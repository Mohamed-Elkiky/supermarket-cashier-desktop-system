from decimal import Decimal
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.departments.models import Department, DepartmentCategory, DepartmentPricingRule, DepartmentStockSettings
from apps.departments.services import apply_rounding, calculate_sell_price, create_category, create_department, delete_category
from apps.staff.models import Staff

User = get_user_model()


@pytest.fixture
def dept(db):
    return create_department(name="Test Department", tax_rate=Decimal("0.2000"), display_order=99)


@pytest.fixture
def pricing_rule(dept):
    return dept.pricing_rule


def _make_staff_user(db, role="cashier"):
    user = User.objects.create_user(email=f"{role}@test.com", password="testpass123")
    test_dept, _ = Department.objects.get_or_create(slug="test-dept-staff", defaults={"name": "Staff Test Dept", "display_order": 999})
    Staff.objects.create(user=user, first_name="Test", last_name=role.capitalize(), email=user.email, role=role, department=test_dept)
    return user


@pytest.fixture
def cashier_client(db):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user(db, "cashier"))
    return client


@pytest.fixture
def manager_client(db):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user(db, "store_manager"))
    return client


@pytest.fixture
def dept_manager_client(db):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user(db, "department_manager"))
    return client


class TestDepartmentModel:
    def test_slug_auto_generated(self, db):
        dept = Department.objects.create(name="Wine & Spirits", display_order=1)
        assert dept.slug == "wine-spirits"

    def test_str_representation(self, db):
        dept = Department.objects.create(name="Bakery", slug="bakery", display_order=2)
        assert str(dept) == "Bakery"


class TestDepartmentCategoryModel:
    def test_depth_level_1(self, dept):
        cat = DepartmentCategory.objects.create(department=dept, name="Vegetables", slug="vegetables")
        assert cat.depth == 1

    def test_depth_level_2(self, dept):
        parent = DepartmentCategory.objects.create(department=dept, name="Vegetables", slug="vegetables")
        child = DepartmentCategory.objects.create(department=dept, parent=parent, name="Root Vegetables", slug="root-vegetables")
        assert child.depth == 2

    def test_cannot_create_level_3(self, dept):
        from django.core.exceptions import ValidationError
        root = DepartmentCategory.objects.create(department=dept, name="Level 1", slug="level-1")
        child = DepartmentCategory.objects.create(department=dept, parent=root, name="Level 2", slug="level-2")
        grandchild = DepartmentCategory(department=dept, parent=child, name="Level 3", slug="level-3")
        with pytest.raises(ValidationError, match="two levels"):
            grandchild.clean()


class TestApplyRounding:
    def test_nearest_penny(self):
        assert apply_rounding(123, "nearest_penny") == 123

    def test_nearest_5p(self):
        assert apply_rounding(123, "nearest_5p") == 125
        assert apply_rounding(121, "nearest_5p") == 120

    def test_nearest_10p(self):
        assert apply_rounding(135, "nearest_10p") == 140

    def test_psychological(self):
        assert apply_rounding(205, "psychological") == 199

    def test_unknown_fallback(self):
        assert apply_rounding(100, "unknown") == 100


class TestCalculateSellPrice:
    def test_basic_markup(self, pricing_rule):
        pricing_rule.default_markup_percent = Decimal("25.00")
        pricing_rule.rounding_strategy = "nearest_penny"
        pricing_rule.minimum_margin_percent = Decimal("0.00")
        pricing_rule.save()
        assert calculate_sell_price(100, pricing_rule) == 125

    def test_minimum_margin_enforced(self, pricing_rule):
        pricing_rule.default_markup_percent = Decimal("5.00")
        pricing_rule.minimum_margin_percent = Decimal("20.00")
        pricing_rule.save()
        with pytest.raises(ValueError, match="below the department minimum"):
            calculate_sell_price(100, pricing_rule)

    def test_zero_cost_raises(self, pricing_rule):
        with pytest.raises(ValueError, match="greater than zero"):
            calculate_sell_price(0, pricing_rule)


class TestCreateDepartment:
    def test_creates_with_defaults(self, db):
        dept = create_department(name="Wine Cellar", tax_rate=Decimal("0.2000"))
        assert dept.slug == "wine-cellar"
        assert hasattr(dept, "pricing_rule")
        assert hasattr(dept, "stock_settings")

    def test_duplicate_slug_raises(self, db):
        create_department(name="Confectionery")
        with pytest.raises(ValueError, match="already exists"):
            create_department(name="Confectionery")


class TestCategoryService:
    def test_create_level_1(self, dept):
        cat = create_category(department=dept, name="Fruit")
        assert cat.parent is None

    def test_create_level_2(self, dept):
        parent = create_category(department=dept, name="Fruit")
        child = create_category(department=dept, name="Citrus", parent_id=parent.id)
        assert child.parent_id == parent.id

    def test_create_level_3_raises(self, dept):
        parent = create_category(department=dept, name="Fruit")
        child = create_category(department=dept, name="Citrus", parent_id=parent.id)
        with pytest.raises(ValueError, match="Maximum category depth"):
            create_category(department=dept, name="Lemons", parent_id=child.id)

    def test_delete_soft_deletes(self, dept):
        cat = create_category(department=dept, name="Herbs")
        delete_category(cat)
        cat.refresh_from_db()
        assert cat.is_active is False

    def test_delete_parent_deactivates_children(self, dept):
        parent = create_category(department=dept, name="Vegetables")
        child = create_category(department=dept, name="Roots", parent_id=parent.id)
        delete_category(parent)
        child.refresh_from_db()
        assert child.is_active is False


class TestDepartmentListAPI:
    def test_cashier_can_list(self, cashier_client):
        response = cashier_client.get(reverse("department-list-create"))
        assert response.status_code == 200

    def test_unauthenticated_denied(self, db):
        response = APIClient().get(reverse("department-list-create"))
        assert response.status_code == 401

    def test_cashier_cannot_create(self, cashier_client):
        response = cashier_client.post(reverse("department-list-create"), {"name": "X"}, format="json")
        assert response.status_code == 403

    def test_manager_can_create(self, manager_client):
        response = manager_client.post(reverse("department-list-create"), {"name": "Gluten Free", "tax_rate": "0.0000", "display_order": 10}, format="json")
        assert response.status_code == 201
        assert response.data["data"]["slug"] == "gluten-free"


class TestDepartmentDetailAPI:
    def test_retrieve_includes_nested_data(self, cashier_client, dept):
        response = cashier_client.get(reverse("department-detail", kwargs={"pk": dept.pk}))
        assert response.status_code == 200
        data = response.data["data"]
        assert "pricing_rule" in data
        assert "stock_settings" in data
        assert "categories" in data

    def test_cashier_cannot_patch(self, cashier_client, dept):
        response = cashier_client.patch(reverse("department-detail", kwargs={"pk": dept.pk}), {"display_order": 5}, format="json")
        assert response.status_code == 403

    def test_manager_can_patch(self, manager_client, dept):
        response = manager_client.patch(reverse("department-detail", kwargs={"pk": dept.pk}), {"display_order": 5}, format="json")
        assert response.status_code == 200

    def test_invalid_tax_rate_rejected(self, manager_client, dept):
        response = manager_client.patch(reverse("department-detail", kwargs={"pk": dept.pk}), {"tax_rate": "1.5000"}, format="json")
        assert response.status_code == 400


class TestPriceSuggestionAPI:
    def test_basic_suggestion(self, cashier_client, dept):
        dept.pricing_rule.default_markup_percent = Decimal("25.00")
        dept.pricing_rule.minimum_margin_percent = Decimal("0.00")
        dept.pricing_rule.rounding_strategy = "nearest_penny"
        dept.pricing_rule.save()
        response = cashier_client.post(reverse("department-price-suggestion", kwargs={"pk": dept.pk}), {"cost_price_pence": 100}, format="json")
        assert response.status_code == 200
        assert response.data["data"]["suggested_sell_price_pence"] == 125

    def test_zero_cost_rejected(self, cashier_client, dept):
        response = cashier_client.post(reverse("department-price-suggestion", kwargs={"pk": dept.pk}), {"cost_price_pence": 0}, format="json")
        assert response.status_code == 400