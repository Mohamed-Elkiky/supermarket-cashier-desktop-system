from django.core.validators import MinValueValidator
from django.db import models


class Expense(models.Model):
    """
    Immutable expense record — matches the `expenses` table in
    migrations/V007__expenses.sql. Every entry is permanent: no updates,
    no deletes, and (unlike most other models here) intentionally no
    updated_at column at all.
    """

    class Category(models.TextChoices):
        STAFF_WAGES = "staff_wages", "Staff Wages"
        SUPPLIER_PAYMENT = "supplier_payment", "Supplier Payment"
        UTILITIES = "utilities", "Utilities"
        RENT = "rent", "Rent"
        MAINTENANCE = "maintenance", "Maintenance"
        EQUIPMENT = "equipment", "Equipment"
        MARKETING = "marketing", "Marketing"
        INSURANCE = "insurance", "Insurance"
        OTHER = "other", "Other"

    category = models.CharField(max_length=20, choices=Category.choices)
    # Mandatory full description: who, what, why, amount context.
    description = models.TextField()
    amount_pence = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    payee_name = models.CharField(max_length=255, blank=True)
    supplier = models.ForeignKey(
        "inventory.Supplier", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="expenses",
    )
    recorded_by = models.ForeignKey(
        "staff.Staff", on_delete=models.PROTECT, related_name="expenses",
    )
    # Date the expense actually occurred — may differ from created_at.
    expense_date = models.DateField()
    reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "expenses"
        ordering = ["-expense_date"]
        indexes = [
            models.Index(fields=["category"], name="idx_expenses_category"),
            models.Index(fields=["-expense_date"], name="idx_expenses_expense_date"),
            models.Index(fields=["recorded_by"], name="idx_expenses_recorded_by"),
        ]

    def __str__(self):
        return f"{self.category} — £{self.amount_pence / 100:.2f} ({self.expense_date})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.description and len(self.description.strip()) < 20:
            raise ValidationError(
                "description must fully explain who, what, why, and amount "
                "(minimum 20 characters)."
            )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError(
                "Expense entries are immutable. There is no edit path — "
                "record a correcting entry instead."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Expense entries cannot be deleted. They are permanent financial records."
        )
