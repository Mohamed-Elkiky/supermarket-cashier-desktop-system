import logging
from django.db import transaction
from .models import Product, ProductVariant, ProductVariantAllergen, Supplier, Allergen

logger = logging.getLogger("apps.inventory")


@transaction.atomic
def create_product(
    *, department, supplier=None, name, description="",
    is_age_restricted=False, age_restriction_years=None,
) -> Product:
    product = Product.objects.create(
        department=department,
        supplier=supplier,
        name=name,
        description=description,
        is_age_restricted=is_age_restricted,
        age_restriction_years=age_restriction_years,
    )
    logger.info("Created product '%s' in department '%s'", name, department.name)
    return product


@transaction.atomic
def update_product(product: Product, validated_data: dict) -> Product:
    for attr, value in validated_data.items():
        setattr(product, attr, value)
    product.full_clean()
    product.save()
    logger.info("Updated product id=%s", product.id)
    return product


@transaction.atomic
def create_variant(
    *, product, sku, name, pricing_mode="fixed",
    sell_price, cost_price, barcode=None,
    unit_of_measure="unit", low_stock_threshold=0,
    track_expiry=False, expiry_alert_days=3,
) -> ProductVariant:
    variant = ProductVariant.objects.create(
        product=product,
        sku=sku,
        barcode=barcode,
        name=name,
        pricing_mode=pricing_mode,
        sell_price=sell_price,
        cost_price=cost_price,
        unit_of_measure=unit_of_measure,
        low_stock_threshold=low_stock_threshold,
        track_expiry=track_expiry,
        expiry_alert_days=expiry_alert_days,
    )
    logger.info(
        "Created variant '%s' (SKU=%s, mode=%s) for product '%s'",
        name, sku, pricing_mode, product.name,
    )
    return variant


@transaction.atomic
def update_variant(variant: ProductVariant, validated_data: dict) -> ProductVariant:
    for attr, value in validated_data.items():
        setattr(variant, attr, value)
    variant.full_clean()
    variant.save()
    logger.info("Updated variant id=%s (SKU=%s)", variant.id, variant.sku)
    return variant


@transaction.atomic
def set_variant_allergens(variant: ProductVariant, allergen_data: list) -> list:
    """
    Atomically replace all allergen links for a variant.

    allergen_data: [{"allergen_id": 1, "may_contain": False}, ...]

    Raises Allergen.DoesNotExist if any allergen_id is not found —
    the transaction rolls back so the variant is left unchanged.
    """
    variant.allergen_links.all().delete()
    links = []
    for item in allergen_data:
        allergen = Allergen.objects.get(pk=item["allergen_id"])
        link = ProductVariantAllergen.objects.create(
            variant=variant,
            allergen=allergen,
            may_contain=item.get("may_contain", False),
        )
        links.append(link)
    logger.info(
        "Set %d allergen link(s) on variant id=%s", len(links), variant.id
    )
    return links


def get_variant_by_barcode(barcode: str) -> ProductVariant:
    """
    Fetch an active variant by barcode. Used by the cashier barcode scanner.
    Raises ProductVariant.DoesNotExist if not found or inactive.
    """
    return ProductVariant.objects.select_related(
        "product__department"
    ).prefetch_related(
        "allergen_links__allergen"
    ).get(barcode=barcode, is_active=True)


def calculate_line_total(
    variant: ProductVariant, weight_kg: float = None, quantity: int = 1
) -> dict:
    """
    Return a structured line-total dict for the given variant.

    For weight_based variants weight_kg is required; quantity is ignored.
    For fixed variants quantity is used; weight_kg is ignored.
    """
    if variant.pricing_mode == "weight_based":
        if not weight_kg:
            raise ValueError(
                "weight_kg is required for weight-based products."
            )
        unit_price = float(variant.sell_price)
        total = round(unit_price * weight_kg, 2)
        return {
            "pricing_mode": "weight_based",
            "sku": variant.sku,
            "name": variant.name,
            "sell_price_per_kg": unit_price,
            "weight_kg": weight_kg,
            "line_total": total,
            "line_total_display": f"£{total:.2f}",
        }

    unit_price = float(variant.sell_price)
    total = round(unit_price * quantity, 2)
    return {
        "pricing_mode": "fixed",
        "sku": variant.sku,
        "name": variant.name,
        "sell_price": unit_price,
        "quantity": quantity,
        "line_total": total,
        "line_total_display": f"£{total:.2f}",
    }