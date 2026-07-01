import logging
from decimal import Decimal

from django.db import connection, transaction
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
def get_low_stock_variants(department_id: int) -> list:
    """
    Return all active variants in a department where current ledger-derived
    stock is at or below the variant's low_stock_threshold.
    Only variants with track_expiry=False or track_expiry=True are included —
    threshold of 0 means alerts are disabled for that variant.
    """
    from django.db.models import Sum, OuterRef, Subquery

    # Aggregate stock per variant scoped to this department
    stock_qs = (
        InventoryLedger.objects
        .filter(department_id=department_id, variant_id=OuterRef("pk"))
        .values("variant_id")
        .annotate(total=Sum("quantity"))
        .values("total")
    )

    variants = (
        ProductVariant.objects
        .filter(
            product__department_id=department_id,
            is_active=True,
            low_stock_threshold__gt=0,  # threshold 0 means no alert
        )
        .select_related("product__department")
        .annotate(current_stock=Subquery(stock_qs))
    )

    alerts = []
    for v in variants:
        stock = float(v.current_stock or 0)
        if stock <= v.low_stock_threshold:
            alerts.append({
                "variant_id": v.id,
                "sku": v.sku,
                "name": v.name,
                "product_name": v.product.name,
                "department_id": department_id,
                "current_stock": stock,
                "low_stock_threshold": v.low_stock_threshold,
                "unit_of_measure": v.unit_of_measure,
                "units_below_threshold": v.low_stock_threshold - stock,
            })

    return sorted(alerts, key=lambda x: x["units_below_threshold"], reverse=True)


def get_variant_expiry_status(variant_id: int, department_id: int) -> dict:
    """
    Return expiry status for every batch of a variant in a department.
    Used by the barcode scan flow to block expired items before they
    reach the basket.

    A batch is considered:
      - 'ok'      : use_by/best_before is beyond the alert window
      - 'warning' : within the alert window but not yet expired
      - 'expired' : use_by or best_before date is in the past

    Only batches with net stock > 0 are returned.
    """
    today = timezone.now().date()

    try:
        variant = ProductVariant.objects.get(pk=variant_id, is_active=True)
    except ProductVariant.DoesNotExist:
        raise ValueError(f"Variant {variant_id} not found or inactive.")

    if not variant.track_expiry:
        return {
            "variant_id": variant_id,
            "sku": variant.sku,
            "name": variant.name,
            "track_expiry": False,
            "batches": [],
            "has_expired_stock": False,
            "has_warning_stock": False,
        }

    qs = (
        InventoryLedger.objects
        .filter(variant_id=variant_id, department_id=department_id)
        .exclude(best_before_date=None, use_by_date=None)
        .values("batch_ref", "best_before_date", "use_by_date")
        .annotate(net_quantity=Sum("quantity"))
        .filter(net_quantity__gt=0)
        .order_by("use_by_date", "best_before_date")
    )

    batches = []
    has_expired = False
    has_warning = False

    for row in qs:
        bb = row["best_before_date"]
        ub = row["use_by_date"]
        earliest = min(d for d in (bb, ub) if d is not None)
        days_remaining = (earliest - today).days

        if days_remaining < 0:
            status = "expired"
            has_expired = True
        elif days_remaining <= variant.expiry_alert_days:
            status = "warning"
            has_warning = True
        else:
            status = "ok"

        batches.append({
            "batch_ref": row["batch_ref"] or None,
            "best_before_date": bb.isoformat() if bb else None,
            "use_by_date": ub.isoformat() if ub else None,
            "days_remaining": days_remaining,
            "net_quantity": float(row["net_quantity"]),
            "status": status,
        })

    return {
        "variant_id": variant_id,
        "sku": variant.sku,
        "name": variant.name,
        "track_expiry": True,
        "batches": batches,
        "has_expired_stock": has_expired,
        "has_warning_stock": has_warning,
    }


def check_basket_for_expired(lines: list) -> list:
    """
    Validate a basket before checkout. Blocks a line only if the variant
    has NO non-expired stock available. If there is at least one valid
    (non-expired) batch with stock, the line is allowed through.

    lines: [{"variant_id": int, "department_id": int, "batch_ref": str|None}, ...]
    """
    today = timezone.now().date()
    blocked = []

    for line in lines:
        variant_id    = line.get("variant_id")
        department_id = line.get("department_id")
        batch_ref     = line.get("batch_ref") or ""

        try:
            variant = ProductVariant.objects.get(pk=variant_id, is_active=True)
        except ProductVariant.DoesNotExist:
            blocked.append({
                "variant_id": variant_id,
                "batch_ref": batch_ref or None,
                "reason": "Variant not found or inactive.",
                "status": "not_found",
            })
            continue

        if not variant.track_expiry:
            continue

        # If a specific batch was requested, check only that batch
        if batch_ref:
            qs = (
                InventoryLedger.objects
                .filter(variant_id=variant_id, department_id=department_id, batch_ref=batch_ref)
                .exclude(best_before_date=None, use_by_date=None)
                .values("batch_ref", "best_before_date", "use_by_date")
                .annotate(net_quantity=Sum("quantity"))
                .filter(net_quantity__gt=0)
            )
            expired_batches = []
            for row in qs:
                earliest = min(d for d in (row["best_before_date"], row["use_by_date"]) if d is not None)
                if earliest < today:
                    expired_batches.append({
                        "batch_ref": row["batch_ref"],
                        "expired_date": earliest.isoformat(),
                        "net_quantity": float(row["net_quantity"]),
                    })
            if expired_batches:
                blocked.append({
                    "variant_id": variant_id,
                    "sku": variant.sku,
                    "name": variant.name,
                    "batch_ref": batch_ref,
                    "reason": "Batch is expired and cannot be sold.",
                    "status": "expired",
                    "expired_batches": expired_batches,
                })
            continue

        # No specific batch — check if ANY non-expired stock exists
        all_dated_batches = (
            InventoryLedger.objects
            .filter(variant_id=variant_id, department_id=department_id)
            .exclude(best_before_date=None, use_by_date=None)
            .values("batch_ref", "best_before_date", "use_by_date")
            .annotate(net_quantity=Sum("quantity"))
            .filter(net_quantity__gt=0)
        )

        if not all_dated_batches.exists():
            # No dated stock at all — block since track_expiry is on
            blocked.append({
                "variant_id": variant_id,
                "sku": variant.sku,
                "name": variant.name,
                "batch_ref": None,
                "reason": "No stock with expiry date found. Cannot sell expiry-tracked item without a dated batch.",
                "status": "no_dated_stock",
            })
            continue

        # Check if at least one batch is valid (not expired)
        has_valid_stock = False
        expired_batches = []
        for row in all_dated_batches:
            earliest = min(d for d in (row["best_before_date"], row["use_by_date"]) if d is not None)
            if earliest >= today:
                has_valid_stock = True
                break
            else:
                expired_batches.append({
                    "batch_ref": row["batch_ref"],
                    "expired_date": earliest.isoformat(),
                    "net_quantity": float(row["net_quantity"]),
                })

        if not has_valid_stock:
            blocked.append({
                "variant_id": variant_id,
                "sku": variant.sku,
                "name": variant.name,
                "batch_ref": None,
                "reason": "All available stock is expired and cannot be sold.",
                "status": "expired",
                "expired_batches": expired_batches,
            })

    return blocked


# ── Allergen audit ────────────────────────────────────────────────────────────

def _variant_ids_with_allergen_updates_since(since) -> set:
    """
    Derives which variants had their allergen profile changed on/after `since`
    from activity_log (written by ProductVariantAllergenView.put() via
    log_activity() for the 'variant.allergens.set' action) — avoids adding a
    new updated_at column to ProductVariantAllergen.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT entity_id FROM activity_log
            WHERE entity_type = %s AND action = %s AND occurred_at >= %s
            """,
            ["product_variants", "variant.allergens.set", since.isoformat()],
        )
        return {int(row[0]) for row in cursor.fetchall()}


def get_allergen_audit_export(*, department_id: int = None, updated_since=None) -> list:
    """
    Full allergen profile for every active variant: SKU, product name,
    department, and contains/may_contain/absent for each configured allergen.
    """
    qs = (
        ProductVariant.objects
        .filter(is_active=True)
        .select_related("product__department")
        .prefetch_related("allergen_links__allergen")
    )
    if department_id:
        qs = qs.filter(product__department_id=department_id)
    if updated_since is not None:
        variant_ids = _variant_ids_with_allergen_updates_since(updated_since)
        qs = qs.filter(pk__in=variant_ids)

    allergens = list(Allergen.objects.order_by("eu_code"))

    rows = []
    for variant in qs:
        links = {link.allergen_id: link.may_contain for link in variant.allergen_links.all()}
        row = {
            "sku": variant.sku,
            "product_name": variant.product.name,
            "department": variant.product.department.name,
        }
        for allergen in allergens:
            if allergen.id not in links:
                row[allergen.eu_code] = "absent"
            elif links[allergen.id]:
                row[allergen.eu_code] = "may_contain"
            else:
                row[allergen.eu_code] = "contains"
        rows.append(row)

    return rows