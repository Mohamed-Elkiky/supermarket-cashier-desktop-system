from django.urls import path

from .views import (
    OrderCreateView,
    OrderDetailView,
    OrderAddItemView,
    OrderRemoveItemView,
    OrderConfirmView,
    OrderCheckoutView,
    OrderReceiptView,
    OrderVoidView,
    PromotionListCreateView,
    PromotionDetailView,
    PromotionDeactivateView,
)

urlpatterns = [
    path("orders/",                              OrderCreateView.as_view(),    name="order-create"),
    path("orders/<int:pk>/",                     OrderDetailView.as_view(),    name="order-detail"),
    path("orders/<int:pk>/items/",               OrderAddItemView.as_view(),   name="order-add-item"),
    path("orders/<int:pk>/items/<int:item_pk>/", OrderRemoveItemView.as_view(), name="order-remove-item"),
    path("orders/<int:pk>/confirm/",             OrderConfirmView.as_view(),   name="order-confirm"),
    path("orders/<int:pk>/checkout/",            OrderCheckoutView.as_view(),  name="order-checkout"),
    path("orders/<int:pk>/receipt/",             OrderReceiptView.as_view(),   name="order-receipt"),
    path("orders/<int:pk>/void/",                OrderVoidView.as_view(),      name="order-void"),
    path("promotions/",                          PromotionListCreateView.as_view(), name="promotion-list-create"),
    path("promotions/<int:pk>/",                 PromotionDetailView.as_view(),     name="promotion-detail"),
    path("promotions/<int:pk>/deactivate/",      PromotionDeactivateView.as_view(), name="promotion-deactivate"),
]