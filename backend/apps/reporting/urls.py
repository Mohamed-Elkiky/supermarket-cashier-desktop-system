from django.urls import path

from .views import (
    BestSellersView,
    DepartmentPerformanceView,
    SalesDashboardView,
    StaffPerformanceView,
    WasteCostView,
)

urlpatterns = [
    path("sales-dashboard/",         SalesDashboardView.as_view(),        name="sales-dashboard"),
    path("department-performance/",  DepartmentPerformanceView.as_view(), name="department-performance"),
    path("best-sellers/",            BestSellersView.as_view(),           name="best-sellers"),
    path("waste-cost/",              WasteCostView.as_view(),             name="waste-cost"),
    path("staff-performance/",       StaffPerformanceView.as_view(),      name="staff-performance"),
]
