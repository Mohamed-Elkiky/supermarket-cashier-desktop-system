from django.urls import path

from .views import (
    CleaningLogListCreateView,
    EhoExportView,
    MissedChecksView,
    TemperatureLogListCreateView,
)

urlpatterns = [
    path("temperature-logs/", TemperatureLogListCreateView.as_view(), name="temperature-log-list-create"),
    path("cleaning-logs/",    CleaningLogListCreateView.as_view(),    name="cleaning-log-list-create"),
    path("missed-checks/",    MissedChecksView.as_view(),             name="missed-checks"),
    path("eho-export/",       EhoExportView.as_view(),                name="eho-export"),
]
