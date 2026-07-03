import logging
from datetime import datetime, time as dt_time
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .models import ClockEvent, Rota, Staff

logger = logging.getLogger("apps.staff")


# ── Staff CRUD ────────────────────────────────────────────────────────────────

@transaction.atomic
def create_staff(
    *, first_name, last_name, email, phone="", role="cashier", department=None,
    commission_rate=Decimal("0"), hourly_wage=Decimal("0"), hired_at=None,
) -> Staff:
    staff = Staff(
        first_name=first_name, last_name=last_name, email=email, phone=phone,
        role=role, department=department, commission_rate=commission_rate,
        hourly_wage=hourly_wage, hired_at=hired_at,
    )
    staff.full_clean()
    staff.save()
    logger.info("Created staff id=%s (%s)", staff.id, staff.email)
    return staff


@transaction.atomic
def update_staff(staff: Staff, validated_data: dict) -> Staff:
    for attr, value in validated_data.items():
        setattr(staff, attr, value)
    staff.full_clean()
    staff.save()
    logger.info("Updated staff id=%s", staff.id)
    return staff


# ── Clock events ──────────────────────────────────────────────────────────────

def get_current_clock_status(staff: Staff) -> str:
    """'clocked_in' or 'clocked_out', based on the most recent ClockEvent."""
    last_event = staff.clock_events.order_by("-event_at", "-id").first()
    if last_event is None or last_event.event_type == ClockEvent.EventType.CLOCK_OUT:
        return "clocked_out"
    return "clocked_in"


def clock_in(*, staff: Staff, was_offline: bool = False) -> ClockEvent:
    if get_current_clock_status(staff) == "clocked_in":
        raise ValueError(f"{staff.first_name} {staff.last_name} is already clocked in.")
    event = ClockEvent.objects.create(
        staff=staff, event_type=ClockEvent.EventType.CLOCK_IN, was_offline=was_offline,
    )
    logger.info("Staff #%s clocked in (offline=%s)", staff.id, was_offline)
    return event


def clock_out(*, staff: Staff, was_offline: bool = False) -> ClockEvent:
    if get_current_clock_status(staff) == "clocked_out":
        raise ValueError(f"{staff.first_name} {staff.last_name} is not currently clocked in.")
    event = ClockEvent.objects.create(
        staff=staff, event_type=ClockEvent.EventType.CLOCK_OUT, was_offline=was_offline,
    )
    logger.info("Staff #%s clocked out (offline=%s)", staff.id, was_offline)
    return event


def calculate_hours_worked(*, staff: Staff, date_from, date_to) -> Decimal:
    """
    Pairs clock_in/clock_out events chronologically within [date_from, date_to]
    and sums the worked duration in hours.

    An unclosed clock_in at the end of the range (no matching clock_out
    before date_to) is CAPPED at the end of date_to rather than excluded —
    a shift still in progress when payroll is run counts for the hours
    worked so far, instead of silently vanishing from the report.
    """
    events = list(
        staff.clock_events
        .filter(event_at__date__gte=date_from, event_at__date__lte=date_to)
        .order_by("event_at", "id")
    )

    range_end = timezone.make_aware(datetime.combine(date_to, dt_time.max))

    total_seconds = 0
    open_clock_in = None
    for event in events:
        if event.event_type == ClockEvent.EventType.CLOCK_IN:
            open_clock_in = event.event_at
        elif event.event_type == ClockEvent.EventType.CLOCK_OUT and open_clock_in is not None:
            total_seconds += (event.event_at - open_clock_in).total_seconds()
            open_clock_in = None

    if open_clock_in is not None:
        total_seconds += (range_end - open_clock_in).total_seconds()

    hours = Decimal(total_seconds) / Decimal(3600)
    return hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ── Rota CRUD ─────────────────────────────────────────────────────────────────

def _validate_week_commencing(week_commencing):
    if week_commencing.weekday() != 0:  # Monday == 0
        raise ValueError("week_commencing must be a Monday.")


@transaction.atomic
def create_rota_entry(
    *, staff, week_commencing, shift_date, shift_start, shift_end,
    department=None, notes="", created_by=None,
) -> Rota:
    _validate_week_commencing(week_commencing)
    rota = Rota(
        staff=staff, department=department, week_commencing=week_commencing,
        shift_date=shift_date, shift_start=shift_start, shift_end=shift_end,
        notes=notes, created_by=created_by,
    )
    rota.full_clean()
    rota.save()
    logger.info("Created rota entry id=%s for staff #%s on %s", rota.id, staff.id, shift_date)
    return rota


@transaction.atomic
def update_rota_entry(rota: Rota, validated_data: dict) -> Rota:
    if "week_commencing" in validated_data:
        _validate_week_commencing(validated_data["week_commencing"])
    for attr, value in validated_data.items():
        setattr(rota, attr, value)
    rota.full_clean()
    rota.save()
    logger.info("Updated rota entry id=%s", rota.id)
    return rota


def delete_rota_entry(rota: Rota) -> None:
    rota_id = rota.id
    rota.delete()
    logger.info("Deleted rota entry id=%s", rota_id)


def get_rota_for_week(*, week_commencing, department=None) -> list:
    qs = Rota.objects.filter(week_commencing=week_commencing).select_related("staff", "department")
    if department is not None:
        qs = qs.filter(department=department)
    return list(qs)


# ── Commission / payroll ──────────────────────────────────────────────────────

def calculate_commission(*, staff: Staff, date_from, date_to) -> int:
    """Sums staff.commission_rate * order.total_pence over paid orders in range. Returns pence."""
    from apps.pos.models import Order

    orders = Order.objects.filter(
        cashier=staff, status="paid",
        paid_at__date__gte=date_from, paid_at__date__lte=date_to,
    )
    total_pence = 0
    for order in orders:
        commission = Decimal(order.total_pence) * staff.commission_rate
        total_pence += int(commission.to_integral_value(rounding=ROUND_HALF_UP))
    return total_pence


def build_payroll_export(*, date_from, date_to, department=None) -> list:
    """
    Flat, structured payroll export — no server-side file generation (the
    formatted Xero/QuickBooks/Sage export is a later sprint task). Exposes
    the underlying numbers per active staff member.
    """
    staff_qs = Staff.objects.filter(is_active=True)
    if department is not None:
        staff_qs = staff_qs.filter(department=department)

    rows = []
    for staff in staff_qs:
        hours = calculate_hours_worked(staff=staff, date_from=date_from, date_to=date_to)
        wages_pence = int((hours * staff.hourly_wage * 100).to_integral_value(rounding=ROUND_HALF_UP))
        commission_pence = calculate_commission(staff=staff, date_from=date_from, date_to=date_to)
        rows.append({
            "staff_id": staff.id,
            "staff_name": f"{staff.first_name} {staff.last_name}".strip(),
            "hours_worked": float(hours),
            "hourly_wage": float(staff.hourly_wage),
            "wages_pence": wages_pence,
            "commission_pence": commission_pence,
            "total_pence": wages_pence + commission_pence,
        })
    return rows
