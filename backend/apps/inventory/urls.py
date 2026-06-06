from django.urls import path

from .views import (
    AllergenListView,
    BarcodeLookupView,
    ProductListCreateView,
    ProductDetailView,
    ProductVariantListCreateView,
    ProductVariantDetailView,
    ProductVariantAllergenView,
    ProductVariantLineTotalView,
    LedgerLocationListView,
    LedgerListView,
    LedgerMovementView,
    StockLevelView,
    StockLevelBulkView,
    ExpiryAlertView,
)

urlpatterns = [
    # Allergens
    path("allergens/", AllergenListView.as_view(), name="allergen-list"),

    # Barcode scanner
    path("barcode/", BarcodeLookupView.as_view(), name="barcode-lookup"),

    # Products
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),

    # Variants
    path("products/<int:pk>/variants/", ProductVariantListCreateView.as_view(), name="variant-list-create"),
    path("products/<int:pk>/variants/<int:variant_pk>/", ProductVariantDetailView.as_view(), name="variant-detail"),
    path("products/<int:pk>/variants/<int:variant_pk>/allergens/", ProductVariantAllergenView.as_view(), name="variant-allergens"),
    path("products/<int:pk>/variants/<int:variant_pk>/line-total/", ProductVariantLineTotalView.as_view(), name="variant-line-total"),

    # Stock levels (ledger-derived)
    path("stock/<int:variant_pk>/", StockLevelView.as_view(), name="stock-level"),
    path("stock/bulk/", StockLevelBulkView.as_view(), name="stock-level-bulk"),

    # Ledger locations
    path("ledger/locations/", LedgerLocationListView.as_view(), name="ledger-location-list"),

    # Ledger entries + movements
    path("ledger/", LedgerListView.as_view(), name="ledger-list"),
    path("ledger/movements/", LedgerMovementView.as_view(), name="ledger-movement"),

    # Expiry alerts
    path("ledger/expiry/<int:department_pk>/", ExpiryAlertView.as_view(), name="expiry-alerts"),
]