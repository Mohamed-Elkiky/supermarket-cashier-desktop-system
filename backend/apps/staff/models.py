from django.conf import settings
from django.db import models
from django.utils import timezone


class Staff(models.Model):
    ROLE_CHOICES = [
        ("cashier", "Cashier"),
        ("department_manager", "Department Manager"),
        ("store_manager", "Store Manager"),
        ("admin", "Admin"),
        ("owner", "Owner"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="staff_profile",
        null=True,
        blank=True,
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=30, blank=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, default="cashier")
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    hourly_wage = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    hired_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "staff"

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.role})"


class ClockEvent(models.Model):
    """
    Clock in/out event — matches `staff_clock_events` in
    migrations/V006__staff_clock_events_rotas.sql.

    V006 doesn't carry an explicit "no update/delete" comment for this table
    the way V007 (expenses) and V008 (food safety logs) do for theirs. It's
    made immutable here anyway as a deliberate design choice, for the same
    audit-trail-integrity reason those tables are immutable: a clock event is
    a timestamped fact about when someone was on shift. If a clock event is
    wrong, log a correcting adjustment through a manager tool — don't edit
    history.
    """

    class EventType(models.TextChoices):
        CLOCK_IN = "clock_in", "Clock In"
        CLOCK_OUT = "clock_out", "Clock Out"

    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name="clock_events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    # Recorded in UTC always.
    event_at = models.DateTimeField(default=timezone.now)
    was_offline = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "staff_clock_events"
        ordering = ["-event_at"]
        indexes = [
            models.Index(fields=["staff"], name="idx_clock_events_staff_id"),
            models.Index(fields=["-event_at"], name="idx_clock_events_event_at"),
        ]

    def __str__(self):
        return f"staff#{self.staff_id} {self.event_type} @ {self.event_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "ClockEvent entries are immutable. Log a correcting adjustment "
                "instead of updating."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "ClockEvent entries cannot be deleted. They are permanent audit records."
        )


class Rota(models.Model):
    """
    Shift schedule entry — matches `rotas` in
    migrations/V006__staff_clock_events_rotas.sql. Unlike ClockEvent, rotas
    ARE editable — managers drag-and-drop shifts to build the weekly grid.
    """

    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, related_name="rota_entries")
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rota_entries",
    )
    # Week commencing Monday — used to group the rota grid.
    week_commencing = models.DateField()
    shift_date = models.DateField()
    shift_start = models.TimeField()
    shift_end = models.TimeField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        Staff,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotas_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rotas"
        ordering = ["week_commencing", "shift_date", "shift_start"]
        indexes = [
            models.Index(fields=["staff"], name="idx_rotas_staff_id"),
            models.Index(fields=["week_commencing"], name="idx_rotas_week_commencing"),
        ]

    def __str__(self):
        return f"staff#{self.staff_id} {self.shift_date} {self.shift_start}-{self.shift_end}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.shift_start and self.shift_end and self.shift_end <= self.shift_start:
            raise ValidationError("shift_end must be after shift_start.")
