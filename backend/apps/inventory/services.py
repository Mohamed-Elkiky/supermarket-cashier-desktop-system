import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    Allergen,
    InventoryLedger,
    LedgerLocation,
    Product,
    ProductVariant,
    ProductVariantAllergen,
)

logger = logging.getLogger("apps.inventory")


# ── Products ──────────────────────────────────────────────────────────────────

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
    logger.info("Set %d allergen link(s) on variant id=%s", len(links), variant.id)
    return links


def get_variant_by_barcode(barcode: str) -> ProductVariant:
    return ProductVariant.objects.select_related(
        "product__department"
    ).prefetch_related(
        "allergen_links__allergen"
    ).get(barcode=barcode, is_active=True)


def calculate_line_total(
    variant: ProductVariant, weight_kg: float = None, quantity: int = 1
) -> dict:
    if variant.pricing_mode == "weight_based":
        if not weight_kg:
            raise ValueError("weight_kg is required for weight-based products.")
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


# ── Ledger ────────────────────────────────────────────────────────────────────

def record_movement(
    *,
    variant: ProductVariant,
    department,
    movement_type: str,
    quantity: Decimal,
    performed_by=None,
    location: LedgerLocation = None,
    weight_kg: Decimal = None,
    batch_ref: str = "",
    best_before_date=None,
    use_by_date=None,
    order_id: int = None,
    return_id: int = None,
    reason: str = "",
) -> InventoryLedger:
    """
    Single write path for all stock movements.
    Raises ValueError for any business rule violation — nothing is written.
    """
    quantity = Decimal(str(quantity))
    _validate_movement(movement_type, quantity, reason, variant, weight_kg)

    with transaction.atomic():
        entry = InventoryLedger(
            variant=variant,
            department=department,
            location=location,
            movement_type=movement_type,
            quantity=quantity,
            weight_kg=Decimal(str(weight_kg)) if weight_kg is not None else None,
            batch_ref=batch_ref or "",
            best_before_date=best_before_date,
            use_by_date=use_by_date,
            order_id=order_id,
            return_id=return_id,
            performed_by=performed_by,
            reason=reason or "",
        )
        entry.save()

    logger.info(
        "Ledger entry recorded: type=%s variant=%s qty=%s dept=%s by=%s",
        movement_type,
        variant.sku,
        quantity,
        department.name,
        getattr(performed_by, "id", None),
    )
    return entry


def _validate_movement(
    movement_type: str,
    quantity: Decimal,
    reason: str,
    variant: ProductVariant,
    weight_kg,
) -> None:
    valid_types = {c[0] for c in InventoryLedger.MOVEMENT_CHOICES}
    if movement_type not in valid_types:
        raise ValueError(f"Unknown movement_type '{movement_type}'.")

    if movement_type in InventoryLedger.OUTBOUND_TYPES and quantity >= 0:
        raise ValueError(
            f"Outbound movement '{movement_type}' requires a negative quantity. Got {quantity}."
        )
    if movement_type in InventoryLedger.INBOUND_TYPES and quantity <= 0:
        raise ValueError(
            f"Inbound movement '{movement_type}' requires a positive quantity. Got {quantity}."
        )
    if movement_type == "adjustment" and not (reason or "").strip():
        raise ValueError("Adjustment entries require a non-empty reason.")

    if variant.pricing_mode == "weight_based" and weight_kg is None:
        raise ValueError(f"Variant '{variant.sku}' is weight-based; weight_kg is required.")

    if weight_kg is not None and Decimal(str(weight_kg)) <= 0:
        raise ValueError("weight_kg must be greater than zero.")


def get_stock_level(variant_id: int, department_id: int = None) -> dict:
    """
    Derive current stock from the ledger sum.
    Scoped to a department when department_id is provided, otherwise store-wide.
    """
    qs = InventoryLedger.objects.filter(variant_id=variant_id)
    if department_id is not None:
        qs = qs.filter(department_id=department_id)

    total = qs.aggregate(total=Sum("quantity"))["total"] or Decimal("0")

    try:
        variant = ProductVariant.objects.select_related("product__department").get(pk=variant_id)
    except ProductVariant.DoesNotExist:
        raise ValueError(f"Variant {variant_id} not found.")

    return {
        "variant_id": variant_id,
        "sku": variant.sku,
        "name": variant.name,
        "department_id": department_id,
        "stock_quantity": float(total),
        "unit_of_measure": variant.unit_of_measure,
        "low_stock_threshold": variant.low_stock_threshold,
        "is_low_stock": float(total) <= variant.low_stock_threshold,
    }


def get_stock_levels_bulk(variant_ids: list, department_id: int = None) -> list:
    """
    Aggregate stock levels for a list of variant IDs in a single query.
    Variants with no ledger entries are returned with stock_quantity 0.0.
    """
    qs = InventoryLedger.objects.filter(variant_id__in=variant_ids)
    if department_id is not None:
        qs = qs.filter(department_id=department_id)

    totals = {
        row["variant_id"]: row["total"]
        for row in qs.values("variant_id").annotate(total=Sum("quantity"))
    }

    results = []
    for v in ProductVariant.objects.filter(pk__in=variant_ids).select_related("product"):
        total = float(totals.get(v.id, Decimal("0")))
        results.append({
            "variant_id": v.id,
            "sku": v.sku,
            "name": v.name,
            "department_id": department_id,
            "stock_quantity": total,
            "unit_of_measure": v.unit_of_measure,
            "low_stock_threshold": v.low_stock_threshold,
            "is_low_stock": total <= v.low_stock_threshold,
        })
    return results


def get_expiry_alerts(department_id: int, days_ahead: int = None) -> list:
    """
    Return batches approaching or past their best_before / use_by date.
    Aggregates by (variant, batch_ref) — only batches with net stock > 0 appear.
    days_ahead overrides the per-variant expiry_alert_days when provided.
    """
    today = timezone.now().date()

    qs = (
        InventoryLedger.objects
        .filter(department_id=department_id)
        .exclude(best_before_date=None, use_by_date=None)
        .values(
            "variant_id",
            "variant__sku",
            "variant__name",
            "variant__expiry_alert_days",
            "batch_ref",
            "best_before_date",
            "use_by_date",
        )
        .annotate(net_quantity=Sum("quantity"))
        .filter(net_quantity__gt=0)
        .order_by("use_by_date", "best_before_date")
    )

    alerts = []
    for row in qs:
        alert_window = days_ahead if days_ahead is not None else row["variant__expiry_alert_days"]
        bb = row["best_before_date"]
        ub = row["use_by_date"]
        earliest = min(d for d in (bb, ub) if d is not None)
        days_remaining = (earliest - today).days

        if days_remaining > alert_window:
            continue

        alerts.append({
            "variant_id": row["variant_id"],
            "sku": row["variant__sku"],
            "name": row["variant__name"],
            "batch_ref": row["batch_ref"] or None,
            "best_before_date": bb.isoformat() if bb else None,
            "use_by_date": ub.isoformat() if ub else None,
            "days_remaining": days_remaining,
            "net_quantity": float(row["net_quantity"]),
            "is_expired": days_remaining < 0,
        })

    return alerts