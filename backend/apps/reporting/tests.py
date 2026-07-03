from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.inventory.models import InventoryLedger
from apps.inventory.services import create_product, create_variant
from apps.pos.models import Order, OrderItem
from apps.staff.models import Staff
from apps.staff.services import calculate_commission

from .services import (
    get_best_sellers,
    get_department_performance,
    get_sales_dashboard,
    get_staff_performance,
    get_waste_cost,
)

User = get_user_model()

DAY_1 = date(2026, 6, 1)
DAY_2 = date(2026, 6, 2)
OUTSIDE_RANGE = date(2026, 1, 1)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept_grocery(db):
    return Department.objects.create(
        name="Grocery Reporting", slug="grocery-reporting", tax_rate=Decimal("0.2000"), display_order=1,
    )


@pytest.fixture
def dept_produce(db):
    return Department.objects.create(
        name="Produce Reporting", slug="produce-reporting", tax_rate=Decimal("0.0000"), display_order=2,
    )


@pytest.fixture
def variant_beans(dept_grocery):
    # Small margin per unit (sell 2.00, cost 1.90) but sells in high volume.
    product = create_product(department=dept_grocery, name="Baked Beans")
    return create_variant(
        product=product, sku="BEANS-REPORT", name="Baked Beans", pricing_mode="fixed",
        sell_price=Decimal("2.00"), cost_price=Decimal("1.90"),
    )


@pytest.fixture
def variant_apples(dept_produce):
    # Big margin per kg (sell 3.00, cost 0.10) but sells in low volume —
    # deliberately the inverse of beans, so units vs margin ranking flips.
    product = create_product(department=dept_produce, name="Apples")
    return create_variant(
        product=product, sku="APPLES-REPORT", name="Apples (per kg)", pricing_mode="weight_based",
        sell_price=Decimal("3.00"), cost_price=Decimal("0.10"), unit_of_measure="kg",
    )


@pytest.fixture
def cashier_staff(dept_grocery):
    return Staff.objects.create(
        first_name="Casey", last_name="Cashier", email="casey@reporting-test.com",
        role="cashier", department=dept_grocery,
        commission_rate=Decimal("0.0100"), hourly_wage=Decimal("10.00"),
    )


def _aware(d, t):
    return timezone.make_aware(datetime.combine(d, t))


def _make_order(cashier, total_pence, paid_at, payment_method="card", status="paid"):
    return Order.objects.create(
        cashier=cashier, status=status, total_pence=total_pence,
        subtotal_pence=total_pence, payment_method=payment_method, paid_at=paid_at,
    )


def _make_item(order, variant, *, line_total_pence, quantity=1, weight_kg=None):
    return OrderItem.objects.create(
        order=order, variant=variant, variant_name_snapshot=variant.name,
        unit_price_pence=line_total_pence, quantity=quantity, weight_kg=weight_kg,
        line_total_pence=line_total_pence,
    )


def _make_ledger_entry(variant, department, movement_type, quantity, recorded_at):
    entry = InventoryLedger.objects.create(
        variant=variant, department=department, movement_type=movement_type, quantity=Decimal(str(quantity)),
    )
    # recorded_at is auto_now_add — backdate via a bulk update, which bypasses
    # both auto_now_add and the model's immutable save() override (neither
    # applies to queryset-level .update()).
    InventoryLedger.objects.filter(pk=entry.pk).update(recorded_at=recorded_at)
    entry.refresh_from_db()
    return entry


@pytest.fixture
def sales_fixture(dept_grocery, dept_produce, variant_beans, variant_apples, cashier_staff):
    """
    Three paid orders with known totals/lines, plus one out-of-range and one
    unpaid order that must be excluded from every aggregate below.

    Order A: cashier, £10.00, card, day 1 — 3x beans, line total 600p (cost 570p, margin 30p)
    Order B: cashier, £20.00, cash, day 1 — 2kg apples, line total 600p (cost 20p, margin 580p)
    Order C: no cashier, £5.00, card, day 2 — 2x beans, line total 400p (cost 380p, margin 20p)
    """
    order_a = _make_order(cashier_staff, 1000, _aware(DAY_1, time(9, 0)), payment_method="card")
    _make_item(order_a, variant_beans, line_total_pence=600, quantity=3)

    order_b = _make_order(cashier_staff, 2000, _aware(DAY_1, time(14, 0)), payment_method="cash")
    _make_item(order_b, variant_apples, line_total_pence=600, weight_kg=Decimal("2"))

    order_c = _make_order(None, 500, _aware(DAY_2, time(10, 0)), payment_method="card")
    _make_item(order_c, variant_beans, line_total_pence=400, quantity=2)

    # Out of range — must never appear in range-filtered aggregates.
    order_outside = _make_order(cashier_staff, 999_999, _aware(OUTSIDE_RANGE, time(9, 0)))
    _make_item(order_outside, variant_beans, line_total_pence=999_999, quantity=1)

    # Unpaid — must never appear in "paid" aggregates.
    _make_order(cashier_staff, 888_888, None, status="confirmed")

    return {"a": order_a, "b": order_b, "c": order_c}


def _make_staff_user(role="cashier", suffix="", department=None):
    email = f"{role}{suffix}@reporting-api-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    Staff.objects.create(
        user=user, first_name="Test", last_name=role.capitalize(), email=email, role=role, department=department,
    )
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


# ── Sales dashboard ────────────────────────────────────────────────────────────

class TestGetSalesDashboard:
    def test_totals_match_known_fixture(self, sales_fixture):
        data = get_sales_dashboard(date_from=DAY_1, date_to=DAY_2)
        assert data["total_revenue_pence"] == 1000 + 2000 + 500
        assert data["order_count"] == 3
        assert data["average_basket_pence"] == round((1000 + 2000 + 500) / 3)

    def test_revenue_by_day(self, sales_fixture):
        data = get_sales_dashboard(date_from=DAY_1, date_to=DAY_2)
        by_day = {row["date"]: row for row in data["revenue_by_day"]}
        assert by_day[DAY_1.isoformat()]["revenue_pence"] == 3000
        assert by_day[DAY_1.isoformat()]["order_count"] == 2
        assert by_day[DAY_2.isoformat()]["revenue_pence"] == 500
        assert by_day[DAY_2.isoformat()]["order_count"] == 1

    def test_revenue_by_payment_method(self, sales_fixture):
        data = get_sales_dashboard(date_from=DAY_1, date_to=DAY_2)
        by_method = {row["payment_method"]: row for row in data["revenue_by_payment_method"]}
        assert by_method["card"]["revenue_pence"] == 1500
        assert by_method["cash"]["revenue_pence"] == 2000

    def test_out_of_range_and_unpaid_excluded(self, sales_fixture):
        data = get_sales_dashboard(date_from=DAY_1, date_to=DAY_2)
        assert data["total_revenue_pence"] != 1000 + 2000 + 500 + 999_999
        assert data["order_count"] == 3

    def test_department_filter_does_not_double_count(self, sales_fixture, dept_grocery):
        data = get_sales_dashboard(date_from=DAY_1, date_to=DAY_2, department=dept_grocery)
        # Only orders A (grocery) and C (grocery) — order B is produce-only.
        assert data["order_count"] == 2
        assert data["total_revenue_pence"] == 1000 + 500


# ── Department performance ────────────────────────────────────────────────────

class TestGetDepartmentPerformance:
    def test_revenue_margin_and_transaction_count(self, sales_fixture, dept_grocery, dept_produce):
        rows = get_department_performance(date_from=DAY_1, date_to=DAY_2)
        by_id = {row["department_id"]: row for row in rows}

        grocery = by_id[dept_grocery.id]
        assert grocery["revenue_pence"] == 600 + 400
        assert grocery["margin_pence"] == 30 + 20
        assert grocery["transaction_count"] == 2

        produce = by_id[dept_produce.id]
        assert produce["revenue_pence"] == 600
        assert produce["margin_pence"] == 580
        assert produce["transaction_count"] == 1

    def test_ranked_by_revenue_descending(self, sales_fixture, dept_grocery, dept_produce):
        rows = get_department_performance(date_from=DAY_1, date_to=DAY_2)
        assert rows[0]["department_id"] == dept_grocery.id
        assert rows[1]["department_id"] == dept_produce.id


# ── Best sellers ───────────────────────────────────────────────────────────────

class TestGetBestSellers:
    def test_units_metric_ranks_beans_first(self, sales_fixture, variant_beans, variant_apples):
        rows = get_best_sellers(date_from=DAY_1, date_to=DAY_2, metric="units")
        assert rows[0]["variant_id"] == variant_beans.id
        assert rows[0]["units_sold"] == 5.0  # 3 + 2
        assert rows[1]["variant_id"] == variant_apples.id
        assert rows[1]["units_sold"] == 2.0

    def test_margin_metric_ranks_apples_first(self, sales_fixture, variant_beans, variant_apples):
        rows = get_best_sellers(date_from=DAY_1, date_to=DAY_2, metric="margin")
        assert rows[0]["variant_id"] == variant_apples.id
        assert rows[0]["margin_pence"] == 580
        assert rows[1]["variant_id"] == variant_beans.id
        assert rows[1]["margin_pence"] == 50

    def test_department_filter(self, sales_fixture, dept_produce, variant_apples):
        rows = get_best_sellers(date_from=DAY_1, date_to=DAY_2, department=dept_produce)
        assert len(rows) == 1
        assert rows[0]["variant_id"] == variant_apples.id

    def test_limit(self, sales_fixture):
        rows = get_best_sellers(date_from=DAY_1, date_to=DAY_2, limit=1)
        assert len(rows) == 1

    def test_invalid_metric_raises(self, sales_fixture):
        with pytest.raises(ValueError, match="metric must be"):
            get_best_sellers(date_from=DAY_1, date_to=DAY_2, metric="bogus")


# ── Waste cost ─────────────────────────────────────────────────────────────────

class TestGetWasteCost:
    def test_grand_total_and_breakdowns(self, dept_grocery, dept_produce, variant_beans, variant_apples):
        _make_ledger_entry(variant_beans, dept_grocery, "waste", -5, _aware(DAY_1, time(9, 0)))       # 5 * 1.90 = 950p
        _make_ledger_entry(variant_apples, dept_produce, "markdown", -3, _aware(DAY_1, time(9, 0)))   # 3 * 0.10 = 30p
        # Out of range — excluded.
        _make_ledger_entry(variant_beans, dept_grocery, "waste", -10, _aware(OUTSIDE_RANGE, time(9, 0)))
        # Wrong movement type — excluded even though in range.
        _make_ledger_entry(variant_beans, dept_grocery, "sale", -1, _aware(DAY_1, time(10, 0)))

        data = get_waste_cost(date_from=DAY_1, date_to=DAY_2)
        assert data["grand_total_pence"] == 950 + 30

        by_dept = {row["department_id"]: row for row in data["by_department"]}
        assert by_dept[dept_grocery.id]["cost_pence"] == 950
        assert by_dept[dept_produce.id]["cost_pence"] == 30

        by_variant = {row["variant_id"]: row for row in data["by_variant"]}
        assert by_variant[variant_beans.id]["cost_pence"] == 950
        assert by_variant[variant_apples.id]["cost_pence"] == 30

    def test_department_filter(self, dept_grocery, dept_produce, variant_beans, variant_apples):
        _make_ledger_entry(variant_beans, dept_grocery, "waste", -5, _aware(DAY_1, time(9, 0)))
        _make_ledger_entry(variant_apples, dept_produce, "markdown", -3, _aware(DAY_1, time(9, 0)))

        data = get_waste_cost(date_from=DAY_1, date_to=DAY_2, department=dept_grocery)
        assert data["grand_total_pence"] == 950
        assert len(data["by_department"]) == 1


# ── Staff performance ──────────────────────────────────────────────────────────

class TestGetStaffPerformance:
    def test_totals_and_average_basket(self, sales_fixture, cashier_staff):
        rows = get_staff_performance(date_from=DAY_1, date_to=DAY_2)
        row = next(r for r in rows if r["staff_id"] == cashier_staff.id)
        assert row["total_sales_pence"] == 1000 + 2000  # order C has no cashier
        assert row["transaction_count"] == 2
        assert row["average_basket_pence"] == round((1000 + 2000) / 2)

    def test_commission_matches_staff_service_exactly(self, sales_fixture, cashier_staff):
        """
        Must reuse apps.staff.services.calculate_commission, not
        reimplement it — assert the two numbers are identical, not just
        both 'plausible', so the two calculations can never silently drift.
        """
        expected_commission = calculate_commission(staff=cashier_staff, date_from=DAY_1, date_to=DAY_2)
        rows = get_staff_performance(date_from=DAY_1, date_to=DAY_2)
        row = next(r for r in rows if r["staff_id"] == cashier_staff.id)
        assert row["commission_pence"] == expected_commission
        assert expected_commission == round((1000 + 2000) * 0.01)  # 1% of £30.00

    def test_filter_by_staff(self, sales_fixture, cashier_staff, dept_grocery):
        other_staff = Staff.objects.create(
            first_name="Other", last_name="One", email="other-perf@reporting-test.com",
            role="cashier", department=dept_grocery,
        )
        rows = get_staff_performance(date_from=DAY_1, date_to=DAY_2, staff=cashier_staff)
        assert len(rows) == 1
        assert rows[0]["staff_id"] == cashier_staff.id


# ── API permission boundaries + validation ────────────────────────────────────

REPORTING_ENDPOINTS = [
    "sales-dashboard",
    "department-performance",
    "best-sellers",
    "waste-cost",
    "staff-performance",
]


class TestReportingAPIPermissions:
    @pytest.mark.parametrize("url_name", REPORTING_ENDPOINTS)
    def test_cashier_forbidden(self, cashier_client, url_name):
        response = cashier_client.get(reverse(url_name), {"date_from": "2026-06-01", "date_to": "2026-06-02"})
        assert response.status_code == 403

    @pytest.mark.parametrize("url_name", REPORTING_ENDPOINTS)
    def test_unauthenticated_denied(self, anon_client, url_name):
        response = anon_client.get(reverse(url_name), {"date_from": "2026-06-01", "date_to": "2026-06-02"})
        assert response.status_code == 401

    @pytest.mark.parametrize("url_name", REPORTING_ENDPOINTS)
    def test_manager_allowed(self, manager_client, url_name):
        response = manager_client.get(reverse(url_name), {"date_from": "2026-06-01", "date_to": "2026-06-02"})
        assert response.status_code == 200

    @pytest.mark.parametrize("url_name", REPORTING_ENDPOINTS)
    def test_missing_date_params_returns_400(self, manager_client, url_name):
        response = manager_client.get(reverse(url_name))
        assert response.status_code == 400
        assert response.data["success"] is False

    @pytest.mark.parametrize("url_name", REPORTING_ENDPOINTS)
    def test_date_to_before_date_from_returns_400(self, manager_client, url_name):
        response = manager_client.get(reverse(url_name), {"date_from": "2026-06-30", "date_to": "2026-06-01"})
        assert response.status_code == 400


class TestReportingAPIShapes:
    def test_sales_dashboard_envelope(self, manager_client, sales_fixture):
        response = manager_client.get(reverse("sales-dashboard"), {"date_from": "2026-06-01", "date_to": "2026-06-02"})
        assert response.status_code == 200
        assert response.data["success"] is True
        assert response.data["data"]["total_revenue_pence"] == 3500

    def test_best_sellers_metric_switching_via_api(self, manager_client, sales_fixture, variant_beans, variant_apples):
        units_resp = manager_client.get(
            reverse("best-sellers"), {"date_from": "2026-06-01", "date_to": "2026-06-02", "metric": "units"}
        )
        margin_resp = manager_client.get(
            reverse("best-sellers"), {"date_from": "2026-06-01", "date_to": "2026-06-02", "metric": "margin"}
        )
        assert units_resp.data["data"][0]["variant_id"] == variant_beans.id
        assert margin_resp.data["data"][0]["variant_id"] == variant_apples.id

    def test_department_performance_department_filter_rejects_unknown(self, manager_client):
        response = manager_client.get(
            reverse("department-performance"), {"date_from": "2026-06-01", "date_to": "2026-06-02"}
        )
        assert response.status_code == 200

    def test_waste_cost_unknown_department_returns_404(self, manager_client):
        response = manager_client.get(
            reverse("waste-cost"), {"date_from": "2026-06-01", "date_to": "2026-06-02", "department": 999999}
        )
        assert response.status_code == 404
