from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.inventory.models import Allergen, Product, ProductVariant, ProductVariantAllergen
from apps.inventory.serializers import (
    AllergenWriteSerializer,
    LineTotalSerializer,
    ProductVariantWriteSerializer,
    ProductWriteSerializer,
)
from apps.inventory.services import (
    calculate_line_total,
    create_product,
    create_variant,
    get_variant_by_barcode,
    set_variant_allergens,
)
from apps.staff.models import Staff

User = get_user_model()


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept(db):
    return Department.objects.create(name="Produce", slug="produce", display_order=1)


@pytest.fixture
def product(dept):
    return create_product(department=dept, name="Loose Carrots")


@pytest.fixture
def fixed_variant(product):
    return create_variant(
        product=product,
        sku="CARROT-BAG-1KG",
        name="Carrot Bag 1kg",
        pricing_mode="fixed",
        sell_price=Decimal("1.29"),
        cost_price=Decimal("0.60"),
        unit_of_measure="unit",
        barcode="5000112345678",
    )


@pytest.fixture
def weight_variant(product):
    return create_variant(
        product=product,
        sku="CARROT-LOOSE",
        name="Loose Carrots (per kg)",
        pricing_mode="weight_based",
        sell_price=Decimal("1.50"),
        cost_price=Decimal("0.70"),
        unit_of_measure="kg",
        barcode="2000000000001",
    )


@pytest.fixture
def allergen_gluten(db):
    return Allergen.objects.create(name="Gluten", eu_code="GL")


@pytest.fixture
def allergen_nuts(db):
    return Allergen.objects.create(name="Tree Nuts", eu_code="TN")


def _make_staff_user(role="cashier", suffix=""):
    email = f"{role}{suffix}@test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    test_dept, _ = Department.objects.get_or_create(
        slug="staff-test-dept",
        defaults={"name": "Staff Test Dept", "display_order": 999},
    )
    Staff.objects.create(
        user=user,
        first_name="Test",
        last_name=role.capitalize(),
        email=email,
        role=role,
        department=test_dept,
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
    client.force_authenticate(user=_make_staff_user("department_manager"))
    return client


@pytest.fixture
def anon_client(db):
    return APIClient()


# ── ProductWriteSerializer ────────────────────────────────────────────────────

class TestProductWriteSerializer:
    def test_valid_non_age_restricted(self, dept):
        s = ProductWriteSerializer(data={"department": dept.id, "name": "Milk"})
        assert s.is_valid(), s.errors

    def test_age_restricted_requires_years(self, dept):
        s = ProductWriteSerializer(data={
            "department": dept.id,
            "name": "Whisky",
            "is_age_restricted": True,
        })
        assert not s.is_valid()
        assert "age_restriction_years" in s.errors

    def test_age_restricted_with_years_is_valid(self, dept):
        s = ProductWriteSerializer(data={
            "department": dept.id,
            "name": "Whisky",
            "is_age_restricted": True,
            "age_restriction_years": 18,
        })
        assert s.is_valid(), s.errors

    def test_patch_existing_age_restricted_no_years_in_payload(self, product):
        product.is_age_restricted = True
        product.age_restriction_years = 18
        product.save()
        s = ProductWriteSerializer(product, data={"name": "Updated Name"}, partial=True)
        assert s.is_valid(), s.errors

    def test_patch_setting_age_restricted_without_years_fails(self, product):
        s = ProductWriteSerializer(product, data={"is_age_restricted": True}, partial=True)
        assert not s.is_valid()
        assert "age_restriction_years" in s.errors


# ── ProductVariantWriteSerializer ─────────────────────────────────────────────

class TestProductVariantWriteSerializer:
    def _base(self, **overrides):
        data = {
            "sku": "TEST-001",
            "name": "Test Item",
            "pricing_mode": "fixed",
            "sell_price": "2.00",
            "cost_price": "1.00",
            "unit_of_measure": "unit",
        }
        data.update(overrides)
        return data

    def test_valid_fixed(self):
        s = ProductVariantWriteSerializer(data=self._base())
        assert s.is_valid(), s.errors

    def test_valid_weight_based(self):
        s = ProductVariantWriteSerializer(data=self._base(
            pricing_mode="weight_based", unit_of_measure="kg"
        ))
        assert s.is_valid(), s.errors

    def test_weight_based_with_unit_uom_rejected(self):
        s = ProductVariantWriteSerializer(data=self._base(
            pricing_mode="weight_based", unit_of_measure="unit"
        ))
        assert not s.is_valid()
        assert "unit_of_measure" in s.errors

    def test_fixed_with_kg_uom_rejected(self):
        s = ProductVariantWriteSerializer(data=self._base(
            pricing_mode="fixed", unit_of_measure="kg"
        ))
        assert not s.is_valid()
        assert "unit_of_measure" in s.errors

    def test_sell_below_cost_rejected(self):
        s = ProductVariantWriteSerializer(data=self._base(
            sell_price="0.50", cost_price="1.00"
        ))
        assert not s.is_valid()
        assert "sell_price" in s.errors

    def test_patch_only_price_uses_instance_mode(self, weight_variant):
        s = ProductVariantWriteSerializer(
            weight_variant, data={"sell_price": "2.00"}, partial=True
        )
        assert s.is_valid(), s.errors

    def test_patch_only_price_below_cost_uses_instance_cost(self, fixed_variant):
        s = ProductVariantWriteSerializer(
            fixed_variant, data={"sell_price": "0.50"}, partial=True
        )
        assert not s.is_valid()
        assert "sell_price" in s.errors

    def test_patch_switch_to_weight_without_uom_rejected(self, fixed_variant):
        s = ProductVariantWriteSerializer(
            fixed_variant, data={"pricing_mode": "weight_based"}, partial=True
        )
        assert not s.is_valid()
        assert "unit_of_measure" in s.errors

    def test_patch_switch_to_weight_with_correct_uom_ok(self, fixed_variant):
        s = ProductVariantWriteSerializer(
            fixed_variant,
            data={"pricing_mode": "weight_based", "unit_of_measure": "kg"},
            partial=True,
        )
        assert s.is_valid(), s.errors


# ── AllergenWriteSerializer ───────────────────────────────────────────────────

class TestAllergenWriteSerializer:
    def test_valid_list(self):
        s = AllergenWriteSerializer(data={"allergens": [{"allergen_id": 1, "may_contain": False}]})
        assert s.is_valid(), s.errors

    def test_empty_list_valid(self):
        s = AllergenWriteSerializer(data={"allergens": []})
        assert s.is_valid(), s.errors

    def test_missing_allergen_id_rejected(self):
        s = AllergenWriteSerializer(data={"allergens": [{"may_contain": False}]})
        assert not s.is_valid()

    def test_non_integer_allergen_id_rejected(self):
        s = AllergenWriteSerializer(data={"allergens": [{"allergen_id": "one"}]})
        assert not s.is_valid()

    def test_non_bool_may_contain_rejected(self):
        s = AllergenWriteSerializer(data={"allergens": [{"allergen_id": 1, "may_contain": "yes"}]})
        assert not s.is_valid()


# ── LineTotalSerializer ───────────────────────────────────────────────────────

class TestLineTotalSerializer:
    def test_weight_valid(self):
        s = LineTotalSerializer(data={"weight_kg": 0.5})
        assert s.is_valid(), s.errors

    def test_weight_zero_rejected(self):
        s = LineTotalSerializer(data={"weight_kg": 0.0})
        assert not s.is_valid()

    def test_quantity_valid(self):
        s = LineTotalSerializer(data={"quantity": 3})
        assert s.is_valid(), s.errors

    def test_quantity_zero_rejected(self):
        s = LineTotalSerializer(data={"quantity": 0})
        assert not s.is_valid()

    def test_defaults_quantity_to_1(self):
        s = LineTotalSerializer(data={})
        assert s.is_valid(), s.errors
        assert s.validated_data["quantity"] == 1


# ── calculate_line_total service ──────────────────────────────────────────────

class TestCalculateLineTotal:
    def test_fixed_single_item(self, fixed_variant):
        result = calculate_line_total(fixed_variant, quantity=1)
        assert result["pricing_mode"] == "fixed"
        assert result["line_total"] == 1.29
        assert result["line_total_display"] == "£1.29"
        assert result["quantity"] == 1

    def test_fixed_multiple_items(self, fixed_variant):
        result = calculate_line_total(fixed_variant, quantity=4)
        assert result["line_total"] == round(1.29 * 4, 2)

    def test_weight_based_calculates_correctly(self, weight_variant):
        result = calculate_line_total(weight_variant, weight_kg=0.456)
        assert result["pricing_mode"] == "weight_based"
        assert result["sell_price_per_kg"] == 1.50
        assert result["weight_kg"] == 0.456
        assert result["line_total"] == round(1.50 * 0.456, 2)

    def test_weight_based_missing_weight_raises(self, weight_variant):
        with pytest.raises(ValueError, match="weight_kg is required"):
            calculate_line_total(weight_variant)

    def test_weight_based_zero_weight_raises(self, weight_variant):
        with pytest.raises(ValueError, match="weight_kg is required"):
            calculate_line_total(weight_variant, weight_kg=0)

    def test_result_includes_sku_and_name(self, fixed_variant):
        result = calculate_line_total(fixed_variant, quantity=1)
        assert result["sku"] == fixed_variant.sku
        assert result["name"] == fixed_variant.name


# ── set_variant_allergens service ─────────────────────────────────────────────

class TestSetVariantAllergens:
    def test_sets_allergens(self, fixed_variant, allergen_gluten, allergen_nuts):
        links = set_variant_allergens(fixed_variant, [
            {"allergen_id": allergen_gluten.id, "may_contain": False},
            {"allergen_id": allergen_nuts.id, "may_contain": True},
        ])
        assert len(links) == 2
        assert fixed_variant.allergen_links.count() == 2

    def test_replaces_existing_allergens(self, fixed_variant, allergen_gluten, allergen_nuts):
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_gluten.id}])
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_nuts.id}])
        links = list(fixed_variant.allergen_links.all())
        assert len(links) == 1
        assert links[0].allergen_id == allergen_nuts.id

    def test_empty_list_clears_allergens(self, fixed_variant, allergen_gluten):
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_gluten.id}])
        set_variant_allergens(fixed_variant, [])
        assert fixed_variant.allergen_links.count() == 0

    def test_unknown_allergen_id_rolls_back(self, fixed_variant, allergen_gluten):
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_gluten.id}])
        assert fixed_variant.allergen_links.count() == 1
        with pytest.raises(Allergen.DoesNotExist):
            set_variant_allergens(fixed_variant, [
                {"allergen_id": allergen_gluten.id},
                {"allergen_id": 99999},
            ])
        assert fixed_variant.allergen_links.count() == 1

    def test_may_contain_flag_stored_correctly(self, fixed_variant, allergen_gluten):
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_gluten.id, "may_contain": True}])
        link = fixed_variant.allergen_links.get()
        assert link.may_contain is True


# ── get_variant_by_barcode service ────────────────────────────────────────────

class TestGetVariantByBarcode:
    def test_finds_active_variant(self, fixed_variant):
        result = get_variant_by_barcode(fixed_variant.barcode)
        assert result.id == fixed_variant.id

    def test_unknown_barcode_raises(self, db):
        with pytest.raises(ProductVariant.DoesNotExist):
            get_variant_by_barcode("0000000000000")

    def test_inactive_variant_not_found(self, fixed_variant):
        fixed_variant.is_active = False
        fixed_variant.save()
        with pytest.raises(ProductVariant.DoesNotExist):
            get_variant_by_barcode(fixed_variant.barcode)

    def test_result_has_product_relation(self, fixed_variant):
        result = get_variant_by_barcode(fixed_variant.barcode)
        assert result.product.name == fixed_variant.product.name


# ── Product list/create API ───────────────────────────────────────────────────

class TestProductListCreateAPI:
    def test_cashier_can_list(self, cashier_client, product):
        response = cashier_client.get(reverse("product-list-create"))
        assert response.status_code == 200
        assert response.data["success"] is True
        ids = [p["id"] for p in response.data["data"]]
        assert product.id in ids

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("product-list-create"))
        assert response.status_code == 401

    def test_cashier_cannot_create(self, cashier_client, dept):
        response = cashier_client.post(
            reverse("product-list-create"),
            {"department": dept.id, "name": "Broccoli"},
            format="json",
        )
        assert response.status_code == 403

    def test_manager_can_create(self, manager_client, dept):
        response = manager_client.post(
            reverse("product-list-create"),
            {"department": dept.id, "name": "Broccoli"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["data"]["name"] == "Broccoli"

    def test_inactive_filtered_by_default(self, cashier_client, product):
        product.is_active = False
        product.save()
        response = cashier_client.get(reverse("product-list-create"))
        ids = [p["id"] for p in response.data["data"]]
        assert product.id not in ids

    def test_active_false_param_includes_inactive(self, cashier_client, product):
        product.is_active = False
        product.save()
        response = cashier_client.get(reverse("product-list-create") + "?active=false")
        ids = [p["id"] for p in response.data["data"]]
        assert product.id in ids

    def test_filter_by_department(self, cashier_client, dept, product):
        other_dept = Department.objects.create(name="Bakery", slug="bakery", display_order=2)
        create_product(department=other_dept, name="Sourdough")
        response = cashier_client.get(reverse("product-list-create") + f"?department={dept.id}")
        for p in response.data["data"]:
            assert p["department"] == dept.id

    def test_age_restricted_without_years_rejected(self, manager_client, dept):
        response = manager_client.post(
            reverse("product-list-create"),
            {"department": dept.id, "name": "Vodka", "is_age_restricted": True},
            format="json",
        )
        assert response.status_code == 400


# ── Product detail API ────────────────────────────────────────────────────────

class TestProductDetailAPI:
    def test_retrieve(self, cashier_client, product):
        response = cashier_client.get(reverse("product-detail", kwargs={"pk": product.pk}))
        assert response.status_code == 200
        assert response.data["data"]["id"] == product.id

    def test_404_on_missing(self, cashier_client):
        response = cashier_client.get(reverse("product-detail", kwargs={"pk": 99999}))
        assert response.status_code == 404

    def test_cashier_cannot_patch(self, cashier_client, product):
        response = cashier_client.patch(
            reverse("product-detail", kwargs={"pk": product.pk}),
            {"name": "New Name"},
            format="json",
        )
        assert response.status_code == 403

    def test_manager_can_patch_name(self, manager_client, product):
        response = manager_client.patch(
            reverse("product-detail", kwargs={"pk": product.pk}),
            {"name": "Organic Carrots"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["name"] == "Organic Carrots"

    def test_manager_can_deactivate(self, manager_client, product):
        response = manager_client.patch(
            reverse("product-detail", kwargs={"pk": product.pk}),
            {"is_active": False},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["is_active"] is False


# ── Variant list/create API ───────────────────────────────────────────────────

class TestVariantListCreateAPI:
    def test_cashier_can_list(self, cashier_client, product, fixed_variant):
        response = cashier_client.get(
            reverse("variant-list-create", kwargs={"pk": product.pk})
        )
        assert response.status_code == 200
        ids = [v["id"] for v in response.data["data"]]
        assert fixed_variant.id in ids

    def test_product_not_found(self, cashier_client):
        response = cashier_client.get(reverse("variant-list-create", kwargs={"pk": 99999}))
        assert response.status_code == 404

    def test_cashier_cannot_create(self, cashier_client, product):
        response = cashier_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {"sku": "X", "name": "X", "sell_price": "1.00", "cost_price": "0.50"},
            format="json",
        )
        assert response.status_code == 403

    def test_manager_creates_fixed_variant(self, manager_client, product):
        response = manager_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {
                "sku": "BROC-1",
                "name": "Broccoli Head",
                "pricing_mode": "fixed",
                "sell_price": "0.89",
                "cost_price": "0.40",
                "unit_of_measure": "unit",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["data"]["pricing_mode"] == "fixed"
        assert response.data["data"]["line_total_example"] == "£0.89"

    def test_manager_creates_weight_based_variant(self, manager_client, product):
        response = manager_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {
                "sku": "CARROT-WB",
                "name": "Loose Carrots",
                "pricing_mode": "weight_based",
                "sell_price": "1.50",
                "cost_price": "0.70",
                "unit_of_measure": "kg",
            },
            format="json",
        )
        assert response.status_code == 201
        assert response.data["data"]["pricing_mode"] == "weight_based"
        assert response.data["data"]["line_total_example"] == "£1.50 per kg"

    def test_weight_based_with_unit_uom_rejected(self, manager_client, product):
        response = manager_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {
                "sku": "BAD-WB",
                "name": "Bad Item",
                "pricing_mode": "weight_based",
                "sell_price": "1.50",
                "cost_price": "0.70",
                "unit_of_measure": "unit",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_sell_below_cost_rejected(self, manager_client, product):
        response = manager_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {
                "sku": "CHEAP-1",
                "name": "Cheap Item",
                "pricing_mode": "fixed",
                "sell_price": "0.30",
                "cost_price": "1.00",
                "unit_of_measure": "unit",
            },
            format="json",
        )
        assert response.status_code == 400

    def test_duplicate_sku_rejected(self, manager_client, product, fixed_variant):
        response = manager_client.post(
            reverse("variant-list-create", kwargs={"pk": product.pk}),
            {
                "sku": fixed_variant.sku,
                "name": "Duplicate",
                "pricing_mode": "fixed",
                "sell_price": "1.00",
                "cost_price": "0.50",
                "unit_of_measure": "unit",
            },
            format="json",
        )
        assert response.status_code == 400


# ── Variant detail API ────────────────────────────────────────────────────────

class TestVariantDetailAPI:
    def test_retrieve(self, cashier_client, product, fixed_variant):
        response = cashier_client.get(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk})
        )
        assert response.status_code == 200
        assert response.data["data"]["sku"] == fixed_variant.sku

    def test_variant_not_found(self, cashier_client, product):
        response = cashier_client.get(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": 99999})
        )
        assert response.status_code == 404

    def test_cashier_cannot_patch(self, cashier_client, product, fixed_variant):
        response = cashier_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"name": "Updated"},
            format="json",
        )
        assert response.status_code == 403

    def test_manager_can_patch_name(self, manager_client, product, fixed_variant):
        response = manager_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"name": "Carrot Bag 2kg"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["name"] == "Carrot Bag 2kg"

    def test_manager_can_patch_price(self, manager_client, product, fixed_variant):
        response = manager_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"sell_price": "1.49"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["sell_price"] == "1.49"

    def test_patch_price_below_existing_cost_rejected(self, manager_client, product, fixed_variant):
        response = manager_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"sell_price": "0.50"},
            format="json",
        )
        assert response.status_code == 400

    def test_patch_switch_mode_without_uom_rejected(self, manager_client, product, fixed_variant):
        response = manager_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"pricing_mode": "weight_based"},
            format="json",
        )
        assert response.status_code == 400

    def test_patch_switch_mode_with_uom_succeeds(self, manager_client, product, fixed_variant):
        response = manager_client.patch(
            reverse("variant-detail", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"pricing_mode": "weight_based", "unit_of_measure": "kg"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["pricing_mode"] == "weight_based"
        assert response.data["data"]["line_total_example"] == f"£{fixed_variant.sell_price:.2f} per kg"

    def test_variant_scoped_to_product(self, cashier_client, dept, fixed_variant):
        other_product = create_product(department=dept, name="Other Product")
        response = cashier_client.get(
            reverse("variant-detail", kwargs={"pk": other_product.pk, "variant_pk": fixed_variant.pk})
        )
        assert response.status_code == 404


# ── Allergen replace API ──────────────────────────────────────────────────────

class TestVariantAllergenAPI:
    def test_manager_can_set_allergens(self, manager_client, product, fixed_variant, allergen_gluten, allergen_nuts):
        response = manager_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": [
                {"allergen_id": allergen_gluten.id, "may_contain": False},
                {"allergen_id": allergen_nuts.id, "may_contain": True},
            ]},
            format="json",
        )
        assert response.status_code == 200
        allergen_names = [a["allergen"]["name"] for a in response.data["data"]["allergens"]]
        assert "Gluten" in allergen_names
        assert "Tree Nuts" in allergen_names

    def test_cashier_cannot_set_allergens(self, cashier_client, product, fixed_variant, allergen_gluten):
        response = cashier_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": [{"allergen_id": allergen_gluten.id}]},
            format="json",
        )
        assert response.status_code == 403

    def test_empty_list_clears_allergens(self, manager_client, product, fixed_variant, allergen_gluten):
        manager_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": [{"allergen_id": allergen_gluten.id}]},
            format="json",
        )
        response = manager_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": []},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["allergens"] == []

    def test_unknown_allergen_id_returns_404(self, manager_client, product, fixed_variant):
        response = manager_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": [{"allergen_id": 99999}]},
            format="json",
        )
        assert response.status_code == 404

    def test_may_contain_flag_persisted(self, manager_client, product, fixed_variant, allergen_nuts):
        manager_client.put(
            reverse("variant-allergens", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"allergens": [{"allergen_id": allergen_nuts.id, "may_contain": True}]},
            format="json",
        )
        link = fixed_variant.allergen_links.get()
        assert link.may_contain is True


# ── Line-total API ────────────────────────────────────────────────────────────

class TestLineTotalAPI:
    def test_fixed_with_quantity(self, cashier_client, product, fixed_variant):
        response = cashier_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"quantity": 3},
            format="json",
        )
        assert response.status_code == 200
        data = response.data["data"]
        assert data["pricing_mode"] == "fixed"
        assert data["quantity"] == 3
        assert data["line_total"] == round(float(fixed_variant.sell_price) * 3, 2)

    def test_weight_based_with_weight_kg(self, cashier_client, product, weight_variant):
        response = cashier_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": weight_variant.pk}),
            {"weight_kg": 0.75},
            format="json",
        )
        assert response.status_code == 200
        data = response.data["data"]
        assert data["pricing_mode"] == "weight_based"
        assert data["weight_kg"] == 0.75
        assert data["line_total"] == round(float(weight_variant.sell_price) * 0.75, 2)

    def test_weight_variant_missing_weight_returns_400(self, cashier_client, product, weight_variant):
        response = cashier_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": weight_variant.pk}),
            {"quantity": 1},
            format="json",
        )
        assert response.status_code == 400
        assert "weight_kg" in str(response.data["error"]["errors"])

    def test_fixed_defaults_quantity_to_1(self, cashier_client, product, fixed_variant):
        response = cashier_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["quantity"] == 1
        assert response.data["data"]["line_total"] == float(fixed_variant.sell_price)

    def test_unauthenticated_denied(self, anon_client, product, fixed_variant):
        response = anon_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": fixed_variant.pk}),
            {"quantity": 1},
            format="json",
        )
        assert response.status_code == 401

    def test_zero_weight_rejected(self, cashier_client, product, weight_variant):
        response = cashier_client.post(
            reverse("variant-line-total", kwargs={"pk": product.pk, "variant_pk": weight_variant.pk}),
            {"weight_kg": 0.0},
            format="json",
        )
        assert response.status_code == 400


# ── Barcode lookup API ────────────────────────────────────────────────────────

class TestBarcodeLookupAPI:
    def test_finds_active_variant(self, cashier_client, fixed_variant):
        response = cashier_client.get(reverse("barcode-lookup") + f"?barcode={fixed_variant.barcode}")
        assert response.status_code == 200
        assert response.data["data"]["sku"] == fixed_variant.sku

    def test_unknown_barcode_returns_404(self, cashier_client):
        response = cashier_client.get(reverse("barcode-lookup") + "?barcode=0000000000000")
        assert response.status_code == 404

    def test_missing_barcode_param_returns_400(self, cashier_client):
        response = cashier_client.get(reverse("barcode-lookup"))
        assert response.status_code == 400

    def test_inactive_variant_returns_404(self, cashier_client, fixed_variant):
        fixed_variant.is_active = False
        fixed_variant.save()
        response = cashier_client.get(reverse("barcode-lookup") + f"?barcode={fixed_variant.barcode}")
        assert response.status_code == 404

    def test_unauthenticated_denied(self, anon_client, fixed_variant):
        response = anon_client.get(reverse("barcode-lookup") + f"?barcode={fixed_variant.barcode}")
        assert response.status_code == 401

    def test_response_includes_pricing_mode(self, cashier_client, weight_variant):
        response = cashier_client.get(reverse("barcode-lookup") + f"?barcode={weight_variant.barcode}")
        assert response.status_code == 200
        assert response.data["data"]["pricing_mode"] == "weight_based"

    def test_response_includes_allergens(self, cashier_client, fixed_variant, allergen_gluten):
        set_variant_allergens(fixed_variant, [{"allergen_id": allergen_gluten.id, "may_contain": False}])
        response = cashier_client.get(reverse("barcode-lookup") + f"?barcode={fixed_variant.barcode}")
        assert response.status_code == 200
        assert len(response.data["data"]["allergens"]) == 1