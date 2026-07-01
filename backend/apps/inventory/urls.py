from django.urls import path

from .views import (
    AllergenAuditExportView,
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
    LowStockAlertView,
    VariantExpiryStatusView,
    BasketExpiryCheckView,
)

urlpatterns = [
    # Allergens
    path("allergens/", AllergenListView.as_view(), name="allergen-list"),
    path("allergens/audit-export/", AllergenAuditExportView.as_view(), name="allergen-audit-export"),

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

    # Low stock alerts (per department)
    path("stock/alerts/<int:department_pk>/", LowStockAlertView.as_view(), name="low-stock-alerts"),

    # Ledger locations
    path("ledger/locations/", LedgerLocationListView.as_view(), name="ledger-location-list"),

    # Ledger entries + movements
    path("ledger/", LedgerListView.as_view(), name="ledger-list"),
    path("ledger/movements/", LedgerMovementView.as_view(), name="ledger-movement"),

    # Expiry alerts (department-wide)
    path("ledger/expiry/<int:department_pk>/", ExpiryAlertView.as_view(), name="expiry-alerts"),

    # Per-variant expiry status (used at scan time)
    path("expiry/<int:variant_pk>/", VariantExpiryStatusView.as_view(), name="variant-expiry-status"),

    # Basket expiry check (called before checkout)
    path("expiry/basket/check/", BasketExpiryCheckView.as_view(), name="basket-expiry-check"),
]