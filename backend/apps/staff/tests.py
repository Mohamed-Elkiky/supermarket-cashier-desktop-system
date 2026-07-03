from datetime import date, datetime, time
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.departments.models import Department
from apps.pos.models import Order

from .models import ClockEvent, Rota, Staff
from .services import (
    build_payroll_export,
    calculate_commission,
    calculate_hours_worked,
    clock_in,
    clock_out,
    create_rota_entry,
    delete_rota_entry,
    get_current_clock_status,
    get_rota_for_week,
    update_rota_entry,
)

User = get_user_model()

MONDAY = date(2026, 6, 1)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept(db):
    return Department.objects.create(name="Staff Test Dept", slug="staff-test-dept", display_order=1)


@pytest.fixture
def staff_member(dept):
    return Staff.objects.create(
        first_name="Casey", last_name="Cashier", email="casey@staff-test.com",
        role="cashier", department=dept,
        commission_rate=Decimal("0.0100"), hourly_wage=Decimal("12.00"),
    )


@pytest.fixture
def other_cashier_staff(dept):
    return Staff.objects.create(
        first_name="Other", last_name="Cashier", email="other-cashier@staff-test.com",
        role="cashier", department=dept,
    )


def _make_staff_user(role="cashier", suffix="", department=None,
                     commission_rate=Decimal("0"), hourly_wage=Decimal("0")):
    email = f"{role}{suffix}@staff-api-test.com"
    user = User.objects.create_user(email=email, password="testpass123")
    staff = Staff.objects.create(
        user=user, first_name="Test", last_name=role.capitalize(), email=email, role=role,
        department=department, commission_rate=commission_rate, hourly_wage=hourly_wage,
    )
    return user, staff


@pytest.fixture
def cashier_client_and_staff(dept):
    user, staff = _make_staff_user("cashier", department=dept)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, staff


@pytest.fixture
def cashier_client(cashier_client_and_staff):
    return cashier_client_and_staff[0]


@pytest.fixture
def manager_client(db):
    user, _ = _make_staff_user("store_manager", suffix="2")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def dept_manager_client(db):
    user, _ = _make_staff_user("department_manager", suffix="3")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def anon_client(db):
    return APIClient()


def _make_paid_order(cashier, total_pence, paid_at):
    return Order.objects.create(cashier=cashier, status="paid", total_pence=total_pence, paid_at=paid_at)


def _aware(d, t):
    return timezone.make_aware(datetime.combine(d, t))


# ── Clock in/out (service) ────────────────────────────────────────────────────

class TestClockInOut:
    def test_clock_in_creates_event(self, staff_member):
        event = clock_in(staff=staff_member)
        assert event.event_type == "clock_in"
        assert get_current_clock_status(staff_member) == "clocked_in"

    def test_double_clock_in_rejected(self, staff_member):
        clock_in(staff=staff_member)
        with pytest.raises(ValueError, match="already clocked in"):
            clock_in(staff=staff_member)

    def test_clock_out_without_open_clock_in_rejected(self, staff_member):
        with pytest.raises(ValueError, match="not currently clocked in"):
            clock_out(staff=staff_member)

    def test_clock_out_after_clock_in_succeeds(self, staff_member):
        clock_in(staff=staff_member)
        event = clock_out(staff=staff_member)
        assert event.event_type == "clock_out"
        assert get_current_clock_status(staff_member) == "clocked_out"

    def test_status_defaults_to_clocked_out(self, staff_member):
        assert get_current_clock_status(staff_member) == "clocked_out"

    def test_clock_event_immutable(self, staff_member):
        event = clock_in(staff=staff_member)
        event.was_offline = True
        with pytest.raises(ValueError, match="immutable"):
            event.save()
        with pytest.raises(ValueError, match="cannot be deleted"):
            event.delete()


# ── calculate_hours_worked ─────────────────────────────────────────────────────

class TestCalculateHoursWorked:
    def test_single_completed_shift(self, staff_member):
        day = date(2026, 6, 1)
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(day, time(9, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_out", event_at=_aware(day, time(17, 0)))
        hours = calculate_hours_worked(staff=staff_member, date_from=day, date_to=day)
        assert hours == Decimal("8.00")

    def test_multiple_shifts_summed(self, staff_member):
        day1, day2 = date(2026, 6, 1), date(2026, 6, 2)
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(day1, time(9, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_out", event_at=_aware(day1, time(13, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(day2, time(9, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_out", event_at=_aware(day2, time(18, 0)))
        hours = calculate_hours_worked(staff=staff_member, date_from=day1, date_to=day2)
        assert hours == Decimal("13.00")  # 4 + 9

    def test_unclosed_trailing_shift_capped_at_date_to(self, staff_member):
        day = date(2026, 6, 1)
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(day, time(9, 0)))
        hours = calculate_hours_worked(staff=staff_member, date_from=day, date_to=day)
        # Capped at the end of date_to (23:59:59.999999) rather than excluded.
        assert hours == Decimal("15.00")

    def test_no_events_returns_zero(self, staff_member):
        hours = calculate_hours_worked(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 1))
        assert hours == Decimal("0.00")

    def test_events_outside_range_excluded(self, staff_member):
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(date(2026, 1, 1), time(9, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_out", event_at=_aware(date(2026, 1, 1), time(17, 0)))
        hours = calculate_hours_worked(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert hours == Decimal("0.00")


# ── Rota CRUD ─────────────────────────────────────────────────────────────────

class TestRotaEntry:
    def test_create_valid_entry(self, staff_member):
        rota = create_rota_entry(
            staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
            shift_start=time(9, 0), shift_end=time(17, 0),
        )
        assert rota.id is not None

    def test_shift_end_before_start_rejected(self, staff_member):
        with pytest.raises(ValidationError):
            create_rota_entry(
                staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                shift_start=time(17, 0), shift_end=time(9, 0),
            )

    def test_shift_end_equal_start_rejected(self, staff_member):
        with pytest.raises(ValidationError):
            create_rota_entry(
                staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                shift_start=time(9, 0), shift_end=time(9, 0),
            )

    def test_week_commencing_not_monday_rejected(self, staff_member):
        tuesday = date(2026, 6, 2)
        with pytest.raises(ValueError, match="must be a Monday"):
            create_rota_entry(
                staff=staff_member, week_commencing=tuesday, shift_date=tuesday,
                shift_start=time(9, 0), shift_end=time(17, 0),
            )

    def test_update_entry(self, staff_member):
        rota = create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                                 shift_start=time(9, 0), shift_end=time(17, 0))
        updated = update_rota_entry(rota, {"shift_end": time(18, 0)})
        assert updated.shift_end == time(18, 0)

    def test_update_with_invalid_shift_times_rejected(self, staff_member):
        rota = create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                                 shift_start=time(9, 0), shift_end=time(17, 0))
        with pytest.raises(ValidationError):
            update_rota_entry(rota, {"shift_start": time(20, 0)})

    def test_delete_entry(self, staff_member):
        rota = create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                                 shift_start=time(9, 0), shift_end=time(17, 0))
        delete_rota_entry(rota)
        assert not Rota.objects.filter(pk=rota.pk).exists()

    def test_get_rota_for_week(self, staff_member, other_cashier_staff):
        create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                          shift_start=time(9, 0), shift_end=time(17, 0))
        create_rota_entry(staff=other_cashier_staff, week_commencing=MONDAY, shift_date=MONDAY,
                          shift_start=time(10, 0), shift_end=time(18, 0))
        results = get_rota_for_week(week_commencing=MONDAY)
        assert len(results) == 2

    def test_get_rota_for_week_filters_by_department(self, staff_member, dept):
        other_dept = Department.objects.create(name="Other Dept Rota", slug="other-dept-rota", display_order=2)
        other_staff = Staff.objects.create(first_name="X", last_name="Y", email="xy-rota@staff-test.com",
                                           role="cashier", department=other_dept)
        create_rota_entry(staff=staff_member, department=dept, week_commencing=MONDAY, shift_date=MONDAY,
                          shift_start=time(9, 0), shift_end=time(17, 0))
        create_rota_entry(staff=other_staff, department=other_dept, week_commencing=MONDAY, shift_date=MONDAY,
                          shift_start=time(9, 0), shift_end=time(17, 0))
        results = get_rota_for_week(week_commencing=MONDAY, department=dept)
        assert len(results) == 1
        assert results[0].staff_id == staff_member.id


# ── calculate_commission ───────────────────────────────────────────────────────

class TestCalculateCommission:
    def test_sums_commission_for_paid_orders_in_range(self, staff_member):
        day = _aware(date(2026, 6, 15), time(12, 0))
        _make_paid_order(staff_member, 10_000, day)  # 1% of 10000p = 100p
        _make_paid_order(staff_member, 5_000, day)   # 1% of 5000p = 50p
        commission = calculate_commission(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert commission == 150

    def test_excludes_unpaid_orders(self, staff_member):
        Order.objects.create(cashier=staff_member, status="confirmed", total_pence=10_000, paid_at=None)
        commission = calculate_commission(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert commission == 0

    def test_excludes_orders_outside_range(self, staff_member):
        outside = _aware(date(2026, 1, 1), time(12, 0))
        _make_paid_order(staff_member, 10_000, outside)
        commission = calculate_commission(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert commission == 0

    def test_excludes_other_staff_orders(self, staff_member, other_cashier_staff):
        day = _aware(date(2026, 6, 15), time(12, 0))
        _make_paid_order(other_cashier_staff, 10_000, day)
        commission = calculate_commission(staff=staff_member, date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert commission == 0


# ── build_payroll_export ───────────────────────────────────────────────────────

class TestBuildPayrollExport:
    def test_reconciles_hours_wage_and_commission(self, staff_member):
        day = date(2026, 6, 1)
        ClockEvent.objects.create(staff=staff_member, event_type="clock_in", event_at=_aware(day, time(9, 0)))
        ClockEvent.objects.create(staff=staff_member, event_type="clock_out", event_at=_aware(day, time(17, 0)))  # 8h
        _make_paid_order(staff_member, 10_000, _aware(day, time(12, 0)))  # 1% of 10000p = 100p

        rows = build_payroll_export(date_from=day, date_to=day)
        row = next(r for r in rows if r["staff_id"] == staff_member.id)

        assert row["hours_worked"] == 8.0
        expected_wages = int(8 * float(staff_member.hourly_wage) * 100)
        assert row["wages_pence"] == expected_wages
        assert row["commission_pence"] == 100
        assert row["total_pence"] == row["wages_pence"] + row["commission_pence"]

    def test_filters_by_department(self, staff_member, dept):
        other_dept = Department.objects.create(name="Other Dept Payroll", slug="other-dept-payroll", display_order=2)
        other_staff = Staff.objects.create(first_name="X", last_name="Y", email="xy-payroll@staff-test.com",
                                           role="cashier", department=other_dept)
        rows = build_payroll_export(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30), department=dept)
        staff_ids = {r["staff_id"] for r in rows}
        assert staff_member.id in staff_ids
        assert other_staff.id not in staff_ids

    def test_excludes_inactive_staff(self, staff_member):
        staff_member.is_active = False
        staff_member.save()
        rows = build_payroll_export(date_from=date(2026, 6, 1), date_to=date(2026, 6, 30))
        assert staff_member.id not in {r["staff_id"] for r in rows}


# ── Staff CRUD API — permission boundaries ────────────────────────────────────

class TestStaffAPI:
    def test_cashier_forbidden(self, cashier_client):
        response = cashier_client.get(reverse("staff-list-create"))
        assert response.status_code == 403

    def test_department_manager_forbidden(self, dept_manager_client):
        response = dept_manager_client.get(reverse("staff-list-create"))
        assert response.status_code == 403

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.get(reverse("staff-list-create"))
        assert response.status_code == 401

    def test_store_manager_can_create(self, manager_client, dept):
        response = manager_client.post(
            reverse("staff-list-create"),
            {"first_name": "New", "last_name": "Hire", "email": "new.hire@staff-test.com", "department_id": dept.id},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_store_manager_can_list(self, manager_client, staff_member):
        response = manager_client.get(reverse("staff-list-create"))
        assert response.status_code == 200

    def test_store_manager_can_update(self, manager_client, staff_member):
        response = manager_client.patch(
            reverse("staff-detail", kwargs={"pk": staff_member.pk}), {"is_active": False}, format="json",
        )
        assert response.status_code == 200
        assert response.data["data"]["is_active"] is False


# ── Clock in/out API ───────────────────────────────────────────────────────────

class TestClockInOutAPI:
    def test_cashier_can_clock_self_in(self, cashier_client_and_staff):
        client, staff = cashier_client_and_staff
        response = client.post(reverse("clock-in"), {}, format="json")
        assert response.status_code == 201, response.data
        assert response.data["data"]["staff"] == staff.id

    def test_double_clock_in_returns_400(self, cashier_client_and_staff):
        client, _ = cashier_client_and_staff
        client.post(reverse("clock-in"), {}, format="json")
        response = client.post(reverse("clock-in"), {}, format="json")
        assert response.status_code == 400

    def test_clock_out_without_clock_in_returns_400(self, cashier_client):
        response = cashier_client.post(reverse("clock-out"), {}, format="json")
        assert response.status_code == 400

    def test_status_endpoint_transitions(self, cashier_client_and_staff):
        client, _ = cashier_client_and_staff
        response = client.get(reverse("clock-status"))
        assert response.data["data"]["status"] == "clocked_out"
        client.post(reverse("clock-in"), {}, format="json")
        response = client.get(reverse("clock-status"))
        assert response.data["data"]["status"] == "clocked_in"

    def test_cannot_clock_in_another_staff_member(self, cashier_client_and_staff, other_cashier_staff):
        client, staff = cashier_client_and_staff
        # staff_id in the body must be ignored — the actor is always resolved
        # from request.user.staff_profile, never from client-supplied input.
        response = client.post(reverse("clock-in"), {"staff_id": other_cashier_staff.id}, format="json")
        assert response.status_code == 201
        assert response.data["data"]["staff"] == staff.id
        assert response.data["data"]["staff"] != other_cashier_staff.id

    def test_unauthenticated_denied(self, anon_client):
        response = anon_client.post(reverse("clock-in"), {}, format="json")
        assert response.status_code == 401


# ── Rota API ───────────────────────────────────────────────────────────────────

class TestRotaAPI:
    def test_cashier_forbidden_on_list(self, cashier_client):
        response = cashier_client.get(reverse("rota-list-create"))
        assert response.status_code == 403

    def test_cashier_forbidden_on_create(self, cashier_client, staff_member):
        response = cashier_client.post(
            reverse("rota-list-create"),
            {"staff_id": staff_member.id, "week_commencing": MONDAY.isoformat(), "shift_date": MONDAY.isoformat(),
             "shift_start": "09:00:00", "shift_end": "17:00:00"},
            format="json",
        )
        assert response.status_code == 403

    def test_department_manager_can_create(self, dept_manager_client, staff_member):
        response = dept_manager_client.post(
            reverse("rota-list-create"),
            {"staff_id": staff_member.id, "week_commencing": MONDAY.isoformat(), "shift_date": MONDAY.isoformat(),
             "shift_start": "09:00:00", "shift_end": "17:00:00"},
            format="json",
        )
        assert response.status_code == 201, response.data

    def test_shift_end_before_start_returns_400(self, dept_manager_client, staff_member):
        response = dept_manager_client.post(
            reverse("rota-list-create"),
            {"staff_id": staff_member.id, "week_commencing": MONDAY.isoformat(), "shift_date": MONDAY.isoformat(),
             "shift_start": "17:00:00", "shift_end": "09:00:00"},
            format="json",
        )
        assert response.status_code == 400

    def test_non_monday_week_commencing_returns_400(self, dept_manager_client, staff_member):
        tuesday = date(2026, 6, 2)
        response = dept_manager_client.post(
            reverse("rota-list-create"),
            {"staff_id": staff_member.id, "week_commencing": tuesday.isoformat(), "shift_date": tuesday.isoformat(),
             "shift_start": "09:00:00", "shift_end": "17:00:00"},
            format="json",
        )
        assert response.status_code == 400

    def test_week_view(self, dept_manager_client, staff_member):
        create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                          shift_start=time(9, 0), shift_end=time(17, 0))
        response = dept_manager_client.get(reverse("rota-week"), {"week_commencing": MONDAY.isoformat()})
        assert response.status_code == 200
        assert len(response.data["data"]) == 1

    def test_delete(self, dept_manager_client, staff_member):
        rota = create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                                 shift_start=time(9, 0), shift_end=time(17, 0))
        response = dept_manager_client.delete(reverse("rota-detail", kwargs={"pk": rota.pk}))
        assert response.status_code == 200
        assert not Rota.objects.filter(pk=rota.pk).exists()

    def test_cashier_forbidden_on_delete(self, cashier_client, dept_manager_client, staff_member):
        rota = create_rota_entry(staff=staff_member, week_commencing=MONDAY, shift_date=MONDAY,
                                 shift_start=time(9, 0), shift_end=time(17, 0))
        response = cashier_client.delete(reverse("rota-detail", kwargs={"pk": rota.pk}))
        assert response.status_code == 403


# ── Payroll export API ─────────────────────────────────────────────────────────

class TestPayrollExportAPI:
    def test_cashier_forbidden(self, cashier_client):
        response = cashier_client.get(reverse("payroll-export"), {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        assert response.status_code == 403

    def test_department_manager_forbidden(self, dept_manager_client):
        response = dept_manager_client.get(reverse("payroll-export"), {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        assert response.status_code == 403

    def test_store_manager_can_view(self, manager_client, staff_member):
        response = manager_client.get(reverse("payroll-export"), {"date_from": "2026-06-01", "date_to": "2026-06-30"})
        assert response.status_code == 200

    def test_missing_date_params_returns_400(self, manager_client):
        response = manager_client.get(reverse("payroll-export"))
        assert response.status_code == 400
