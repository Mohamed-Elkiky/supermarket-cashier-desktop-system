# Note: encryption (Vault) and ArrayField (Postgres-only) sandbox
# compatibility shims live in backend/conftest.py — see that file for why.
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.urls import reverse
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.inventory.models import Allergen, ProductVariantAllergen
from apps.inventory.services import create_product, create_variant
from apps.pos.services import create_order
from apps.staff.models import Staff

from .models import Customer, LoyaltyAccount, LoyaltyTransaction
from .services import (
    GOLD_THRESHOLD_PENCE,
    SILVER_THRESHOLD_PENCE,
    _evaluate_tier,
    adjust_points,
    award_points,
    check_basket_allergen_conflicts,
    create_customer,
    redeem_points,
    search_customers,
    update_customer,
)

User = get_user_model()


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept(db):
    return Department.objects.create(name="Loyalty Test Dept", slug="loyalty-test-dept", display_order=1)


@pytest.fixture
def customer(db):
    return create_customer(first_name="Jane", last_name="Doe", email="jane@loyalty-test.com")


def _make_order(total_pence):
    order = create_order()
    order.subtotal_pence = total_pence
    order.total_pence = total_pence
    order.save(update_fields=["subtotal_pence", "total_pence"])
    return order


def _make_staff_user(role="cashier", suffix=""):
    email = f"{role}{suffix}@loyalty-api-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    Staff.objects.create(user=user, first_name="Test", last_name=role.capitalize(), email=email, role=role)
    return user


@pytest.fixture
def cashier_client(db):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user("cashier"))
    return client


@pytest.fixture
def manager_client(db):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user("department_manager", suffix="2"))
    return client


@pytest.fixture
def anon_client(db):
    return APIClient()


# ── create_customer / update_customer ─────────────────────────────────────────

class TestCreateCustomer:
    def test_auto_creates_bronze_loyalty_account(self, db):
        c = create_customer(first_name="Jane", last_name="Doe", email="jane1@test.com")
        assert c.loyalty_account.tier == LoyaltyAccount.Tier.BRONZE
        assert c.loyalty_account.points_balance == 0
        assert c.loyalty_account.lifetime_spend_pence == 0

    def test_pii_fields_round_trip_through_encryption(self, db):
        c = create_customer(
            first_name="Jane", last_name="Doe", email="jane2@test.com",
            date_of_birth=date(1990, 5, 14), address_line1="1 Test St", postcode="AB1 2CD",
        )
        c.refresh_from_db()
        assert c.first_name == "Jane"
        assert c.last_name == "Doe"
        assert c.date_of_birth == "1990-05-14"
        assert c.address_line1 == "1 Test St"
        assert c.postcode == "AB1 2CD"

    def test_email_and_phone_stay_plaintext_and_queryable(self, db):
        c = create_customer(first_name="A", last_name="B", email="plaintext@test.com", phone="07700900123")
        # If these were encrypted, an exact-match DB filter would never match.
        assert Customer.objects.filter(email="plaintext@test.com").exists()
        assert Customer.objects.filter(phone="07700900123").exists()

    def test_allergen_preferences_default_empty(self, db):
        c = create_customer(first_name="A", last_name="B", email="ab@test.com")
        assert c.allergen_preferences == []


class TestUpdateCustomer:
    def test_updates_fields(self, customer):
        updated = update_customer(customer, {"city": "London"})
        assert updated.city == "London"

    def test_marketing_consent_sets_timestamp(self, customer):
        assert customer.marketing_consent_at is None
        updated = update_customer(customer, {"marketing_consent": True})
        assert updated.marketing_consent_at is not None

    def test_revoking_consent_clears_timestamp(self, customer):
        update_customer(customer, {"marketing_consent": True})
        updated = update_customer(customer, {"marketing_consent": False})
        assert updated.marketing_consent_at is None


class TestSearchCustomers:
    def test_search_by_email(self, customer):
        results = search_customers("jane@loyalty-test.com")
        assert customer.id in [c.id for c in results]

    def test_search_by_phone(self, db):
        c = create_customer(first_name="P", last_name="Q", phone="07700900123", email="pq@test.com")
        results = search_customers("07700900123")
        assert c.id in [r.id for r in results]

    def test_search_by_name_decrypts_in_python(self, customer):
        results = search_customers("Doe")
        assert customer.id in [c.id for c in results]

    def test_empty_query_returns_empty(self, db):
        assert search_customers("") == []
        assert search_customers("   ") == []

    def test_inactive_customers_excluded(self, customer):
        customer.is_active = False
        customer.save()
        results = search_customers("jane")
        assert customer.id not in [c.id for c in results]


# ── award_points / tier math ──────────────────────────────────────────────────

class TestAwardPoints:
    def test_bronze_earn_rate(self, customer):
        order = _make_order(1000)  # £10.00
        txn = award_points(loyalty_account=customer.loyalty_account, order=order)
        assert txn.points == 10
        assert txn.transaction_type == "earn"
        assert txn.order_id == order.id

    def test_silver_earn_rate(self, customer):
        customer.loyalty_account.tier = LoyaltyAccount.Tier.SILVER
        customer.loyalty_account.save()
        order = _make_order(1000)
        txn = award_points(loyalty_account=customer.loyalty_account, order=order)
        assert txn.points == 12  # int(10 * 1.25)

    def test_gold_earn_rate(self, customer):
        customer.loyalty_account.tier = LoyaltyAccount.Tier.GOLD
        customer.loyalty_account.save()
        order = _make_order(1000)
        txn = award_points(loyalty_account=customer.loyalty_account, order=order)
        assert txn.points == 15  # int(10 * 1.5)

    def test_updates_lifetime_spend_and_points_balance(self, customer):
        order = _make_order(1000)
        award_points(loyalty_account=customer.loyalty_account, order=order)
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.lifetime_spend_pence == 1000
        assert customer.loyalty_account.points_balance == 10

    def test_upgrades_bronze_to_silver_at_threshold(self, customer):
        order = _make_order(SILVER_THRESHOLD_PENCE)
        award_points(loyalty_account=customer.loyalty_account, order=order)
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.tier == LoyaltyAccount.Tier.SILVER

    def test_stays_bronze_below_threshold(self, customer):
        order = _make_order(SILVER_THRESHOLD_PENCE - 1)
        award_points(loyalty_account=customer.loyalty_account, order=order)
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.tier == LoyaltyAccount.Tier.BRONZE

    def test_upgrades_silver_to_gold_at_threshold(self, customer):
        customer.loyalty_account.tier = LoyaltyAccount.Tier.SILVER
        customer.loyalty_account.lifetime_spend_pence = SILVER_THRESHOLD_PENCE
        customer.loyalty_account.save()
        order = _make_order(GOLD_THRESHOLD_PENCE - SILVER_THRESHOLD_PENCE)
        award_points(loyalty_account=customer.loyalty_account, order=order)
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.tier == LoyaltyAccount.Tier.GOLD

    def test_tier_never_downgrades(self):
        # Direct unit test on the pure tier-evaluation function: even if the
        # recomputed spend-based tier is lower, the account keeps its rank.
        assert _evaluate_tier(LoyaltyAccount.Tier.GOLD, 0) == LoyaltyAccount.Tier.GOLD
        assert _evaluate_tier(LoyaltyAccount.Tier.SILVER, 0) == LoyaltyAccount.Tier.SILVER
        assert _evaluate_tier(LoyaltyAccount.Tier.BRONZE, GOLD_THRESHOLD_PENCE) == LoyaltyAccount.Tier.GOLD


# ── redeem_points ──────────────────────────────────────────────────────────────

class TestRedeemPoints:
    def test_redeem_reduces_balance(self, customer):
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(10_000))  # 100 pts
        redeem_points(loyalty_account=customer.loyalty_account, points=40)
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.points_balance == 60

    def test_insufficient_balance_raises(self, customer):
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(1000))  # 10 pts
        with pytest.raises(ValueError, match="Insufficient points balance"):
            redeem_points(loyalty_account=customer.loyalty_account, points=100)

    def test_non_positive_points_raises(self, customer):
        with pytest.raises(ValueError, match="positive"):
            redeem_points(loyalty_account=customer.loyalty_account, points=0)


# ── adjust_points ──────────────────────────────────────────────────────────────

class TestAdjustPoints:
    def test_blank_reason_raises(self, customer):
        with pytest.raises(ValueError, match="reason is required"):
            adjust_points(loyalty_account=customer.loyalty_account, points=50, reason="")

    def test_whitespace_only_reason_raises(self, customer):
        with pytest.raises(ValueError, match="reason is required"):
            adjust_points(loyalty_account=customer.loyalty_account, points=50, reason="   ")

    def test_positive_adjustment_updates_balance(self, customer):
        adjust_points(loyalty_account=customer.loyalty_account, points=25, reason="Goodwill gesture")
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.points_balance == 25

    def test_negative_adjustment_updates_balance(self, customer):
        adjust_points(loyalty_account=customer.loyalty_account, points=50, reason="Correction")
        adjust_points(loyalty_account=customer.loyalty_account, points=-20, reason="Reverse part of correction")
        customer.loyalty_account.refresh_from_db()
        assert customer.loyalty_account.points_balance == 30


# ── points_balance reconciliation ─────────────────────────────────────────────

class TestPointsBalanceReconciliation:
    def test_matches_sum_after_multiple_operations(self, customer):
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(1000))   # +10
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(2000))   # +20
        redeem_points(loyalty_account=customer.loyalty_account, points=15)                # -15
        adjust_points(loyalty_account=customer.loyalty_account, points=-5, reason="fix")  # -5

        customer.loyalty_account.refresh_from_db()
        actual_sum = customer.loyalty_account.transactions.aggregate(total=Sum("points"))["total"]
        assert customer.loyalty_account.points_balance == actual_sum
        assert customer.loyalty_account.points_balance == 10


# ── Immutability ──────────────────────────────────────────────────────────────

class TestLoyaltyTransactionImmutability:
    def test_update_raises(self, customer):
        txn = award_points(loyalty_account=customer.loyalty_account, order=_make_order(1000))
        txn.points = 999
        with pytest.raises(ValueError, match="immutable"):
            txn.save()

    def test_delete_raises(self, customer):
        txn = award_points(loyalty_account=customer.loyalty_account, order=_make_order(1000))
        with pytest.raises(ValueError, match="cannot be deleted"):
            txn.delete()

    def test_model_clean_enforces_adjustment_reason(self, customer):
        from django.core.exceptions import ValidationError
        txn = LoyaltyTransaction(
            loyalty_account=customer.loyalty_account,
            transaction_type=LoyaltyTransaction.TransactionType.ADJUSTMENT,
            points=10,
        )
        with pytest.raises(ValidationError):
            txn.full_clean()


# ── Allergen conflict detection ───────────────────────────────────────────────

class TestCheckBasketAllergenConflicts:
    def _make_variant(self, dept, sku, name):
        product = create_product(department=dept, name=name)
        return create_variant(
            product=product, sku=sku, name=name,
            pricing_mode="fixed", sell_price=Decimal("1.00"), cost_price=Decimal("0.50"),
        )

    def test_definite_and_may_contain_conflicts(self, dept, customer):
        allergen_milk = Allergen.objects.create(name="Milk", eu_code="MLK-LT")
        allergen_nuts = Allergen.objects.create(name="Nuts", eu_code="NUT-LT")

        variant_milk = self._make_variant(dept, "SNACK-MILK", "Milk Snack")
        variant_nuts = self._make_variant(dept, "SNACK-NUTS", "Nut Snack")
        variant_safe = self._make_variant(dept, "SNACK-SAFE", "Safe Snack")

        ProductVariantAllergen.objects.create(variant=variant_milk, allergen=allergen_milk, may_contain=False)
        ProductVariantAllergen.objects.create(variant=variant_nuts, allergen=allergen_nuts, may_contain=True)

        customer.allergen_preferences = [allergen_milk.id, allergen_nuts.id]
        customer.save()

        conflicts = check_basket_allergen_conflicts(
            customer=customer,
            basket_variant_ids=[variant_milk.id, variant_nuts.id, variant_safe.id],
        )
        assert len(conflicts) == 2
        by_variant = {c["variant_id"]: c for c in conflicts}
        assert by_variant[variant_milk.id]["may_contain"] is False
        assert by_variant[variant_nuts.id]["may_contain"] is True
        assert by_variant[variant_milk.id]["allergen_name"] == "Milk"

    def test_no_preferences_returns_empty(self, customer):
        assert check_basket_allergen_conflicts(customer=customer, basket_variant_ids=[1, 2]) == []

    def test_no_matching_allergens_returns_empty(self, dept, customer):
        allergen_milk = Allergen.objects.create(name="Milk", eu_code="MLK-LT2")
        variant_safe = self._make_variant(dept, "SNACK-SAFE2", "Safe Snack 2")
        customer.allergen_preferences = [allergen_milk.id]
        customer.save()
        conflicts = check_basket_allergen_conflicts(customer=customer, basket_variant_ids=[variant_safe.id])
        assert conflicts == []


# ── Customer API ──────────────────────────────────────────────────────────────

class TestCustomerAPI:
    def test_cashier_can_create(self, cashier_client):
        response = cashier_client.post(
            reverse("customer-list-create"),
            {"first_name": "Amy", "last_name": "Adams", "email": "amy@api-test.com"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["first_name"] == "Amy"

    def test_duplicate_email_rejected(self, cashier_client, customer):
        response = cashier_client.post(
            reverse("customer-list-create"),
            {"first_name": "Dup", "last_name": "Licate", "email": customer.email},
            format="json",
        )
        assert response.status_code == 400

    def test_cashier_can_list(self, cashier_client, customer):
        response = cashier_client.get(reverse("customer-list-create"))
        assert response.status_code == 200

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("customer-list-create"))
        assert response.status_code == 401

    def test_cashier_can_update(self, cashier_client, customer):
        response = cashier_client.patch(
            reverse("customer-detail", kwargs={"pk": customer.pk}),
            {"city": "Manchester"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["city"] == "Manchester"

    def test_search_by_email(self, cashier_client, customer):
        response = cashier_client.get(reverse("customer-search"), {"q": "jane@loyalty-test.com"})
        assert response.status_code == 200
        assert any(c["id"] == customer.id for c in response.data["data"])


# ── Loyalty profile API ────────────────────────────────────────────────────────

class TestLoyaltyProfileAPI:
    def test_get_profile(self, cashier_client, customer):
        response = cashier_client.get(reverse("customer-loyalty-profile", kwargs={"pk": customer.pk}))
        assert response.status_code == 200
        assert response.data["data"]["tier"] == "bronze"
        assert response.data["data"]["points_balance"] == 0

    def test_includes_transaction_history(self, cashier_client, customer):
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(1000))
        response = cashier_client.get(reverse("customer-loyalty-profile", kwargs={"pk": customer.pk}))
        assert response.status_code == 200
        assert len(response.data["data"]["transactions"]) == 1


# ── Redeem API ────────────────────────────────────────────────────────────────

class TestRedeemPointsAPI:
    def test_cashier_can_redeem(self, cashier_client, customer):
        award_points(loyalty_account=customer.loyalty_account, order=_make_order(10_000))  # 100 pts
        response = cashier_client.post(
            reverse("customer-loyalty-redeem", kwargs={"pk": customer.pk}), {"points": 10}, format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["points_balance"] == 90

    def test_insufficient_balance_returns_400(self, cashier_client, customer):
        response = cashier_client.post(
            reverse("customer-loyalty-redeem", kwargs={"pk": customer.pk}), {"points": 999}, format="json",
        )
        assert response.status_code == 400

    def test_unauthenticated_denied(self, anon_client, customer):
        response = anon_client.post(
            reverse("customer-loyalty-redeem", kwargs={"pk": customer.pk}), {"points": 1}, format="json",
        )
        assert response.status_code == 401


# ── Adjust API — permission boundary ─────────────────────────────────────────

class TestAdjustPointsAPI:
    def test_cashier_forbidden(self, cashier_client, customer):
        response = cashier_client.post(
            reverse("customer-loyalty-adjust", kwargs={"pk": customer.pk}),
            {"points": 10, "reason": "test"}, format="json",
        )
        assert response.status_code == 403

    def test_manager_can_adjust(self, manager_client, customer):
        response = manager_client.post(
            reverse("customer-loyalty-adjust", kwargs={"pk": customer.pk}),
            {"points": 10, "reason": "Goodwill gesture"}, format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["points_balance"] == 10

    def test_manager_missing_reason_returns_400(self, manager_client, customer):
        response = manager_client.post(
            reverse("customer-loyalty-adjust", kwargs={"pk": customer.pk}),
            {"points": 10, "reason": ""}, format="json",
        )
        assert response.status_code == 400


# ── Basket conflict check API ─────────────────────────────────────────────────

class TestBasketConflictCheckAPI:
    def test_cashier_can_check(self, cashier_client, dept, customer):
        allergen = Allergen.objects.create(name="Milk", eu_code="MLK-API")
        product = create_product(department=dept, name="Snack")
        variant = create_variant(
            product=product, sku="SNACK-API", name="Snack",
            pricing_mode="fixed", sell_price=Decimal("1.00"), cost_price=Decimal("0.50"),
        )
        ProductVariantAllergen.objects.create(variant=variant, allergen=allergen, may_contain=False)
        customer.allergen_preferences = [allergen.id]
        customer.save()

        response = cashier_client.post(
            reverse("basket-conflict-check"),
            {"customer_id": customer.id, "variant_ids": [variant.id]},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["has_conflicts"] is True
        assert len(response.data["data"]["conflicts"]) == 1

    def test_no_conflicts(self, cashier_client, dept, customer):
        product = create_product(department=dept, name="Plain")
        variant = create_variant(
            product=product, sku="PLAIN-API", name="Plain",
            pricing_mode="fixed", sell_price=Decimal("1.00"), cost_price=Decimal("0.50"),
        )
        response = cashier_client.post(
            reverse("basket-conflict-check"),
            {"customer_id": customer.id, "variant_ids": [variant.id]},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["has_conflicts"] is False
