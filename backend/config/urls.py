from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    # API v1
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/inventory/", include("apps.inventory.urls")),
    path("api/v1/pos/", include("apps.pos.urls")),
    path("api/v1/departments/", include("apps.departments.urls")),
    path("api/v1/loyalty/", include("apps.loyalty.urls")),
    path("api/v1/food-safety/", include("apps.food_safety.urls")),
    path("api/v1/staff/", include("apps.staff.urls")),
    path("api/v1/finance/", include("apps.finance.urls")),
    path("api/v1/reporting/", include("apps.reporting.urls")),
    # OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    # Health check
    path("api/health/", include("apps.core.urls")),
]
