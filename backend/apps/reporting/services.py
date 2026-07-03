import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate

from apps.inventory.models import InventoryLedger
from apps.pos.models import Order, OrderItem

logger = logging.getLogger("apps.reporting")


def _line_cost_pence(item: OrderItem) -> int:
    """
    Cost basis for a sold OrderItem line, using the variant's CURRENT
    cost_price — OrderItem has no historical cost snapshot (only a sell-price
    snapshot), so margin reporting necessarily uses today's cost, same
    tradeoff every other "keep it simple, no summary tables" report in this
    app makes. Mirrors the pricing_mode branching used by
    apps.inventory.services.calculate_line_total() (weight_kg for
    weight_based variants, quantity otherwise) but applied to cost_price
    instead of sell_price.
    """
    variant = item.variant
    if variant.pricing_mode == "weight_based" and item.weight_kg is not None:
        amount = item.weight_kg
    else:
        amount = Decimal(item.quantity)
    return int((variant.cost_price * amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def _line_units(item: OrderItem) -> Decimal:
    """Units sold for a line — weight in kg for weight-based variants, quantity otherwise."""
    if item.variant.pricing_mode == "weight_based" and item.weight_kg is not None:
        return item.weight_kg
    return Decimal(item.quantity)


# ── Sales dashboard ────────────────────────────────────────────────────────────

def get_sales_dashboard(*, date_from, date_to, department=None) -> dict:
    orders = Order.objects.filter(
        status="paid", paid_at__date__gte=date_from, paid_at__date__lte=date_to,
    )

    if department is not None:
        # Filtering through items__variant__product__department directly on
        # `orders` would fan the join out (one row per matching item) and
        # double-count total_pence in the aggregates below. Resolve the
        # matching order IDs first, then re-filter the unjoined queryset.
        matching_ids = list(
            orders.filter(items__variant__product__department=department)
            .values_list("id", flat=True).distinct()
        )
        orders = orders.filter(id__in=matching_ids)

    totals = orders.aggregate(total_revenue_pence=Sum("total_pence"), order_count=Count("id"))
    total_revenue_pence = totals["total_revenue_pence"] or 0
    order_count = totals["order_count"] or 0
    average_basket_pence = round(total_revenue_pence / order_count) if order_count else 0

    revenue_by_day = (
        orders.annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(revenue_pence=Sum("total_pence"), order_count=Count("id"))
        .order_by("day")
    )
    revenue_by_payment_method = (
        orders.values("payment_method")
        .annotate(revenue_pence=Sum("total_pence"), order_count=Count("id"))
        .order_by("-revenue_pence")
    )

    return {
        "total_revenue_pence": total_revenue_pence,
        "order_count": order_count,
        "average_basket_pence": average_basket_pence,
        "revenue_by_day": [
            {"date": row["day"].isoformat(), "revenue_pence": row["revenue_pence"], "order_count": row["order_count"]}
            for row in revenue_by_day
        ],
        "revenue_by_payment_method": [
            {
                "payment_method": row["payment_method"],
                "revenue_pence": row["revenue_pence"],
                "order_count": row["order_count"],
            }
            for row in revenue_by_payment_method
        ],
    }


# ── Department performance ────────────────────────────────────────────────────

def get_department_performance(*, date_from, date_to) -> list:
    items = (
        OrderItem.objects
        .filter(
            order__status="paid",
            order__paid_at__date__gte=date_from,
            order__paid_at__date__lte=date_to,
        )
        .select_related("variant__product__department", "order")
    )

    by_department = {}
    for item in items:
        dept = item.variant.product.department
        entry = by_department.setdefault(dept.id, {
            "department_id": dept.id,
            "department_name": dept.name,
            "revenue_pence": 0,
            "cost_pence": 0,
            "order_ids": set(),
        })
        entry["revenue_pence"] += item.line_total_pence
        entry["cost_pence"] += _line_cost_pence(item)
        entry["order_ids"].add(item.order_id)

    rows = [
        {
            "department_id": entry["department_id"],
            "department_name": entry["department_name"],
            "revenue_pence": entry["revenue_pence"],
            "margin_pence": entry["revenue_pence"] - entry["cost_pence"],
            "transaction_count": len(entry["order_ids"]),
        }
        for entry in by_department.values()
    ]
    rows.sort(key=lambda r: r["revenue_pence"], reverse=True)
    return rows


# ── Best sellers ───────────────────────────────────────────────────────────────

def get_best_sellers(*, date_from, date_to, department=None, metric="units", limit=20) -> list:
    if metric not in ("units", "margin"):
        raise ValueError("metric must be 'units' or 'margin'.")

    items = (
        OrderItem.objects
        .filter(
            order__status="paid",
            order__paid_at__date__gte=date_from,
            order__paid_at__date__lte=date_to,
        )
        .select_related("variant__product__department")
    )
    if department is not None:
        items = items.filter(variant__product__department=department)

    by_variant = {}
    for item in items:
        variant = item.variant
        entry = by_variant.setdefault(variant.id, {
            "variant_id": variant.id,
            "sku": variant.sku,
            "name": variant.name,
            "units_sold": Decimal("0"),
            "revenue_pence": 0,
            "cost_pence": 0,
        })
        entry["units_sold"] += _line_units(item)
        entry["revenue_pence"] += item.line_total_pence
        entry["cost_pence"] += _line_cost_pence(item)

    rows = [
        {
            "variant_id": entry["variant_id"],
            "sku": entry["sku"],
            "name": entry["name"],
            "units_sold": float(entry["units_sold"]),
            "revenue_pence": entry["revenue_pence"],
            "margin_pence": entry["revenue_pence"] - entry["cost_pence"],
        }
        for entry in by_variant.values()
    ]

    sort_key = "margin_pence" if metric == "margin" else "units_sold"
    rows.sort(key=lambda r: r[sort_key], reverse=True)
    return rows[:limit]


# ── Waste / markdown cost ─────────────────────────────────────────────────────

def get_waste_cost(*, date_from, date_to, department=None) -> dict:
    # Scoped to waste/damage specifically — InventoryLedger.OUTBOUND_TYPES
    # also includes 'sale' and 'transfer_out', which aren't waste. Both
    # values here are drawn from InventoryLedger.MOVEMENT_CHOICES.
    entries = (
        InventoryLedger.objects
        .filter(
            movement_type__in=["waste", "markdown"],
            recorded_at__date__gte=date_from,
            recorded_at__date__lte=date_to,
        )
        .select_related("variant", "department")
    )
    if department is not None:
        entries = entries.filter(department=department)

    by_department = {}
    by_variant = {}
    grand_total_pence = 0

    for entry in entries:
        cost_pence = int(
            (entry.variant.cost_price * abs(entry.quantity) * 100).to_integral_value(rounding=ROUND_HALF_UP)
        )
        grand_total_pence += cost_pence

        dept_entry = by_department.setdefault(entry.department_id, {
            "department_id": entry.department_id,
            "department_name": entry.department.name,
            "cost_pence": 0,
        })
        dept_entry["cost_pence"] += cost_pence

        variant_entry = by_variant.setdefault(entry.variant_id, {
            "variant_id": entry.variant_id,
            "sku": entry.variant.sku,
            "name": entry.variant.name,
            "cost_pence": 0,
        })
        variant_entry["cost_pence"] += cost_pence

    return {
        "grand_total_pence": grand_total_pence,
        "by_department": sorted(by_department.values(), key=lambda r: r["cost_pence"], reverse=True),
        "by_variant": sorted(by_variant.values(), key=lambda r: r["cost_pence"], reverse=True),
    }


# ── Staff performance ──────────────────────────────────────────────────────────

def get_staff_performance(*, date_from, date_to, staff=None) -> list:
    from apps.staff.models import Staff
    from apps.staff.services import calculate_commission

    if staff is not None:
        staff_qs = Staff.objects.filter(pk=staff.pk)
    else:
        staff_qs = Staff.objects.filter(is_active=True)

    rows = []
    for member in staff_qs:
        totals = Order.objects.filter(
            cashier=member, status="paid",
            paid_at__date__gte=date_from, paid_at__date__lte=date_to,
        ).aggregate(total_sales_pence=Sum("total_pence"), transaction_count=Count("id"))

        total_sales_pence = totals["total_sales_pence"] or 0
        transaction_count = totals["transaction_count"] or 0
        average_basket_pence = round(total_sales_pence / transaction_count) if transaction_count else 0
        # Reuses apps.staff.services.calculate_commission — do not
        # reimplement the commission formula here.
        commission_pence = calculate_commission(staff=member, date_from=date_from, date_to=date_to)

        rows.append({
            "staff_id": member.id,
            "staff_name": f"{member.first_name} {member.last_name}".strip(),
            "total_sales_pence": total_sales_pence,
            "transaction_count": transaction_count,
            "average_basket_pence": average_basket_pence,
            "commission_pence": commission_pence,
        })

    rows.sort(key=lambda r: r["total_sales_pence"], reverse=True)
    return rows
