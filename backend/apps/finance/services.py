import logging

from django.db.models import Count, Sum

from .models import Expense

logger = logging.getLogger("apps.finance")


def record_expense(
    *, category, description, amount_pence, recorded_by, expense_date,
    payee_name="", supplier=None, reference="",
) -> Expense:
    """
    Validates and creates an Expense. Re-validates description length and
    amount_pence here (rather than relying solely on Expense.clean()/the DB
    CHECK constraints) so the API surfaces a clear ValueError instead of a
    raw IntegrityError.
    """
    if not description or len(description.strip()) < 20:
        raise ValueError(
            "description must fully explain who, what, why, and amount "
            "(minimum 20 characters)."
        )
    if amount_pence is None or amount_pence <= 0:
        raise ValueError("amount_pence must be greater than 0.")

    expense = Expense(
        category=category,
        description=description,
        amount_pence=amount_pence,
        payee_name=payee_name,
        supplier=supplier,
        recorded_by=recorded_by,
        expense_date=expense_date,
        reference=reference,
    )
    expense.full_clean()
    expense.save()
    logger.info(
        "Recorded expense id=%s category=%s amount=%dp", expense.id, category, amount_pence,
    )
    return expense


def get_expenses(*, category=None, date_from=None, date_to=None, supplier=None) -> list:
    qs = Expense.objects.select_related("supplier", "recorded_by")
    if category:
        qs = qs.filter(category=category)
    if date_from:
        qs = qs.filter(expense_date__gte=date_from)
    if date_to:
        qs = qs.filter(expense_date__lte=date_to)
    if supplier:
        qs = qs.filter(supplier=supplier)
    return list(qs)


def get_expense_summary_by_category(*, date_from, date_to) -> list:
    """
    Aggregate total pence per category for the given date range.
    Kept as a simple flat shape for Sprint 5's P&L report to consume:
    [{"category": ..., "total_pence": ..., "count": ...}, ...]
    """
    rows = (
        Expense.objects
        .filter(expense_date__gte=date_from, expense_date__lte=date_to)
        .values("category")
        .annotate(total_pence=Sum("amount_pence"), count=Count("id"))
        .order_by("category")
    )
    return [
        {"category": row["category"], "total_pence": row["total_pence"], "count": row["count"]}
        for row in rows
    ]
