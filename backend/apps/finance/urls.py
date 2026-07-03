from django.urls import path

from .views import ExpenseListCreateView, ExpenseSummaryView

urlpatterns = [
    path("expenses/",         ExpenseListCreateView.as_view(), name="expense-list-create"),
    path("expenses/summary/", ExpenseSummaryView.as_view(),     name="expense-summary"),
]
