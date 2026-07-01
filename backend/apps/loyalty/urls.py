from django.urls import path

from .views import (
    AdjustPointsView,
    BasketConflictCheckView,
    CustomerDetailView,
    CustomerListCreateView,
    CustomerSearchView,
    LoyaltyProfileView,
    RedeemPointsView,
)

urlpatterns = [
    path("customers/",                        CustomerListCreateView.as_view(), name="customer-list-create"),
    path("customers/search/",                 CustomerSearchView.as_view(),     name="customer-search"),
    path("customers/<int:pk>/",                CustomerDetailView.as_view(),     name="customer-detail"),
    path("customers/<int:pk>/loyalty/",        LoyaltyProfileView.as_view(),     name="customer-loyalty-profile"),
    path("customers/<int:pk>/loyalty/redeem/", RedeemPointsView.as_view(),       name="customer-loyalty-redeem"),
    path("customers/<int:pk>/loyalty/adjust/", AdjustPointsView.as_view(),       name="customer-loyalty-adjust"),
    path("basket-conflict-check/",             BasketConflictCheckView.as_view(), name="basket-conflict-check"),
]
