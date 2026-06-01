from django.db import models
from django.core.validators import MinValueValidator


class Supplier(models.Model):
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=200, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "suppliers"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Allergen(models.Model):
    name = models.CharField(max_length=100, unique=True)
    eu_code = models.CharField(max_length=10, unique=True)

    class Meta:
        db_table = "allergens"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    department = models.ForeignKey(
        "departments.Department",
        on_delete=models.PROTECT,
        related_name="products",
    )
    supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_age_restricted = models.BooleanField(default=False)
    age_restriction_years = models.IntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.is_age_restricted and not self.age_restriction_years:
            raise ValidationError("age_restriction_years is required when is_age_restricted is True.")


class ProductVariant(models.Model):
    PRICING_MODE_CHOICES = [
        ("fixed", "Fixed price"),
        ("weight_based", "Weight-based (per kg)"),
    ]
    UNIT_OF_MEASURE_CHOICES = [
        ("unit", "Unit"),
        ("kg", "Kilogram"),
        ("g", "Gram"),
        ("litre", "Litre"),
        ("ml", "Millilitre"),
    ]

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="variants",
    )
    sku = models.CharField(max_length=100, unique=True)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    name = models.CharField(max_length=255)
    pricing_mode = models.CharField(
        max_length=20,
        choices=PRICING_MODE_CHOICES,
        default="fixed",
    )
    sell_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    cost_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )
    unit_of_measure = models.CharField(
        max_length=20,
        choices=UNIT_OF_MEASURE_CHOICES,
        default="unit",
    )
    low_stock_threshold = models.IntegerField(default=0)
    track_expiry = models.BooleanField(default=False)
    expiry_alert_days = models.IntegerField(default=3)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "product_variants"
        ordering = ["name"]

    def __str__(self):
        return f"{self.product.name} — {self.name}"

    def calculate_line_total(self, weight_kg: float = None) -> float:
        """
        For fixed pricing: returns sell_price.
        For weight_based pricing: returns sell_price * weight_kg.
        """
        if self.pricing_mode == "weight_based":
            if weight_kg is None or weight_kg <= 0:
                raise ValueError("weight_kg is required for weight-based products.")
            return float(self.sell_price) * weight_kg
        return float(self.sell_price)


class ProductVariantAllergen(models.Model):
    variant = models.ForeignKey(
        ProductVariant,
        on_delete=models.CASCADE,
        related_name="allergen_links",
    )
    allergen = models.ForeignKey(
        Allergen,
        on_delete=models.CASCADE,
    )
    may_contain = models.BooleanField(default=False)

    class Meta:
        db_table = "product_variant_allergens"
        unique_together = [["variant", "allergen"]]