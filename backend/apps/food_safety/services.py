import logging
from decimal import Decimal

from django.utils import timezone

from apps.staff.models import Staff

from .models import CleaningLog, TemperatureLog

logger = logging.getLogger("apps.food_safety")


# ── Temperature checks ────────────────────────────────────────────────────────

def _determine_temperature_result(temperature_celsius: Decimal, department) -> str:
    settings = getattr(department, "stock_settings", None)
    if (
        settings is None
        or settings.temperature_min_celsius is None
        or settings.temperature_max_celsius is None
    ):
        raise ValueError(
            f"Department '{department.name}' has no temperature thresholds configured "
            "(DepartmentStockSettings.temperature_min_celsius/temperature_max_celsius)."
        )
    if settings.temperature_min_celsius <= temperature_celsius <= settings.temperature_max_celsius:
        return TemperatureLog.Result.PASS
    return TemperatureLog.Result.FAIL


def record_temperature_check(
    *, unit_name, department, temperature_celsius, performed_by,
    checked_at=None, was_offline=False, corrective_action=None,
) -> TemperatureLog:
    """
    Determines pass/fail against the department's configured thresholds
    (DepartmentStockSettings). A 'fail' result requires corrective_action.
    """
    temperature_celsius = Decimal(str(temperature_celsius))
    result = _determine_temperature_result(temperature_celsius, department)

    if result == TemperatureLog.Result.FAIL and not corrective_action:
        raise ValueError("corrective_action is required when a temperature check fails.")

    log = TemperatureLog.objects.create(
        unit_name=unit_name,
        department=department,
        temperature_celsius=temperature_celsius,
        result=result,
        corrective_action=corrective_action,
        performed_by=performed_by,
        checked_at=checked_at or timezone.now(),
        was_offline=was_offline,
    )
    logger.info(
        "Temperature check '%s' in department '%s': %s (%.1f°C)",
        unit_name, department.name, result, float(temperature_celsius),
    )
    return log


# ── Cleaning sign-offs ────────────────────────────────────────────────────────

def _find_alert_manager(department):
    """
    Prefers a store_manager assigned to this department; falls back to any
    admin-role Staff (admins oversee the whole store, not a single department).
    """
    manager = Staff.objects.filter(
        department=department, role="store_manager", is_active=True
    ).first()
    if manager:
        return manager
    return Staff.objects.filter(role="admin", is_active=True).first()


def record_cleaning_signoff(
    *, area_name, department, scheduled_interval_hours, result,
    performed_by=None, notes="", cleaned_at=None, was_offline=False,
) -> CleaningLog:
    """
    Creates a CleaningLog. A 'missed' result requires an alerted_manager —
    resolved automatically from the department's store_manager, falling back
    to any admin. Raises ValueError if neither exists.
    """
    if result not in CleaningLog.Result.values:
        raise ValueError(f"Invalid cleaning result '{result}'.")

    alerted_manager = None
    if result == CleaningLog.Result.MISSED:
        alerted_manager = _find_alert_manager(department)
        if alerted_manager is None:
            raise ValueError(
                f"No store_manager or admin found to alert for department '{department.name}'."
            )

    log = CleaningLog.objects.create(
        area_name=area_name,
        department=department,
        scheduled_interval_hours=scheduled_interval_hours,
        result=result,
        notes=notes,
        performed_by=performed_by,
        alerted_manager=alerted_manager,
        cleaned_at=cleaned_at or timezone.now(),
        was_offline=was_offline,
    )
    logger.info(
        "Cleaning sign-off '%s' in department '%s': %s",
        area_name, department.name, result,
    )
    return log


# ── Dashboards / exports ──────────────────────────────────────────────────────

def get_missed_checks(department=None, since=None) -> dict:
    """Missed cleanings and failed temperature checks, for manager dashboards/alerts."""
    cleaning_qs = CleaningLog.objects.filter(
        result=CleaningLog.Result.MISSED
    ).select_related("department", "performed_by", "alerted_manager")
    temp_qs = TemperatureLog.objects.filter(
        result=TemperatureLog.Result.FAIL
    ).select_related("department", "performed_by")

    if department is not None:
        cleaning_qs = cleaning_qs.filter(department=department)
        temp_qs = temp_qs.filter(department=department)
    if since is not None:
        cleaning_qs = cleaning_qs.filter(cleaned_at__gte=since)
        temp_qs = temp_qs.filter(checked_at__gte=since)

    return {
        "missed_cleanings": [
            {
                "id": c.id,
                "area_name": c.area_name,
                "department": c.department.name,
                "cleaned_at": c.cleaned_at.isoformat(),
                "notes": c.notes,
                "alerted_manager": (
                    f"{c.alerted_manager.first_name} {c.alerted_manager.last_name}".strip()
                    if c.alerted_manager else None
                ),
            }
            for c in cleaning_qs
        ],
        "failed_temperature_checks": [
            {
                "id": t.id,
                "unit_name": t.unit_name,
                "department": t.department.name,
                "temperature_celsius": float(t.temperature_celsius),
                "checked_at": t.checked_at.isoformat(),
                "corrective_action": t.corrective_action,
                "performed_by": f"{t.performed_by.first_name} {t.performed_by.last_name}".strip(),
            }
            for t in temp_qs
        ],
    }


def build_eho_export(*, date_from, date_to, department=None) -> dict:
    """
    Flat, structured export for Environmental Health Officer inspection.
    No server-side file generation — the caller renders/downloads client-side.
    """
    temp_qs = TemperatureLog.objects.filter(
        checked_at__date__gte=date_from, checked_at__date__lte=date_to
    ).select_related("department", "performed_by")
    cleaning_qs = CleaningLog.objects.filter(
        cleaned_at__date__gte=date_from, cleaned_at__date__lte=date_to
    ).select_related("department", "performed_by", "alerted_manager")

    if department is not None:
        temp_qs = temp_qs.filter(department=department)
        cleaning_qs = cleaning_qs.filter(department=department)

    temperature_logs = [
        {
            "unit_name": t.unit_name,
            "department": t.department.name,
            "result": t.result,
            "reading_celsius": float(t.temperature_celsius),
            "performed_by": f"{t.performed_by.first_name} {t.performed_by.last_name}".strip(),
            "corrective_action": t.corrective_action,
            "checked_at": t.checked_at.isoformat(),
        }
        for t in temp_qs
    ]

    cleaning_logs = [
        {
            "area_name": c.area_name,
            "department": c.department.name,
            "result": c.result,
            "notes": c.notes,
            "performed_by": (
                f"{c.performed_by.first_name} {c.performed_by.last_name}".strip()
                if c.performed_by else None
            ),
            "alerted_manager": (
                f"{c.alerted_manager.first_name} {c.alerted_manager.last_name}".strip()
                if c.alerted_manager else None
            ),
            "cleaned_at": c.cleaned_at.isoformat(),
        }
        for c in cleaning_qs
    ]

    return {
        "temperature_logs": temperature_logs,
        "cleaning_logs": cleaning_logs,
    }
