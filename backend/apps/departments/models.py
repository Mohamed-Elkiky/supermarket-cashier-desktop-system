from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.text import slugify


class Department(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "departments"
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class DepartmentCategory(models.Model):
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="categories"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    display_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "department_categories"
        ordering = ["display_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "parent", "slug"],
                name="unique_category_slug_per_parent",
            )
        ]

    def __str__(self):
        if self.parent:
            return f"{self.department.name} > {self.parent.name} > {self.name}"
        return f"{self.department.name} > {self.name}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def depth(self) -> int:
        return 1 if self.parent_id is None else 2

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent.parent_id is not None:
            raise ValidationError(
                "Category tree is limited to two levels. "
                "Cannot create a child of a child category."
            )
        if self.parent_id and self.parent.department_id != self.department_id:
            raise ValidationError("Parent category must belong to the same department.")


class DepartmentPricingRule(models.Model):
    ROUNDING_CHOICES = [
        ("nearest_penny", "Nearest penny"),
        ("nearest_5p", "Nearest 5p"),
        ("nearest_10p", "Nearest 10p"),
        ("psychological", "Psychological (X.99)"),
    ]

    department = models.OneToOneField(
        Department, on_delete=models.CASCADE, related_name="pricing_rule"
    )
    default_markup_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(999)],
    )
    rounding_strategy = models.CharField(
        max_length=20, choices=ROUNDING_CHOICES, default="nearest_penny"
    )
    minimum_margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    max_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    display_prices_inclusive_of_tax = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "department_pricing_rules"

    def __str__(self):
        return f"Pricing rule for {self.department.name}"


class DepartmentStockSettings(models.Model):
    department = models.OneToOneField(
        Department, on_delete=models.CASCADE, related_name="stock_settings"
    )
    default_low_stock_threshold = models.IntegerField(
        default=5, validators=[MinValueValidator(0)]
    )
    track_expiry_by_default = models.BooleanField(default=False)
    default_expiry_alert_days = models.IntegerField(
        default=3, validators=[MinValueValidator(1)]
    )
    default_pricing_mode = models.CharField(
        max_length=20,
        choices=[("fixed", "Fixed price"), ("weight_based", "Weight-based (per kg)")],
        default="fixed",
    )
    requires_temperature_checks = models.BooleanField(default=False)
    temperature_min_celsius = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    temperature_max_celsius = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "department_stock_settings"

    def __str__(self):
        return f"Stock settings for {self.department.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if (
            self.temperature_min_celsius is not None
            and self.temperature_max_celsius is not None
            and self.temperature_min_celsius >= self.temperature_max_celsius
        ):
            raise ValidationError(
                "temperature_min_celsius must be less than temperature_max_celsius."
            )