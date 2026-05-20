from django.urls import path
from .views import (
    DepartmentCategoryDetailView, DepartmentCategoryListCreateView,
    DepartmentDetailView, DepartmentListCreateView,
    DepartmentPriceSuggestionView, DepartmentPricingRuleView,
    DepartmentStockSettingsView,
)

urlpatterns = [
    path("", DepartmentListCreateView.as_view(), name="department-list-create"),
    path("<int:pk>/", DepartmentDetailView.as_view(), name="department-detail"),
    path("<int:pk>/pricing-rule/", DepartmentPricingRuleView.as_view(), name="department-pricing-rule"),
    path("<int:pk>/stock-settings/", DepartmentStockSettingsView.as_view(), name="department-stock-settings"),
    path("<int:pk>/categories/", DepartmentCategoryListCreateView.as_view(), name="department-category-list-create"),
    path("<int:pk>/categories/<int:cat_pk>/", DepartmentCategoryDetailView.as_view(), name="department-category-detail"),
    path("<int:pk>/price-suggestion/", DepartmentPriceSuggestionView.as_view(), name="department-price-suggestion"),
]