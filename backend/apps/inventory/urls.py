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
)

urlpatterns = [
    # Allergens
    path("allergens/", AllergenListView.as_view(), name="allergen-list"),

    # Barcode scanner (cashier hot-path)
    path("barcode/", BarcodeLookupView.as_view(), name="barcode-lookup"),

    # Products
    path("products/", ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<int:pk>/", ProductDetailView.as_view(), name="product-detail"),

    # Variants
    path("products/<int:pk>/variants/", ProductVariantListCreateView.as_view(), name="variant-list-create"),
    path("products/<int:pk>/variants/<int:variant_pk>/", ProductVariantDetailView.as_view(), name="variant-detail"),

    # Allergen management for a variant
    path("products/<int:pk>/variants/<int:variant_pk>/allergens/", ProductVariantAllergenView.as_view(), name="variant-allergens"),

    # Line-total calculator (no DB writes)
    path("products/<int:pk>/variants/<int:variant_pk>/line-total/", ProductVariantLineTotalView.as_view(), name="variant-line-total"),
]