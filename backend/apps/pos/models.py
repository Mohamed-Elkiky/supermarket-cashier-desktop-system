from django.db import models
from django.core.validators import MinValueValidator


class Promotion(models.Model):
    PROMOTION_TYPE_CHOICES = [
        ("percentage_discount", "Percentage Discount"),
        ("fixed_amount_off",    "Fixed Amount Off"),
        ("buy_one_get_one",     "Buy One Get One"),
        ("three_for_two",       "Three for Two"),
        ("meal_deal",           "Meal Deal"),
        ("category_markdown",   "Category Markdown"),
    ]

    name           = models.CharField(max_length=255)
    promotion_type = models.CharField(max_length=30, choices=PROMOTION_TYPE_CHOICES)
    # Percentage (0-100) or fixed pence amount depending on type
    discount_value = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    # Scope: whole department or specific variants (see PromotionVariant)
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name="promotions",
    )
    # Minimum basket spend in pence to qualify (used by meal_deal)
    min_spend_pence = models.IntegerField(null=True, blank=True)
    starts_at  = models.DateTimeField()
    ends_at    = models.DateTimeField()
    is_active  = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "staff.Staff",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="created_promotions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "promotions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.promotion_type})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError("ends_at must be after starts_at.")


class PromotionVariant(models.Model):
    """Links a promotion to specific variants. Empty = applies to whole department."""
    promotion = models.ForeignKey(
        Promotion,
        on_delete=models.CASCADE,
        related_name="variant_links",
    )
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        on_delete=models.CASCADE,
        related_name="promotion_links",
    )

    class Meta:
        db_table = "promotion_variants"
        unique_together = [["promotion", "variant"]]


class Order(models.Model):
    STATUS_CHOICES = [
        ("open",      "Open"),
        ("confirmed", "Confirmed"),
        ("paid",      "Paid"),
        ("voided",    "Voided"),
    ]
    PAYMENT_METHOD_CHOICES = [
        ("cash",           "Cash"),
        ("card",           "Card"),
        ("loyalty_points", "Loyalty Points"),
        ("mixed",          "Mixed"),
    ]

    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    cashier        = models.ForeignKey(
        "staff.Staff",
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name="orders",
    )
    # All monetary values stored in pence to avoid float rounding
    subtotal_pence       = models.IntegerField(default=0)
    discount_total_pence = models.IntegerField(default=0)
    tax_total_pence      = models.IntegerField(default=0)
    total_pence          = models.IntegerField(default=0)
    # Cash handling
    cash_tendered_pence  = models.IntegerField(null=True, blank=True)
    change_given_pence   = models.IntegerField(null=True, blank=True)
    # Payment
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True
    )
    # Loyalty
    loyalty_points_earned   = models.IntegerField(default=0)
    loyalty_points_redeemed = models.IntegerField(default=0)
    # Age verification
    age_verified            = models.BooleanField(default=False)
    age_verification_id_type = models.CharField(max_length=50, blank=True)
    # Receipt
    receipt_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    notes          = models.TextField(blank=True)
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    paid_at    = models.DateTimeField(null=True, blank=True)
    voided_at  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status"],     name="idx_orders_status"),
            models.Index(fields=["-created_at"], name="idx_orders_created_at"),
        ]

    def __str__(self):
        return f"Order #{self.id} [{self.status}] £{self.total_pence / 100:.2f}"

    @property
    def total_display(self):
        return f"£{self.total_pence / 100:.2f}"


class OrderItem(models.Model):
    order   = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant = models.ForeignKey(
        "inventory.ProductVariant",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    # Snapshot prices at time of sale — products can change later
    variant_name_snapshot = models.CharField(max_length=255)
    unit_price_pence      = models.IntegerField()
    # Weight for weight-based items
    weight_kg    = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    quantity     = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    # Promotion applied to this line
    promotion    = models.ForeignKey(
        Promotion,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="applied_items",
    )
    discount_pence   = models.IntegerField(default=0)
    line_total_pence = models.IntegerField()
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "order_items"
        indexes = [
            models.Index(fields=["order"],   name="idx_order_items_order_id"),
            models.Index(fields=["variant"], name="idx_order_items_variant_id"),
        ]

    def __str__(self):
        return f"OrderItem #{self.id} — {self.variant_name_snapshot} x{self.quantity}"