from django.urls import path

from .views import HealthCheckView, ManagerOnlyView

urlpatterns = [
    path("", HealthCheckView.as_view(), name="health-check"),
    path("manager-test/", ManagerOnlyView.as_view(), name="manager-test"),
]
