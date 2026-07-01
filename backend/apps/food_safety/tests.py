from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.departments.services import create_department
from apps.staff.models import Staff

from .models import CleaningLog, TemperatureLog
from .services import (
    build_eho_export,
    get_missed_checks,
    record_cleaning_signoff,
    record_temperature_check,
)

User = get_user_model()


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept(db):
    return create_department(
        name="Chilled Foods",
        tax_rate=Decimal("0.0000"),
        stock_settings_data={
            "temperature_min_celsius": Decimal("1.00"),
            "temperature_max_celsius": Decimal("5.00"),
        },
    )


@pytest.fixture
def dept_no_thresholds(db):
    return create_department(name="Dry Goods", tax_rate=Decimal("0.0000"))


@pytest.fixture
def cashier_staff(dept):
    return Staff.objects.create(
        first_name="Casey", last_name="Cashier", email="casey@fs-test.com",
        role="cashier", department=dept,
    )


@pytest.fixture
def store_manager_staff(dept):
    return Staff.objects.create(
        first_name="Sam", last_name="Manager", email="sam.manager@fs-test.com",
        role="store_manager", department=dept,
    )


@pytest.fixture
def admin_staff(db):
    return Staff.objects.create(
        first_name="Ada", last_name="Admin", email="ada.admin@fs-test.com",
        role="admin",
    )


def _make_staff_user(role="cashier", suffix="", department=None):
    email = f"{role}{suffix}@fs-api-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    Staff.objects.create(
        user=user, first_name="Test", last_name=role.capitalize(),
        email=email, role=role, department=department,
    )
    return user


@pytest.fixture
def cashier_client(dept):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user("cashier", department=dept))
    return client


@pytest.fixture
def manager_client(dept):
    client = APIClient()
    client.force_authenticate(user=_make_staff_user("department_manager", suffix="2", department=dept))
    return client


@pytest.fixture
def anon_client(db):
    return APIClient()


# ── record_temperature_check ──────────────────────────────────────────────────

class TestRecordTemperatureCheck:
    def test_pass_within_thresholds(self, dept, cashier_staff):
        log = record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        assert log.result == TemperatureLog.Result.PASS
        assert log.corrective_action is None

    def test_fail_above_threshold_requires_corrective_action(self, dept, cashier_staff):
        with pytest.raises(ValueError, match="corrective_action is required"):
            record_temperature_check(
                unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("10.00"),
                performed_by=cashier_staff,
            )

    def test_fail_below_threshold(self, dept, cashier_staff):
        log = record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("-2.00"),
            performed_by=cashier_staff, corrective_action="Adjusted thermostat",
        )
        assert log.result == TemperatureLog.Result.FAIL

    def test_fail_with_corrective_action_recorded(self, dept, cashier_staff):
        log = record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("10.00"),
            performed_by=cashier_staff, corrective_action="Moved stock to backup fridge",
        )
        assert log.result == TemperatureLog.Result.FAIL
        assert log.corrective_action == "Moved stock to backup fridge"

    def test_no_thresholds_configured_raises(self, dept_no_thresholds, cashier_staff):
        with pytest.raises(ValueError, match="no temperature thresholds configured"):
            record_temperature_check(
                unit_name="Dry Shelf", department=dept_no_thresholds,
                temperature_celsius=Decimal("18.00"), performed_by=cashier_staff,
            )


# ── record_cleaning_signoff ───────────────────────────────────────────────────

class TestRecordCleaningSignoff:
    def test_completed_signoff(self, dept, cashier_staff):
        log = record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff,
        )
        assert log.result == "completed"
        assert log.alerted_manager is None

    def test_missed_resolves_store_manager(self, dept, cashier_staff, store_manager_staff):
        log = record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="missed", performed_by=cashier_staff,
        )
        assert log.alerted_manager_id == store_manager_staff.id

    def test_missed_falls_back_to_admin(self, dept_no_thresholds, admin_staff):
        # dept_no_thresholds has no store_manager assigned
        log = record_cleaning_signoff(
            area_name="Bakery Oven", department=dept_no_thresholds, scheduled_interval_hours=8,
            result="missed", performed_by=None,
        )
        assert log.alerted_manager_id == admin_staff.id

    def test_missed_without_any_manager_raises(self, dept_no_thresholds, cashier_staff):
        with pytest.raises(ValueError, match="No store_manager or admin"):
            record_cleaning_signoff(
                area_name="Bakery Oven", department=dept_no_thresholds, scheduled_interval_hours=8,
                result="missed", performed_by=cashier_staff,
            )

    def test_invalid_result_raises(self, dept, cashier_staff):
        with pytest.raises(ValueError, match="Invalid cleaning result"):
            record_cleaning_signoff(
                area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
                result="not_a_real_result", performed_by=cashier_staff,
            )


# ── Immutability ──────────────────────────────────────────────────────────────

class TestLogImmutability:
    def test_temperature_log_update_raises(self, dept, cashier_staff):
        log = record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        log.temperature_celsius = Decimal("4.00")
        with pytest.raises(ValueError, match="immutable"):
            log.save()

    def test_temperature_log_delete_raises(self, dept, cashier_staff):
        log = record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        with pytest.raises(ValueError, match="cannot be deleted"):
            log.delete()

    def test_cleaning_log_update_raises(self, dept, cashier_staff):
        log = record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff,
        )
        log.notes = "edited after the fact"
        with pytest.raises(ValueError, match="immutable"):
            log.save()

    def test_cleaning_log_delete_raises(self, dept, cashier_staff):
        log = record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff,
        )
        with pytest.raises(ValueError, match="cannot be deleted"):
            log.delete()


# ── get_missed_checks ─────────────────────────────────────────────────────────

class TestGetMissedChecks:
    def test_aggregates_missed_and_failed(self, dept, cashier_staff, store_manager_staff):
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )  # pass — excluded
        record_temperature_check(
            unit_name="Fridge 2", department=dept, temperature_celsius=Decimal("10.00"),
            performed_by=cashier_staff, corrective_action="Called engineer",
        )  # fail
        record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff,
        )  # completed — excluded
        record_cleaning_signoff(
            area_name="Bakery Oven", department=dept, scheduled_interval_hours=8,
            result="missed", performed_by=cashier_staff,
        )  # missed

        result = get_missed_checks()
        assert len(result["failed_temperature_checks"]) == 1
        assert result["failed_temperature_checks"][0]["unit_name"] == "Fridge 2"
        assert len(result["missed_cleanings"]) == 1
        assert result["missed_cleanings"][0]["area_name"] == "Bakery Oven"
        assert result["missed_cleanings"][0]["alerted_manager"] == "Sam Manager"

    def test_filters_by_department(self, dept, dept_no_thresholds, cashier_staff, admin_staff):
        record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="missed", performed_by=cashier_staff,
        )
        record_cleaning_signoff(
            area_name="Bakery Oven", department=dept_no_thresholds, scheduled_interval_hours=8,
            result="missed", performed_by=None,
        )
        result = get_missed_checks(department=dept)
        assert len(result["missed_cleanings"]) == 1
        assert result["missed_cleanings"][0]["area_name"] == "Deli Slicer"

    def test_filters_by_since(self, dept, cashier_staff):
        now = timezone.now()
        record_temperature_check(
            unit_name="Old Fail", department=dept, temperature_celsius=Decimal("10.00"),
            performed_by=cashier_staff, corrective_action="Fixed", checked_at=now - timedelta(days=5),
        )
        record_temperature_check(
            unit_name="Recent Fail", department=dept, temperature_celsius=Decimal("10.00"),
            performed_by=cashier_staff, corrective_action="Fixed", checked_at=now,
        )
        result = get_missed_checks(since=now - timedelta(days=1))
        units = {r["unit_name"] for r in result["failed_temperature_checks"]}
        assert units == {"Recent Fail"}


# ── build_eho_export ──────────────────────────────────────────────────────────

class TestBuildEhoExport:
    def test_shape_and_date_filtering(self, dept, cashier_staff):
        now = timezone.now()
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff, checked_at=now,
        )
        record_temperature_check(
            unit_name="Fridge Old", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff, checked_at=now - timedelta(days=10),
        )
        record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff, cleaned_at=now,
        )

        export = build_eho_export(date_from=now.date(), date_to=now.date())
        temp_units = {r["unit_name"] for r in export["temperature_logs"]}
        assert "Fridge 1" in temp_units
        assert "Fridge Old" not in temp_units

        assert len(export["cleaning_logs"]) == 1
        row = export["cleaning_logs"][0]
        assert row["area_name"] == "Deli Slicer"
        assert row["department"] == dept.name
        assert row["performed_by"] == "Casey Cashier"

    def test_department_filter(self, dept, dept_no_thresholds, cashier_staff):
        now = timezone.now()
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff, checked_at=now,
        )
        export = build_eho_export(date_from=now.date(), date_to=now.date(), department=dept_no_thresholds)
        assert export["temperature_logs"] == []


# ── Temperature log API ───────────────────────────────────────────────────────

class TestTemperatureLogAPI:
    def test_cashier_can_log_pass(self, cashier_client, dept):
        response = cashier_client.post(
            reverse("temperature-log-list-create"),
            {"unit_name": "Fridge 1", "department_id": dept.id, "temperature_celsius": "3.00"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["result"] == "pass"

    def test_fail_without_corrective_action_rejected(self, cashier_client, dept):
        response = cashier_client.post(
            reverse("temperature-log-list-create"),
            {"unit_name": "Fridge 1", "department_id": dept.id, "temperature_celsius": "20.00"},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["success"] is False

    def test_no_thresholds_configured_rejected(self, cashier_client, dept_no_thresholds):
        response = cashier_client.post(
            reverse("temperature-log-list-create"),
            {"unit_name": "Dry Shelf", "department_id": dept_no_thresholds.id, "temperature_celsius": "18.00"},
            format="json",
        )
        assert response.status_code == 400

    def test_cashier_can_list(self, cashier_client, dept, cashier_staff):
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        response = cashier_client.get(reverse("temperature-log-list-create"))
        assert response.status_code == 200
        assert len(response.data["data"]) == 1

    def test_filter_by_result(self, cashier_client, dept, cashier_staff):
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        record_temperature_check(
            unit_name="Fridge 2", department=dept, temperature_celsius=Decimal("10.00"),
            performed_by=cashier_staff, corrective_action="Fixed",
        )
        response = cashier_client.get(reverse("temperature-log-list-create"), {"result": "fail"})
        assert response.status_code == 200
        assert len(response.data["data"]) == 1
        assert response.data["data"][0]["unit_name"] == "Fridge 2"

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("temperature-log-list-create"))
        assert response.status_code == 401


# ── Cleaning log API ──────────────────────────────────────────────────────────

class TestCleaningLogAPI:
    def test_cashier_can_log_completed(self, cashier_client, dept):
        response = cashier_client.post(
            reverse("cleaning-log-list-create"),
            {"area_name": "Deli Slicer", "department_id": dept.id, "result": "completed"},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_missed_without_manager_returns_400(self, cashier_client, dept_no_thresholds):
        response = cashier_client.post(
            reverse("cleaning-log-list-create"),
            {"area_name": "Bakery Oven", "department_id": dept_no_thresholds.id, "result": "missed"},
            format="json",
        )
        assert response.status_code == 400
        assert response.data["success"] is False

    def test_missed_resolves_manager(self, cashier_client, dept, store_manager_staff):
        response = cashier_client.post(
            reverse("cleaning-log-list-create"),
            {"area_name": "Bakery Oven", "department_id": dept.id, "result": "missed"},
            format="json",
        )
        assert response.status_code == 201, response.data
        assert response.data["data"]["alerted_manager_name"] == "Sam Manager"

    def test_cashier_can_list(self, cashier_client, dept, cashier_staff):
        record_cleaning_signoff(
            area_name="Deli Slicer", department=dept, scheduled_interval_hours=4,
            result="completed", performed_by=cashier_staff,
        )
        response = cashier_client.get(reverse("cleaning-log-list-create"))
        assert response.status_code == 200
        assert len(response.data["data"]) == 1


# ── Missed checks API ─────────────────────────────────────────────────────────

class TestMissedChecksAPI:
    def test_cashier_forbidden(self, cashier_client):
        response = cashier_client.get(reverse("missed-checks"))
        assert response.status_code == 403

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("missed-checks"))
        assert response.status_code == 401

    def test_manager_can_view(self, manager_client, dept, cashier_staff, store_manager_staff):
        record_cleaning_signoff(
            area_name="Bakery Oven", department=dept, scheduled_interval_hours=8,
            result="missed", performed_by=cashier_staff,
        )
        response = manager_client.get(reverse("missed-checks"))
        assert response.status_code == 200
        assert len(response.data["data"]["missed_cleanings"]) == 1


# ── EHO export API ────────────────────────────────────────────────────────────

class TestEhoExportAPI:
    def test_cashier_forbidden(self, cashier_client):
        response = cashier_client.get(
            reverse("eho-export"), {"date_from": "2026-01-01", "date_to": "2026-01-31"}
        )
        assert response.status_code == 403

    def test_manager_can_export(self, manager_client, dept, cashier_staff):
        record_temperature_check(
            unit_name="Fridge 1", department=dept, temperature_celsius=Decimal("3.00"),
            performed_by=cashier_staff,
        )
        today = timezone.now().date().isoformat()
        response = manager_client.get(reverse("eho-export"), {"date_from": today, "date_to": today})
        assert response.status_code == 200
        assert "temperature_logs" in response.data["data"]
        assert "cleaning_logs" in response.data["data"]
        assert len(response.data["data"]["temperature_logs"]) == 1

    def test_missing_date_params_returns_400(self, manager_client):
        response = manager_client.get(reverse("eho-export"))
        assert response.status_code == 400

    def test_date_to_before_date_from_rejected(self, manager_client):
        response = manager_client.get(
            reverse("eho-export"), {"date_from": "2026-02-01", "date_to": "2026-01-01"}
        )
        assert response.status_code == 400
