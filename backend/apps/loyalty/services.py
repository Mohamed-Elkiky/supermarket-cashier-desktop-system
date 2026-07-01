import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import Customer, LoyaltyAccount, LoyaltyTransaction

logger = logging.getLogger("apps.loyalty")

# 1 point per £1 spent at bronze, scaled up per tier.
BASE_POINTS_PER_PENCE = Decimal("0.01")
TIER_EARN_MULTIPLIER = {
    LoyaltyAccount.Tier.BRONZE: Decimal("1.00"),
    LoyaltyAccount.Tier.SILVER: Decimal("1.25"),
    LoyaltyAccount.Tier.GOLD: Decimal("1.50"),
}
SILVER_THRESHOLD_PENCE = 500_00
GOLD_THRESHOLD_PENCE = 1_500_00
_TIER_RANK = {LoyaltyAccount.Tier.BRONZE: 0, LoyaltyAccount.Tier.SILVER: 1, LoyaltyAccount.Tier.GOLD: 2}


# ── Customer CRUD ─────────────────────────────────────────────────────────────

def _normalize_date_of_birth(value):
    """date_of_birth is stored as an encrypted ISO-8601 string (see model
    comment) — accept either a date object or a string and normalise."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


@transaction.atomic
def create_customer(
    *, first_name, last_name, email=None, phone="",
    date_of_birth=None, address_line1=None, address_line2=None, city=None, postcode=None,
    allergen_preferences=None, marketing_consent=False,
) -> Customer:
    """Creates a Customer and auto-creates its LoyaltyAccount at bronze tier."""
    customer = Customer(
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=phone,
        date_of_birth=_normalize_date_of_birth(date_of_birth),
        address_line1=address_line1,
        address_line2=address_line2,
        city=city,
        postcode=postcode,
        allergen_preferences=allergen_preferences or [],
        marketing_consent=marketing_consent,
        marketing_consent_at=timezone.now() if marketing_consent else None,
    )
    customer.full_clean()
    customer.save()
    LoyaltyAccount.objects.create(customer=customer, tier=LoyaltyAccount.Tier.BRONZE)
    logger.info("Created customer id=%s", customer.id)
    return customer


@transaction.atomic
def update_customer(customer: Customer, validated_data: dict) -> Customer:
    data = dict(validated_data)
    if "date_of_birth" in data:
        data["date_of_birth"] = _normalize_date_of_birth(data["date_of_birth"])

    if "marketing_consent" in data:
        turning_on = data["marketing_consent"] and not customer.marketing_consent
        turning_off = not data["marketing_consent"]
        if turning_on:
            data.setdefault("marketing_consent_at", timezone.now())
        elif turning_off:
            data.setdefault("marketing_consent_at", None)

    for attr, value in data.items():
        setattr(customer, attr, value)
    customer.full_clean()
    customer.save()
    logger.info("Updated customer id=%s", customer.id)
    return customer


def search_customers(query: str) -> list:
    """
    Searches by email/phone (plaintext columns, so a simple indexed
    icontains/exact query) or by name.

    first_name/last_name are encrypted at rest (EncryptedField/Fernet), whose
    ciphertext is non-deterministic and cannot be pushed down to SQL — there
    is no way to index or filter on it in the database. The name-search path
    below decrypts and compares every active customer in Python instead. This
    is fine at the scale of a single store's customer list; it does NOT scale
    to a multi-store/national customer base — that would need a separate
    deterministic blind-index column (e.g. a keyed HMAC of the lowercased
    name) rather than trying to search the encrypted column directly.
    """
    query = (query or "").strip()
    if not query:
        return []

    matches = list(
        Customer.objects.filter(is_active=True).filter(
            Q(email__icontains=query) | Q(phone__icontains=query)
        )
    )
    matched_ids = {c.id for c in matches}

    query_lower = query.lower()
    for customer in Customer.objects.filter(is_active=True).exclude(id__in=matched_ids):
        full_name = f"{customer.first_name} {customer.last_name}".lower()
        if query_lower in full_name:
            matches.append(customer)

    return matches


# ── Tier / points math ────────────────────────────────────────────────────────

def _recalculate_points_balance(loyalty_account: LoyaltyAccount) -> int:
    total = loyalty_account.transactions.aggregate(total=Sum("points"))["total"]
    return total or 0


def _evaluate_tier(current_tier: str, lifetime_spend_pence: int) -> str:
    """Tiers are cumulative and never downgrade automatically."""
    if lifetime_spend_pence >= GOLD_THRESHOLD_PENCE:
        earned_tier = LoyaltyAccount.Tier.GOLD
    elif lifetime_spend_pence >= SILVER_THRESHOLD_PENCE:
        earned_tier = LoyaltyAccount.Tier.SILVER
    else:
        earned_tier = LoyaltyAccount.Tier.BRONZE

    if _TIER_RANK[earned_tier] > _TIER_RANK[current_tier]:
        return earned_tier
    return current_tier


@transaction.atomic
def award_points(*, loyalty_account: LoyaltyAccount, order) -> LoyaltyTransaction:
    """
    Creates an 'earn' transaction for a completed order, based on the
    account's CURRENT tier earn rate (evaluated before this order's spend is
    added to lifetime_spend_pence — an order that pushes the customer into a
    new tier earns at the OLD rate; the new tier's rate applies from the next
    order onward). Updates lifetime_spend_pence, points_balance, and
    re-evaluates tier (never downgrades).
    """
    multiplier = TIER_EARN_MULTIPLIER[loyalty_account.tier]
    points = int(Decimal(order.total_pence) * BASE_POINTS_PER_PENCE * multiplier)

    txn = LoyaltyTransaction(
        loyalty_account=loyalty_account,
        transaction_type=LoyaltyTransaction.TransactionType.EARN,
        points=points,
        order=order,
    )
    txn.full_clean()
    txn.save()

    loyalty_account.lifetime_spend_pence += order.total_pence
    loyalty_account.points_balance = _recalculate_points_balance(loyalty_account)
    loyalty_account.tier = _evaluate_tier(loyalty_account.tier, loyalty_account.lifetime_spend_pence)
    loyalty_account.save(update_fields=["lifetime_spend_pence", "points_balance", "tier", "updated_at"])

    logger.info(
        "Awarded %d points to loyalty_account #%s (tier=%s) for order #%s",
        points, loyalty_account.id, loyalty_account.tier, order.id,
    )
    return txn


@transaction.atomic
def redeem_points(*, loyalty_account: LoyaltyAccount, points: int) -> LoyaltyTransaction:
    if points <= 0:
        raise ValueError("points must be a positive number to redeem.")

    current_balance = _recalculate_points_balance(loyalty_account)
    if points > current_balance:
        raise ValueError(
            f"Insufficient points balance: has {current_balance}, requested {points}."
        )

    txn = LoyaltyTransaction(
        loyalty_account=loyalty_account,
        transaction_type=LoyaltyTransaction.TransactionType.REDEEM,
        points=-points,
    )
    txn.full_clean()
    txn.save()

    loyalty_account.points_balance = _recalculate_points_balance(loyalty_account)
    loyalty_account.save(update_fields=["points_balance", "updated_at"])

    logger.info("Redeemed %d points from loyalty_account #%s", points, loyalty_account.id)
    return txn


@transaction.atomic
def adjust_points(*, loyalty_account: LoyaltyAccount, points: int, reason: str, performed_by=None) -> LoyaltyTransaction:
    if not reason or not reason.strip():
        raise ValueError("reason is required for a manual point adjustment.")

    txn = LoyaltyTransaction(
        loyalty_account=loyalty_account,
        transaction_type=LoyaltyTransaction.TransactionType.ADJUSTMENT,
        points=points,
        reason=reason,
        performed_by=performed_by,
    )
    txn.full_clean()
    txn.save()

    loyalty_account.points_balance = _recalculate_points_balance(loyalty_account)
    loyalty_account.save(update_fields=["points_balance", "updated_at"])

    logger.info(
        "Adjusted loyalty_account #%s by %d points (reason='%s')",
        loyalty_account.id, points, reason,
    )
    return txn


# ── Allergen conflict check ───────────────────────────────────────────────────

def check_basket_allergen_conflicts(*, customer: Customer, basket_variant_ids: list) -> list:
    """
    Cross-references customer.allergen_preferences against
    ProductVariantAllergen for the given basket variants, for the POS
    basket-conflict warning.
    """
    from apps.inventory.models import ProductVariantAllergen

    preferences = set(customer.allergen_preferences or [])
    if not preferences or not basket_variant_ids:
        return []

    links = (
        ProductVariantAllergen.objects
        .filter(variant_id__in=basket_variant_ids, allergen_id__in=preferences)
        .select_related("variant", "allergen")
    )

    return [
        {
            "variant_id": link.variant_id,
            "variant_name": link.variant.name,
            "allergen_id": link.allergen_id,
            "allergen_name": link.allergen.name,
            "may_contain": link.may_contain,
        }
        for link in links
    ]
