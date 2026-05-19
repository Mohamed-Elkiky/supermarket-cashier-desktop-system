from django.urls import path

from .views import LoginView, LogoutView, SilentRefreshView

urlpatterns = [
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("refresh/", SilentRefreshView.as_view(), name="auth-refresh"),
]
