from django.db import models


class TemperatureLog(models.Model):
    """
    Immutable temperature check record — matches
    food_safety_temperature_logs in migrations/V008__food_safety_logs.sql.
    No row is ever updated or deleted. Corrections are new entries.
    """

    class Result(models.TextChoices):
        PASS = "pass", "Pass"
        FAIL = "fail", "Fail"

    unit_name = models.CharField(max_length=100)
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="temperature_logs",
    )
    temperature_celsius = models.DecimalField(max_digits=5, decimal_places=2)
    result = models.CharField(max_length=20, choices=Result.choices)
    corrective_action = models.TextField(null=True, blank=True)
    performed_by = models.ForeignKey(
        "staff.Staff",
        on_delete=models.PROTECT,
        related_name="temperature_logs",
    )
    checked_at = models.DateTimeField()
    was_offline = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "food_safety_temperature_logs"
        ordering = ["-checked_at"]
        indexes = [
            models.Index(fields=["department"], name="idx_temp_logs_department_id"),
            models.Index(fields=["-checked_at"], name="idx_temp_logs_checked_at"),
            models.Index(fields=["result"], name="idx_temp_logs_result"),
        ]

    def __str__(self):
        return f"{self.unit_name} | {self.result} | {self.checked_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "TemperatureLog entries are immutable. "
                "Create a new entry instead of updating."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "TemperatureLog entries cannot be deleted. "
            "They are permanent EHO compliance records."
        )


class CleaningLog(models.Model):
    """
    Immutable cleaning sign-off record — matches
    food_safety_cleaning_logs in migrations/V008__food_safety_logs.sql.
    No row is ever updated or deleted. Corrections are new entries.
    """

    class Result(models.TextChoices):
        COMPLETED = "completed", "Completed"
        MISSED = "missed", "Missed"
        PARTIAL = "partial", "Partial"

    area_name = models.CharField(max_length=200)
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="cleaning_logs",
    )
    scheduled_interval_hours = models.IntegerField(default=4)
    result = models.CharField(max_length=20, choices=Result.choices)
    notes = models.TextField(null=True, blank=True)
    # Missed cleanings may have no performer — hence SET_NULL, not PROTECT.
    performed_by = models.ForeignKey(
        "staff.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cleaning_logs",
    )
    alerted_manager = models.ForeignKey(
        "staff.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cleaning_alerts",
    )
    cleaned_at = models.DateTimeField()
    was_offline = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "food_safety_cleaning_logs"
        ordering = ["-cleaned_at"]
        indexes = [
            models.Index(fields=["department"], name="idx_cleaning_logs_dept_id"),
            models.Index(fields=["-cleaned_at"], name="idx_cleaning_logs_cleaned_at"),
            models.Index(fields=["result"], name="idx_cleaning_logs_result"),
        ]

    def __str__(self):
        return f"{self.area_name} | {self.result} | {self.cleaned_at:%Y-%m-%d %H:%M}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "CleaningLog entries are immutable. "
                "Create a new entry instead of updating."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "CleaningLog entries cannot be deleted. "
            "They are permanent EHO compliance records."
        )
