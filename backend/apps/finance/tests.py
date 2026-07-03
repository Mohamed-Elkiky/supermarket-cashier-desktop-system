from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse
from rest_framework.test import APIClient

from apps.inventory.models import Supplier
from apps.staff.models import Staff

from .models import Expense
from .services import get_expense_summary_by_category, get_expenses, record_expense

User = get_user_model()

VALID_DESCRIPTION = "Paid supplier invoice #1234 for weekly bread delivery"  # > 20 chars


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_staff_user(role="cashier", suffix=""):
    email = f"{role}{suffix}@finance-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    staff = Staff.objects.create(
        user=user, first_name="Test", last_name=role.capitalize(), email=email, role=role,
    )
    return user, staff


@pytest.fixture
def manager_staff(db):
    _, staff = _make_staff_user("department_manager", suffix="1")
    return staff


@pytest.fixture
def cashier_client(db):
    user, _ = _make_staff_user("cashier")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def manager_client(db):
    user, _ = _make_staff_user("department_manager", suffix="2")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def anon_client(db):
    return APIClient()


@pytest.fixture
def supplier(db):
    return Supplier.objects.create(name="Acme Supplies")


@pytest.fixture
def activity_log_table(db):
    """
    activity_log is written via raw SQL in apps.core.activity.log_activity()
    and has no Django model/migration of its own. Create it here (full
    column set, matching V009__activity_log.sql) so we can assert the
    ActivityLogMixin write actually happened.
    """
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id BIGSERIAL PRIMARY KEY,
                    actor_staff_id INTEGER,
                    actor_role VARCHAR(30),
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(100) NOT NULL,
                    entity_id VARCHAR(50) NOT NULL,
                    before_state JSONB,
                    after_state JSONB,
                    device_identifier VARCHAR(255),
                    ip_address INET,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_staff_id INTEGER,
                    actor_role VARCHAR(30),
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(100) NOT NULL,
                    entity_id VARCHAR(50) NOT NULL,
                    before_state TEXT,
                    after_state TEXT,
                    device_identifier VARCHAR(255),
                    ip_address VARCHAR(45),
                    occurred_at DATETIME NOT NULL
                )
            """)
    yield
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS activity_log")


# ── record_expense ─────────────────────────────────────────────────────────────

class TestRecordExpense:
    def test_creates_expense(self, manager_staff):
        expense = record_expense(
            category="utilities", description=VALID_DESCRIPTION, amount_pence=5000,
            recorded_by=manager_staff, expense_date=date(2026, 6, 1),
        )
        assert expense.id is not None
        assert expense.amount_pence == 5000
        assert expense.category == "utilities"

    def test_description_under_20_chars_rejected(self, manager_staff):
        with pytest.raises(ValueError, match="minimum 20 characters"):
            record_expense(
                category="other", description="paid supplier", amount_pence=1000,
                recorded_by=manager_staff, expense_date=date(2026, 6, 1),
            )

    def test_description_exactly_20_chars_accepted(self, manager_staff):
        desc = "x" * 20
        expense = record_expense(
            category="other", description=desc, amount_pence=1000,
            recorded_by=manager_staff, expense_date=date(2026, 6, 1),
        )
        assert expense.description == desc

    def test_description_length_checked_after_trimming(self, manager_staff):
        # 18 real characters padded with whitespace to 25 total — trimmed length is 18.
        desc = "   " + ("x" * 18) + "    "
        with pytest.raises(ValueError, match="minimum 20 characters"):
            record_expense(
                category="other", description=desc, amount_pence=1000,
                recorded_by=manager_staff, expense_date=date(2026, 6, 1),
            )

    def test_amount_zero_rejected(self, manager_staff):
        with pytest.raises(ValueError, match="greater than 0"):
            record_expense(
                category="other", description=VALID_DESCRIPTION, amount_pence=0,
                recorded_by=manager_staff, expense_date=date(2026, 6, 1),
            )

    def test_amount_negative_rejected(self, manager_staff):
        with pytest.raises(ValueError, match="greater than 0"):
            record_expense(
                category="other", description=VALID_DESCRIPTION, amount_pence=-100,
                recorded_by=manager_staff, expense_date=date(2026, 6, 1),
            )

    def test_supplier_link(self, manager_staff, supplier):
        expense = record_expense(
            category="supplier_payment", description=VALID_DESCRIPTION, amount_pence=2000,
            recorded_by=manager_staff, expense_date=date(2026, 6, 1), supplier=supplier,
        )
        assert expense.supplier_id == supplier.id


# ── Immutability ──────────────────────────────────────────────────────────────

class TestExpenseImmutability:
    def test_update_raises(self, manager_staff):
        expense = record_expense(
            category="rent", description=VALID_DESCRIPTION, amount_pence=100_000,
            recorded_by=manager_staff, expense_date=date(2026, 6, 1),
        )
        expense.amount_pence = 999
        with pytest.raises(ValueError, match="immutable"):
            expense.save()

    def test_delete_raises(self, manager_staff):
        expense = record_expense(
            category="rent", description=VALID_DESCRIPTION, amount_pence=100_000,
            recorded_by=manager_staff, expense_date=date(2026, 6, 1),
        )
        with pytest.raises(ValueError, match="cannot be deleted"):
            expense.delete()

    def test_no_updated_at_column(self):
        assert "updated_at" not in [f.name for f in Expense._meta.get_fields()]


# ── get_expenses filters ───────────────────────────────────────────────────────

class TestGetExpenses:
    def test_filter_by_category(self, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        record_expense(category="utilities", description=VALID_DESCRIPTION, amount_pence=2000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 2))
        results = get_expenses(category="rent")
        assert len(results) == 1
        assert results[0].category == "rent"

    def test_filter_by_date_range(self, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 1, 1))
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 15))
        results = get_expenses(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert len(results) == 1
        assert results[0].expense_date == date(2026, 6, 15)

    def test_filter_by_supplier(self, manager_staff, supplier):
        other_supplier = Supplier.objects.create(name="Other Co")
        record_expense(category="supplier_payment", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1), supplier=supplier)
        record_expense(category="supplier_payment", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1), supplier=other_supplier)
        results = get_expenses(supplier=supplier)
        assert len(results) == 1
        assert results[0].supplier_id == supplier.id


# ── get_expense_summary_by_category ───────────────────────────────────────────

class TestExpenseSummaryByCategory:
    def test_aggregates_across_categories_within_range(self, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=100_000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=50_000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 15))
        record_expense(category="utilities", description=VALID_DESCRIPTION, amount_pence=20_000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 10))
        # Outside the queried range — must not be included.
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=999_999,
                        recorded_by=manager_staff, expense_date=date(2026, 1, 1))

        summary = get_expense_summary_by_category(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        by_category = {row["category"]: row for row in summary}

        assert len(summary) == 2
        assert by_category["rent"]["total_pence"] == 150_000
        assert by_category["rent"]["count"] == 2
        assert by_category["utilities"]["total_pence"] == 20_000
        assert by_category["utilities"]["count"] == 1


# ── Expense API ────────────────────────────────────────────────────────────────

class TestExpenseAPI:
    def test_cashier_forbidden_on_list(self, cashier_client):
        response = cashier_client.get(reverse("expense-list-create"))
        assert response.status_code == 403

    def test_cashier_forbidden_on_create(self, cashier_client):
        response = cashier_client.post(
            reverse("expense-list-create"),
            {"category": "other", "description": VALID_DESCRIPTION, "amount_pence": 1000, "expense_date": "2026-06-01"},
            format="json",
        )
        assert response.status_code == 403

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("expense-list-create"))
        assert response.status_code == 401

    def test_manager_can_create(self, manager_client):
        response = manager_client.post(
            reverse("expense-list-create"),
            {"category": "utilities", "description": VALID_DESCRIPTION, "amount_pence": 5000, "expense_date": "2026-06-01"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["category"] == "utilities"
        assert response.data["data"]["amount_pence"] == 5000

    def test_manager_can_list(self, manager_client, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        response = manager_client.get(reverse("expense-list-create"))
        assert response.status_code == 200
        assert len(response.data["data"]) == 1

    def test_list_filters_by_category(self, manager_client, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=1000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        record_expense(category="marketing", description=VALID_DESCRIPTION, amount_pence=2000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        response = manager_client.get(reverse("expense-list-create"), {"category": "marketing"})
        assert response.status_code == 200
        assert len(response.data["data"]) == 1
        assert response.data["data"][0]["category"] == "marketing"

    def test_description_too_short_returns_400_with_helpful_message(self, manager_client):
        response = manager_client.post(
            reverse("expense-list-create"),
            {"category": "other", "description": "paid supplier", "amount_pence": 1000, "expense_date": "2026-06-01"},
            format="json",
        )
        assert response.status_code == 400
        assert "minimum 20 characters" in str(response.data["error"]["errors"])

    def test_amount_zero_returns_400(self, manager_client):
        response = manager_client.post(
            reverse("expense-list-create"),
            {"category": "other", "description": VALID_DESCRIPTION, "amount_pence": 0, "expense_date": "2026-06-01"},
            format="json",
        )
        assert response.status_code == 400


# ── Expense summary API ────────────────────────────────────────────────────────

class TestExpenseSummaryAPI:
    def test_cashier_forbidden(self, cashier_client):
        response = cashier_client.get(reverse("expense-summary"), {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        assert response.status_code == 403

    def test_manager_can_view_summary(self, manager_client, manager_staff):
        record_expense(category="rent", description=VALID_DESCRIPTION, amount_pence=100_000,
                        recorded_by=manager_staff, expense_date=date(2026, 6, 1))
        response = manager_client.get(reverse("expense-summary"), {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        assert response.status_code == 200
        assert response.data["data"][0]["category"] == "rent"
        assert response.data["data"][0]["total_pence"] == 100_000

    def test_missing_date_params_returns_400(self, manager_client):
        response = manager_client.get(reverse("expense-summary"))
        assert response.status_code == 400

    def test_date_to_before_date_from_returns_400(self, manager_client):
        response = manager_client.get(
            reverse("expense-summary"), {"date_from": "2026-06-30", "date_to": "2026-06-01"}
        )
        assert response.status_code == 400


# ── ActivityLogMixin verification ─────────────────────────────────────────────

class TestExpenseActivityLogging:
    def test_create_writes_activity_log_entry(self, manager_client, activity_log_table):
        response = manager_client.post(
            reverse("expense-list-create"),
            {
                "category": "utilities",
                "description": VALID_DESCRIPTION,
                "amount_pence": 15_000,
                "expense_date": "2026-06-30",
            },
            format="json",
        )
        assert response.status_code == 201, response.data
        expense_id = response.data["data"]["id"]

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT action, entity_type, entity_id FROM activity_log WHERE entity_type = %s",
                ["expenses"],
            )
            rows = cursor.fetchall()

        assert len(rows) == 1
        action, entity_type, entity_id = rows[0]
        assert action == "expense.create"
        assert entity_type == "expenses"
        assert entity_id == str(expense_id)
