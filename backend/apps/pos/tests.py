from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.inventory.services import create_product, create_variant
from apps.staff.models import Staff

from apps.pos.models import Order, Promotion, PromotionVariant
from apps.pos.services import (
    _apply_meal_deals,
    _apply_promotion,
    _find_best_promotion,
    _get_active_promotions,
    add_item,
    confirm_order,
    create_order,
)

User = get_user_model()

NOW = timezone.now()
PAST_START = NOW - timedelta(days=10)
PAST_END = NOW - timedelta(days=1)
FUTURE_START = NOW + timedelta(days=1)
FUTURE_END = NOW + timedelta(days=10)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept_grocery(db):
    return Department.objects.create(name="Grocery Promo", slug="grocery-promo", tax_rate=Decimal("0.2000"), display_order=1)


@pytest.fixture
def dept_produce(db):
    return Department.objects.create(name="Produce Promo", slug="produce-promo", tax_rate=Decimal("0.0000"), display_order=2)


@pytest.fixture
def grocery_variant(dept_grocery):
    product = create_product(department=dept_grocery, name="Baked Beans")
    return create_variant(
        product=product, sku="BEANS-400G", name="Baked Beans 400g",
        pricing_mode="fixed", sell_price=Decimal("10.00"), cost_price=Decimal("5.00"),
    )


@pytest.fixture
def grocery_variant_2(dept_grocery):
    product = create_product(department=dept_grocery, name="Tinned Soup")
    return create_variant(
        product=product, sku="SOUP-400G", name="Tinned Soup 400g",
        pricing_mode="fixed", sell_price=Decimal("2.00"), cost_price=Decimal("1.00"),
    )


@pytest.fixture
def sandwich_variant(dept_produce):
    product = create_product(department=dept_produce, name="Sandwich")
    return create_variant(
        product=product, sku="SANDWICH-01", name="Cheese Sandwich",
        pricing_mode="fixed", sell_price=Decimal("2.00"), cost_price=Decimal("1.00"),
    )


@pytest.fixture
def drink_variant(dept_produce):
    product = create_product(department=dept_produce, name="Drink")
    return create_variant(
        product=product, sku="DRINK-01", name="Bottled Water",
        pricing_mode="fixed", sell_price=Decimal("1.50"), cost_price=Decimal("0.50"),
    )


def _promotion_defaults(**overrides):
    defaults = {
        "name": "Test Promotion",
        "promotion_type": "percentage_discount",
        "discount_value": Decimal("10.00"),
        "starts_at": PAST_START,
        "ends_at": FUTURE_END,
        "is_active": True,
    }
    defaults.update(overrides)
    return defaults


def _build_promotion(**overrides):
    """Unsaved Promotion for pure calculation tests that need no DB access."""
    return Promotion(**_promotion_defaults(**overrides))


def _make_promotion(**overrides):
    """Persisted Promotion — required whenever variant_links/department FKs are queried."""
    return Promotion.objects.create(**_promotion_defaults(**overrides))


def _link_variants(promotion, variants):
    for v in variants:
        PromotionVariant.objects.create(promotion=promotion, variant=v)


def _make_staff_user(role="cashier", suffix=""):
    email = f"{role}{suffix}@promo-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    test_dept, _ = Department.objects.get_or_create(
        slug="promo-staff-test-dept",
        defaults={"name": "Promo Staff Test Dept", "display_order": 999},
    )
    return user, Staff.objects.create(
        user=user, first_name="Test", last_name=role.capitalize(),
        email=email, role=role, department=test_dept,
    )


@pytest.fixture
def cashier_user(db):
    user, staff = _make_staff_user("cashier")
    return staff


@pytest.fixture
def cashier_client(cashier_user):
    client = APIClient()
    client.force_authenticate(user=cashier_user.user)
    return client


@pytest.fixture
def dept_manager_client(db):
    user, staff = _make_staff_user("department_manager")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── _apply_promotion ──────────────────────────────────────────────────────────

class TestApplyPromotion:
    def test_percentage_discount(self):
        promo = _build_promotion(promotion_type="percentage_discount", discount_value=Decimal("10.00"))
        # £10.00 unit price, qty 2 -> line total 2000p, 10% = 200p
        assert _apply_promotion(promo, unit_price_pence=1000, quantity=2) == 200

    def test_fixed_amount_off(self):
        promo = _build_promotion(promotion_type="fixed_amount_off", discount_value=Decimal("3.00"))
        # line total = 1000p (2 x 500), fixed discount 300p
        assert _apply_promotion(promo, unit_price_pence=500, quantity=2) == 300

    def test_fixed_amount_off_never_exceeds_line_total(self):
        promo = _build_promotion(promotion_type="fixed_amount_off", discount_value=Decimal("50.00"))
        # discount would be 5000p but line total is only 500p
        assert _apply_promotion(promo, unit_price_pence=500, quantity=1) == 500

    def test_buy_one_get_one_exact_multiple(self):
        promo = _build_promotion(promotion_type="buy_one_get_one", discount_value=Decimal("1.00"))
        assert _apply_promotion(promo, unit_price_pence=200, quantity=4) == 400  # 2 free

    def test_buy_one_get_one_non_exact_multiple(self):
        promo = _build_promotion(promotion_type="buy_one_get_one", discount_value=Decimal("1.00"))
        # qty=5 -> 2 free items (5 // 2), not 2.5
        assert _apply_promotion(promo, unit_price_pence=200, quantity=5) == 400

    def test_three_for_two_exact_multiple(self):
        promo = _build_promotion(promotion_type="three_for_two", discount_value=Decimal("1.00"))
        assert _apply_promotion(promo, unit_price_pence=300, quantity=6) == 600  # 2 free

    def test_three_for_two_non_exact_multiple(self):
        promo = _build_promotion(promotion_type="three_for_two", discount_value=Decimal("1.00"))
        # qty=4 -> 1 free item (4 // 3), not 1.33
        assert _apply_promotion(promo, unit_price_pence=300, quantity=4) == 300

    def test_meal_deal_returns_zero_at_line_level(self):
        promo = _build_promotion(promotion_type="meal_deal", min_spend_pence=300)
        assert _apply_promotion(promo, unit_price_pence=300, quantity=1) == 0


# ── _find_best_promotion ──────────────────────────────────────────────────────

class TestFindBestPromotion:
    def test_picks_largest_discount(self, dept_grocery, grocery_variant):
        small = _make_promotion(
            name="5% off", promotion_type="percentage_discount",
            discount_value=Decimal("5.00"), department=dept_grocery,
        )
        big = _make_promotion(
            name="£2 off", promotion_type="fixed_amount_off",
            discount_value=Decimal("2.00"), department=dept_grocery,
        )
        promotions = [small, big]
        # unit price £10.00 (1000p), qty 1: 5% = 50p, fixed = 200p -> fixed wins
        best_promo, discount = _find_best_promotion(
            promotions, grocery_variant.id, dept_grocery.id, 1000, 1
        )
        assert best_promo.id == big.id
        assert discount == 200

    def test_meal_deal_excluded_from_per_line_selection(self, dept_grocery, grocery_variant):
        meal_deal = _make_promotion(promotion_type="meal_deal", min_spend_pence=100, department=None)
        best_promo, discount = _find_best_promotion(
            [meal_deal], grocery_variant.id, dept_grocery.id, 1000, 1
        )
        assert best_promo is None
        assert discount == 0

    def test_no_applicable_promotion_returns_none(self, dept_grocery, dept_produce, grocery_variant):
        other_dept_promo = _make_promotion(department=dept_produce)
        best_promo, discount = _find_best_promotion(
            [other_dept_promo], grocery_variant.id, dept_grocery.id, 1000, 1
        )
        assert best_promo is None
        assert discount == 0


# ── _get_active_promotions ────────────────────────────────────────────────────

class TestGetActivePromotions:
    def test_excludes_expired(self, dept_grocery, grocery_variant):
        _make_promotion(name="Expired", department=dept_grocery, starts_at=PAST_START, ends_at=PAST_END)
        active = _get_active_promotions([grocery_variant.id], [dept_grocery.id])
        assert active == []

    def test_excludes_not_yet_started(self, dept_grocery, grocery_variant):
        _make_promotion(name="Future", department=dept_grocery, starts_at=FUTURE_START, ends_at=FUTURE_END)
        active = _get_active_promotions([grocery_variant.id], [dept_grocery.id])
        assert active == []

    def test_includes_currently_active(self, dept_grocery, grocery_variant):
        promo = _make_promotion(name="Active", department=dept_grocery, starts_at=PAST_START, ends_at=FUTURE_END)
        active = _get_active_promotions([grocery_variant.id], [dept_grocery.id])
        assert [p.id for p in active] == [promo.id]

    def test_excludes_inactive_flag(self, dept_grocery, grocery_variant):
        _make_promotion(name="Disabled", department=dept_grocery, is_active=False)
        active = _get_active_promotions([grocery_variant.id], [dept_grocery.id])
        assert active == []


# ── _apply_meal_deals ─────────────────────────────────────────────────────────

@pytest.fixture
def produce_order(sandwich_variant, drink_variant):
    order = create_order()
    add_item(order=order, variant_id=sandwich_variant.id, quantity=1)
    add_item(order=order, variant_id=drink_variant.id, quantity=1)
    return order


class TestApplyMealDeals:
    def _items(self, order):
        items = list(order.items.select_related("variant__product__department").all())
        for i in items:
            i._promotion_applied = False
        return items

    def test_below_min_spend_not_applied(self, produce_order, sandwich_variant, drink_variant):
        # group spend = 200 + 150 = 350p, require 1000p minimum -> should not qualify
        meal_deal = _make_promotion(
            promotion_type="meal_deal", discount_value=Decimal("1.00"),
            min_spend_pence=1000, department=None,
        )
        _link_variants(meal_deal, [sandwich_variant, drink_variant])
        discount, tax_delta = _apply_meal_deals([meal_deal], self._items(produce_order))
        assert discount == 0
        assert tax_delta == 0

    def test_meets_min_spend_spreads_proportionally(self, produce_order, sandwich_variant, drink_variant):
        # group spend = 350p >= 300p minimum, discount_value = £1.00 (100p)
        meal_deal = _make_promotion(
            promotion_type="meal_deal", discount_value=Decimal("1.00"),
            min_spend_pence=300, department=None,
        )
        _link_variants(meal_deal, [sandwich_variant, drink_variant])
        items = self._items(produce_order)
        discount, tax_delta = _apply_meal_deals([meal_deal], items)
        assert discount == 100
        # sandwich (200p) gets 200/350 * 100 = 57p, drink (150p) gets 150/350 * 100 = 43p
        sandwich_item = next(i for i in items if i.variant_id == sandwich_variant.id)
        drink_item = next(i for i in items if i.variant_id == drink_variant.id)
        assert sandwich_item.discount_pence == 57
        assert drink_item.discount_pence == 43
        # produce department has 0% tax, so no tax adjustment either way
        assert tax_delta == 0

    def test_already_promoted_line_excluded(self, produce_order, sandwich_variant, drink_variant):
        meal_deal = _make_promotion(
            promotion_type="meal_deal", discount_value=Decimal("1.00"),
            min_spend_pence=100, department=None,
        )
        _link_variants(meal_deal, [sandwich_variant, drink_variant])
        items = self._items(produce_order)
        # mark the sandwich as already having a per-line promotion applied
        sandwich_item = next(i for i in items if i.variant_id == sandwich_variant.id)
        sandwich_item._promotion_applied = True

        discount, tax_delta = _apply_meal_deals([meal_deal], items)

        sandwich_item.refresh_from_db()
        drink_item = next(i for i in items if i.variant_id == drink_variant.id)
        # only the drink (150p) is eligible now, and it alone meets the 100p minimum
        assert discount == 100
        assert drink_item.discount_pence == 100
        assert sandwich_item.promotion_id is None
        assert sandwich_item.discount_pence == 0


# ── confirm_order end-to-end ──────────────────────────────────────────────────

class TestConfirmOrderEndToEnd:
    def test_percentage_and_meal_deal_reconcile(
        self, dept_grocery, dept_produce, grocery_variant, sandwich_variant, drink_variant,
    ):
        grocery_promo = _make_promotion(
            name="Grocery 10% off", promotion_type="percentage_discount",
            discount_value=Decimal("10.00"), department=dept_grocery,
        )
        meal_deal = _make_promotion(
            name="Lunch Meal Deal", promotion_type="meal_deal",
            discount_value=Decimal("1.00"), min_spend_pence=300, department=None,
        )
        _link_variants(meal_deal, [sandwich_variant, drink_variant])

        order = create_order()
        add_item(order=order, variant_id=grocery_variant.id, quantity=1)   # £10.00
        add_item(order=order, variant_id=sandwich_variant.id, quantity=1)  # £2.00
        add_item(order=order, variant_id=drink_variant.id, quantity=1)     # £1.50

        order = confirm_order(order=order)

        # subtotal = 1000 + 200 + 150
        assert order.subtotal_pence == 1350
        # grocery: 10% of 1000 = 100. meal deal: 100 spread across sandwich/drink (57 + 43)
        assert order.discount_total_pence == 200
        # grocery line after discount = 900, taxed at 20% = 180. produce dept taxed at 0%.
        assert order.tax_total_pence == 180
        assert order.total_pence == (
            order.subtotal_pence - order.discount_total_pence + order.tax_total_pence
        )
        assert order.total_pence == 1330

        items = {i.variant_id: i for i in order.items.all()}
        assert items[grocery_variant.id].promotion_id == grocery_promo.id
        assert items[grocery_variant.id].discount_pence == 100
        assert items[sandwich_variant.id].promotion_id == meal_deal.id
        assert items[sandwich_variant.id].discount_pence == 57
        assert items[drink_variant.id].promotion_id == meal_deal.id
        assert items[drink_variant.id].discount_pence == 43


# ── Promotion management API ──────────────────────────────────────────────────

class TestPromotionAPI:
    def _payload(self, **overrides):
        data = {
            "name": "New Year Sale",
            "promotion_type": "percentage_discount",
            "discount_value": "15.00",
            "starts_at": PAST_START.isoformat(),
            "ends_at": FUTURE_END.isoformat(),
        }
        data.update(overrides)
        return data

    def test_cashier_forbidden_on_create(self, cashier_client, dept_grocery):
        response = cashier_client.post(
            reverse("promotion-list-create"),
            self._payload(department=dept_grocery.id),
            format="json",
        )
        assert response.status_code == 403

    def test_cashier_forbidden_on_update(self, cashier_client, dept_grocery):
        promo = _make_promotion(department=dept_grocery)
        response = cashier_client.patch(
            reverse("promotion-detail", kwargs={"pk": promo.pk}),
            {"discount_value": "20.00"},
            format="json",
        )
        assert response.status_code == 403

    def test_cashier_forbidden_on_deactivate(self, cashier_client, dept_grocery):
        promo = _make_promotion(department=dept_grocery)
        response = cashier_client.post(reverse("promotion-deactivate", kwargs={"pk": promo.pk}))
        assert response.status_code == 403

    def test_cashier_can_list(self, cashier_client, dept_grocery):
        _make_promotion(department=dept_grocery)
        response = cashier_client.get(reverse("promotion-list-create"))
        assert response.status_code == 200

    def test_manager_can_create(self, dept_manager_client, dept_grocery):
        response = dept_manager_client.post(
            reverse("promotion-list-create"),
            self._payload(department=dept_grocery.id),
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["name"] == "New Year Sale"

    def test_manager_can_list_with_filters(self, dept_manager_client, dept_grocery):
        _make_promotion(department=dept_grocery, promotion_type="percentage_discount")
        response = dept_manager_client.get(
            reverse("promotion-list-create"),
            {"is_active": "true", "department": dept_grocery.id, "promotion_type": "percentage_discount"},
        )
        assert response.status_code == 200
        assert len(response.data["data"]) == 1

    def test_manager_can_update(self, dept_manager_client, dept_grocery):
        promo = _make_promotion(department=dept_grocery)
        response = dept_manager_client.patch(
            reverse("promotion-detail", kwargs={"pk": promo.pk}),
            {"discount_value": "25.00"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["discount_value"] == "25.00"

    def test_manager_can_deactivate(self, dept_manager_client, dept_grocery):
        promo = _make_promotion(department=dept_grocery)
        response = dept_manager_client.post(reverse("promotion-deactivate", kwargs={"pk": promo.pk}))
        assert response.status_code == 200
        assert response.data["data"]["is_active"] is False

    def test_invalid_date_range_rejected(self, dept_manager_client, dept_grocery):
        response = dept_manager_client.post(
            reverse("promotion-list-create"),
            self._payload(
                department=dept_grocery.id,
                starts_at=FUTURE_END.isoformat(),
                ends_at=PAST_START.isoformat(),
            ),
            format="json",
        )
        assert response.status_code == 400
        assert response.data["success"] is False
        assert "error" in response.data

    def test_meal_deal_missing_min_spend_rejected(self, dept_manager_client, sandwich_variant):
        response = dept_manager_client.post(
            reverse("promotion-list-create"),
            self._payload(
                promotion_type="meal_deal",
                variant_ids=[sandwich_variant.id],
            ),
            format="json",
        )
        assert response.status_code == 400
        assert response.data["success"] is False

    def test_meal_deal_missing_variant_ids_rejected(self, dept_manager_client):
        response = dept_manager_client.post(
            reverse("promotion-list-create"),
            self._payload(promotion_type="meal_deal", min_spend_pence=500),
            format="json",
        )
        assert response.status_code == 400
        assert response.data["success"] is False

    def test_meal_deal_with_required_fields_created(self, dept_manager_client, sandwich_variant, drink_variant):
        response = dept_manager_client.post(
            reverse("promotion-list-create"),
            self._payload(
                promotion_type="meal_deal",
                min_spend_pence=300,
                variant_ids=[sandwich_variant.id, drink_variant.id],
            ),
            format="json",
        )
        assert response.status_code == 201, response.data
        assert sorted(response.data["data"]["variant_ids"]) == sorted([sandwich_variant.id, drink_variant.id])
