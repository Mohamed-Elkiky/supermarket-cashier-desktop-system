# backend/apps/pos/services.py
import logging
import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import models, transaction
from django.utils import timezone

from .models import Order, OrderItem, Promotion, PromotionVariant

logger = logging.getLogger("apps.pos")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pence(amount: Decimal) -> int:
    """Convert a Decimal pound amount to integer pence, rounding half-up."""
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _generate_receipt_number() -> str:
    return f"RCP-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"


# ── Promotion engine ──────────────────────────────────────────────────────────

def _get_active_promotions(variant_ids: list, department_ids: list) -> list:
    """
    Fetch all active promotions that could apply to the basket.
    Meal deal promotions are always fetched regardless of department scope
    because they span multiple departments by design.
    Returns promotions ordered by discount_value descending.
    """
    now = timezone.now()
    return list(
        Promotion.objects
        .filter(is_active=True, starts_at__lte=now, ends_at__gte=now)
        .filter(
            models.Q(variant_links__variant_id__in=variant_ids) |
            models.Q(department_id__in=department_ids, variant_links__isnull=True) |
            models.Q(promotion_type="meal_deal")
        )
        .distinct()
        .order_by("-discount_value")
    )


def _apply_promotion(promotion: Promotion, unit_price_pence: int, quantity: int) -> int:
    """
    Calculate discount in pence for a single order line.
    Returns discount_pence (always >= 0).
    """
    t = promotion.promotion_type

    if t == "percentage_discount" or t == "category_markdown":
        rate = Decimal(str(promotion.discount_value)) / 100
        return int((Decimal(unit_price_pence * quantity) * rate).to_integral_value(ROUND_HALF_UP))

    if t == "fixed_amount_off":
        discount = _pence(promotion.discount_value)
        return min(discount, unit_price_pence * quantity)

    if t == "buy_one_get_one":
        free_items = quantity // 2
        return free_items * unit_price_pence

    if t == "three_for_two":
        free_items = quantity // 3
        return free_items * unit_price_pence

    if t == "meal_deal":
        # Handled at basket level in _apply_meal_deals — never at line level.
        return 0

    return 0


def _find_best_promotion(promotions: list, variant_id: int, department_id: int,
                         unit_price_pence: int, quantity: int):
    """
    Find the best applicable per-line promotion and return
    (promotion, discount_pence) or (None, 0).
    Meal deal promotions are explicitly excluded here — they are handled
    at basket level by _apply_meal_deals.
    """
    applicable = []
    for p in promotions:
        if p.promotion_type == "meal_deal":
            continue
        variant_ids = list(p.variant_links.values_list("variant_id", flat=True))
        if variant_ids and variant_id not in variant_ids:
            continue
        if not variant_ids and p.department_id != department_id:
            continue
        discount = _apply_promotion(p, unit_price_pence, quantity)
        applicable.append((p, discount))

    if not applicable:
        return None, 0

    applicable.sort(key=lambda x: x[1], reverse=True)
    return applicable[0]


def _apply_meal_deals(promotions: list, items: list) -> tuple[int, int]:
    """
    Apply meal deal promotions across the basket.

    A meal deal qualifies when the combined line total of its linked
    variants meets or exceeds min_spend_pence. The discount
    (promotion.discount_value, stored in pounds) is applied once per
    qualifying group, spread proportionally across qualifying lines so
    per-line tax calculation remains correct.

    Items that already have a per-line promotion applied are excluded —
    meal deals do not stack with other promotions.

    Returns (extra_discount_total_pence, extra_tax_adjustment_pence).
    """
    meal_deals = [p for p in promotions if p.promotion_type == "meal_deal"]
    if not meal_deals:
        return 0, 0

    extra_discount_total = 0
    extra_tax_adjustment = 0

    for deal in meal_deals:
        deal_variant_ids = set(
            deal.variant_links.values_list("variant_id", flat=True)
        )
        if not deal_variant_ids:
            # Misconfigured meal deal with no variant scope — skip safely.
            continue

        discount_per_group_pence = _pence(deal.discount_value)
        min_spend = deal.min_spend_pence or 0

        # Exclude items that already have a per-line promotion.
        # Use promotion_applied flag set during the per-line loop rather than
        # checking promotion_id, which is unreliable on in-memory objects.
        eligible = [
            i for i in items
            if i.variant_id in deal_variant_ids and not getattr(i, "_promotion_applied", False)
        ]
        if not eligible:
            continue

        group_spend = sum(i.unit_price_pence * i.quantity for i in eligible)
        if group_spend < min_spend:
            continue

        # Group qualifies — spread discount proportionally across eligible lines.
        for item in eligible:
            line_value = item.unit_price_pence * item.quantity
            proportion = Decimal(line_value) / Decimal(group_spend)
            line_discount = int(
                (proportion * discount_per_group_pence).to_integral_value(ROUND_HALF_UP)
            )
            line_discount = min(line_discount, line_value)

            dept = item.variant.product.department
            tax_rate = Decimal(str(dept.tax_rate))

            old_tax = int(
                (Decimal(item.line_total_pence) * tax_rate).to_integral_value(ROUND_HALF_UP)
            )
            new_line_total = item.line_total_pence - line_discount
            new_tax = int(
                (Decimal(new_line_total) * tax_rate).to_integral_value(ROUND_HALF_UP)
            )

            item.promotion = deal
            item.discount_pence = (item.discount_pence or 0) + line_discount
            item.line_total_pence = new_line_total
            item.save(update_fields=["promotion", "discount_pence", "line_total_pence"])

            extra_discount_total += line_discount
            extra_tax_adjustment += new_tax - old_tax

    return extra_discount_total, extra_tax_adjustment


# ── Order lifecycle ───────────────────────────────────────────────────────────

def create_order(*, cashier=None) -> Order:
    """Open a new empty basket."""
    order = Order.objects.create(cashier=cashier)
    logger.info("Order #%s created by cashier=%s", order.id, getattr(cashier, "id", None))
    return order


def add_item(
    *,
    order: Order,
    variant_id: int,
    quantity: int = 1,
    weight_kg: Decimal = None,
) -> OrderItem:
    """
    Add or update an item in an open basket.
    Raises ValueError if the order is not open or the variant is expired/inactive.
    """
    from apps.inventory.models import ProductVariant
    from apps.inventory.services import check_basket_for_expired

    if order.status != "open":
        raise ValueError(f"Cannot modify order #{order.id} — status is '{order.status}'.")

    variant = ProductVariant.objects.select_related("product__department").get(
        pk=variant_id, is_active=True
    )

    blocked = check_basket_for_expired([{
        "variant_id": variant_id,
        "department_id": variant.product.department_id,
        "batch_ref": None,
    }])
    if blocked:
        raise ValueError(
            f"Cannot add '{variant.name}' — expired stock: {blocked[0]['reason']}"
        )

    if variant.pricing_mode == "weight_based":
        if not weight_kg or weight_kg <= 0:
            raise ValueError(f"'{variant.name}' is weight-based; weight_kg is required.")
        unit_price_pence = _pence(variant.sell_price * Decimal(str(weight_kg)))
        qty = 1
    else:
        unit_price_pence = _pence(variant.sell_price)
        qty = quantity

    item = OrderItem.objects.create(
        order=order,
        variant=variant,
        variant_name_snapshot=variant.name,
        unit_price_pence=unit_price_pence,
        weight_kg=weight_kg,
        quantity=qty,
        line_total_pence=unit_price_pence * qty,
    )

    order.refresh_from_db()
    _recalculate_order_totals(order)
    logger.info("Added item variant=%s qty=%s to order #%s", variant_id, qty, order.id)
    return item


def remove_item(*, order: Order, item_id: int) -> None:
    """Remove a line from an open basket."""
    if order.status != "open":
        raise ValueError(f"Cannot modify order #{order.id} — status is '{order.status}'.")
    order.items.filter(pk=item_id).delete()
    _recalculate_order_totals(order)


def confirm_order(*, order: Order) -> Order:
    """
    Lock the basket — apply promotions, calculate final totals.
    Moves order from 'open' to 'confirmed'.
    """
    if order.status != "open":
        raise ValueError(f"Order #{order.id} is already '{order.status}'.")
    if not order.items.exists():
        raise ValueError("Cannot confirm an empty order.")

    items = list(order.items.select_related("variant__product__department").all())
    variant_ids = [i.variant_id for i in items]
    department_ids = list({i.variant.product.department_id for i in items})

    promotions = _get_active_promotions(variant_ids, department_ids)

    subtotal = 0
    discount_total = 0
    tax_total = 0

    for item in items:
        dept = item.variant.product.department
        promotion, discount_pence = _find_best_promotion(
            promotions,
            item.variant_id,
            dept.id,
            item.unit_price_pence,
            item.quantity,
        )
        line_before_discount = item.unit_price_pence * item.quantity
        line_after_discount = line_before_discount - discount_pence

        tax_rate = Decimal(str(dept.tax_rate))
        tax_pence = int((Decimal(line_after_discount) * tax_rate).to_integral_value(ROUND_HALF_UP))

        item.promotion = promotion
        item.discount_pence = discount_pence
        item.line_total_pence = line_after_discount
        # Flag used by _apply_meal_deals to detect items already promoted.
        item._promotion_applied = promotion is not None
        item.save(update_fields=["promotion", "discount_pence", "line_total_pence"])

        subtotal += line_before_discount
        discount_total += discount_pence
        tax_total += tax_pence

    # Apply meal deal promotions across the basket (basket-level, not per-line).
    meal_discount, meal_tax_delta = _apply_meal_deals(promotions, items)
    discount_total += meal_discount
    tax_total += meal_tax_delta

    total = subtotal - discount_total + tax_total

    order.status = "confirmed"
    order.subtotal_pence = subtotal
    order.discount_total_pence = discount_total
    order.tax_total_pence = tax_total
    order.total_pence = total
    order.save(update_fields=[
        "status", "subtotal_pence", "discount_total_pence",
        "tax_total_pence", "total_pence", "updated_at",
    ])

    logger.info(
        "Order #%s confirmed — subtotal=%dp discount=%dp (meal_deal=%dp) tax=%dp total=%dp",
        order.id, subtotal, discount_total, meal_discount, tax_total, total,
    )
    return order


@transaction.atomic
def checkout(
    *,
    order: Order,
    payment_method: str,
    cash_tendered_pence: int = None,
    age_verified: bool = False,
    age_verification_id_type: str = "",
    customer=None,
) -> Order:
    """
    Complete payment and deduct stock. All-or-nothing — runs inside a
    single DB transaction. If any step fails the order stays 'confirmed'
    and no stock is deducted.

    Steps:
      1. Validate order is confirmed and payment details are correct
      2. Re-check all items for expiry (safety net in case time passed)
      3. Deduct stock via ledger record_movement() for each line
      4. Award loyalty points if a customer is attached to this checkout
      5. Generate receipt number
      6. Mark order paid

    customer: an apps.loyalty.models.Customer, or None for a guest checkout
    (no points are earned). Passed in per-call rather than stored on Order —
    the link to the earning order is recorded on the LoyaltyTransaction
    itself (LoyaltyTransaction.order), so no schema change to Order is needed.
    """
    from apps.inventory.services import record_movement, check_basket_for_expired

    if order.status != "confirmed":
        raise ValueError(f"Order #{order.id} must be confirmed before checkout. Status: '{order.status}'.")

    if payment_method not in dict(Order.PAYMENT_METHOD_CHOICES):
        raise ValueError(f"Invalid payment_method '{payment_method}'.")

    if payment_method == "cash":
        if not cash_tendered_pence:
            raise ValueError("cash_tendered_pence is required for cash payments.")
        if cash_tendered_pence < order.total_pence:
            raise ValueError(
                f"Cash tendered ({cash_tendered_pence}p) is less than order total ({order.total_pence}p)."
            )

    items = list(order.items.select_related("variant__product__department").all())
    has_age_restricted = any(i.variant.product.is_age_restricted for i in items)
    if has_age_restricted and not age_verified:
        raise ValueError(
            "This order contains age-restricted items. age_verified must be True."
        )

    basket_lines = [
        {
            "variant_id": i.variant_id,
            "department_id": i.variant.product.department_id,
            "batch_ref": None,
        }
        for i in items
    ]
    blocked = check_basket_for_expired(basket_lines)
    if blocked:
        names = ", ".join(b["name"] for b in blocked)
        raise ValueError(f"Checkout blocked — expired items in basket: {names}")

    for item in items:
        dept = item.variant.product.department
        record_movement(
            variant=item.variant,
            department=dept,
            movement_type="sale",
            quantity=Decimal(str(-item.quantity)),
            performed_by=order.cashier,
            order_id=order.id,
            reason=f"Order #{order.id} checkout",
        )

    change_given = None
    if payment_method == "cash" and cash_tendered_pence:
        change_given = cash_tendered_pence - order.total_pence

    points_earned = 0
    if customer is not None:
        from apps.loyalty.services import award_points

        loyalty_account = getattr(customer, "loyalty_account", None)
        if loyalty_account is None:
            raise ValueError(f"Customer #{customer.id} has no loyalty account.")
        loyalty_txn = award_points(loyalty_account=loyalty_account, order=order)
        points_earned = loyalty_txn.points

    now = timezone.now()
    order.status = "paid"
    order.payment_method = payment_method
    order.cash_tendered_pence = cash_tendered_pence
    order.change_given_pence = change_given
    order.age_verified = age_verified
    order.age_verification_id_type = age_verification_id_type or ""
    order.loyalty_points_earned = points_earned
    order.receipt_number = _generate_receipt_number()
    order.paid_at = now
    order.save(update_fields=[
        "status", "payment_method", "cash_tendered_pence", "change_given_pence",
        "age_verified", "age_verification_id_type", "loyalty_points_earned",
        "receipt_number", "paid_at", "updated_at",
    ])

    logger.info(
        "Order #%s paid — method=%s total=%dp receipt=%s",
        order.id, payment_method, order.total_pence, order.receipt_number,
    )
    return order


def deactivate_promotion(*, promotion: Promotion) -> Promotion:
    """Deactivate a promotion. Idempotent — no-op if already inactive."""
    promotion.is_active = False
    promotion.save(update_fields=["is_active", "updated_at"])
    logger.info("Deactivated promotion #%s", promotion.id)
    return promotion


def void_order(*, order: Order, reason: str = "") -> Order:
    """
    Void an open or confirmed order. Paid orders cannot be voided — use returns.
    """
    if order.status == "paid":
        raise ValueError("Paid orders cannot be voided. Process a return instead.")
    if order.status == "voided":
        raise ValueError(f"Order #{order.id} is already voided.")

    order.status = "voided"
    order.voided_at = timezone.now()
    order.notes = f"{order.notes}\nVoided: {reason}".strip()
    order.save(update_fields=["status", "voided_at", "notes", "updated_at"])
    logger.info("Order #%s voided — reason: %s", order.id, reason)
    return order


def _recalculate_order_totals(order: Order) -> None:
    """Recalculate running totals on an open order after items change."""
    total = sum(i.line_total_pence for i in order.items.all())
    order.subtotal_pence = total
    order.total_pence = total
    order.save(update_fields=["subtotal_pence", "total_pence", "updated_at"])


def build_receipt(order: Order) -> dict:
    """
    Build a structured receipt dict from a paid order.
    Used by the receipt endpoint and the Electron print driver.
    """
    if order.status != "paid":
        raise ValueError("Receipt is only available for paid orders.")

    items = list(order.items.select_related("variant__product__department", "promotion").all())

    return {
        "receipt_number": order.receipt_number,
        "paid_at": order.paid_at.isoformat(),
        "cashier": (
            f"{order.cashier.first_name} {order.cashier.last_name}".strip()
            if order.cashier else "Unknown"
        ),
        "items": [
            {
                "name": item.variant_name_snapshot,
                "sku": item.variant.sku,
                "quantity": item.quantity,
                "weight_kg": float(item.weight_kg) if item.weight_kg else None,
                "unit_price_display": f"£{item.unit_price_pence / 100:.2f}",
                "discount_display": f"-£{item.discount_pence / 100:.2f}" if item.discount_pence else None,
                "promotion_name": item.promotion.name if item.promotion else None,
                "line_total_display": f"£{item.line_total_pence / 100:.2f}",
            }
            for item in items
        ],
        "subtotal_display":       f"£{order.subtotal_pence / 100:.2f}",
        "discount_total_display": f"-£{order.discount_total_pence / 100:.2f}",
        "tax_total_display":      f"£{order.tax_total_pence / 100:.2f}",
        "total_display":          f"£{order.total_pence / 100:.2f}",
        "payment_method":         order.payment_method,
        "cash_tendered_display":  f"£{order.cash_tendered_pence / 100:.2f}" if order.cash_tendered_pence else None,
        "change_display":         f"£{order.change_given_pence / 100:.2f}" if order.change_given_pence else None,
        "loyalty_points_earned":  order.loyalty_points_earned,
        "age_verified":           order.age_verified,
    }