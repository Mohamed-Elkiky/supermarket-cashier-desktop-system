from django.urls import path

from .views import (
    ClockInView,
    ClockOutView,
    ClockStatusView,
    PayrollExportView,
    RotaDetailView,
    RotaListCreateView,
    RotaWeekView,
    StaffDetailView,
    StaffListCreateView,
)

urlpatterns = [
    path("staff/",                    StaffListCreateView.as_view(), name="staff-list-create"),
    path("staff/<int:pk>/",           StaffDetailView.as_view(),     name="staff-detail"),

    path("clock-events/clock-in/",    ClockInView.as_view(),         name="clock-in"),
    path("clock-events/clock-out/",   ClockOutView.as_view(),        name="clock-out"),
    path("clock-events/status/",      ClockStatusView.as_view(),     name="clock-status"),

    path("rotas/",                    RotaListCreateView.as_view(),  name="rota-list-create"),
    path("rotas/week/",                RotaWeekView.as_view(),        name="rota-week"),
    path("rotas/<int:pk>/",           RotaDetailView.as_view(),      name="rota-detail"),

    path("payroll-export/",           PayrollExportView.as_view(),   name="payroll-export"),
]
