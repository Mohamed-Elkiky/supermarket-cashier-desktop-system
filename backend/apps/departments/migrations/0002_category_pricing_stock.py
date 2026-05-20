import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("departments", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="department",
            options={"ordering": ["display_order", "name"]},
        ),
        migrations.CreateModel(
            name="DepartmentCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100)),
                ("slug", models.SlugField(max_length=100)),
                ("display_order", models.IntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="categories", to="departments.department")),
                ("parent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="children", to="departments.departmentcategory")),
            ],
            options={"db_table": "department_categories", "ordering": ["display_order", "name"]},
        ),
        migrations.AddConstraint(
            model_name="departmentcategory",
            constraint=models.UniqueConstraint(
                fields=["department", "parent", "slug"],
                name="unique_category_slug_per_parent",
            ),
        ),
        migrations.CreateModel(
            name="DepartmentPricingRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("default_markup_percent", models.DecimalField(decimal_places=2, default=0, max_digits=6, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(999)])),
                ("rounding_strategy", models.CharField(choices=[("nearest_penny", "Nearest penny"), ("nearest_5p", "Nearest 5p"), ("nearest_10p", "Nearest 10p"), ("psychological", "Psychological (X.99)")], default="nearest_penny", max_length=20)),
                ("minimum_margin_percent", models.DecimalField(decimal_places=2, default=0, max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("max_discount_percent", models.DecimalField(decimal_places=2, default=10, max_digits=5, validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)])),
                ("display_prices_inclusive_of_tax", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="pricing_rule", to="departments.department")),
            ],
            options={"db_table": "department_pricing_rules"},
        ),
        migrations.CreateModel(
            name="DepartmentStockSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("default_low_stock_threshold", models.IntegerField(default=5, validators=[django.core.validators.MinValueValidator(0)])),
                ("track_expiry_by_default", models.BooleanField(default=False)),
                ("default_expiry_alert_days", models.IntegerField(default=3, validators=[django.core.validators.MinValueValidator(1)])),
                ("default_pricing_mode", models.CharField(choices=[("fixed", "Fixed price"), ("weight_based", "Weight-based (per kg)")], default="fixed", max_length=20)),
                ("requires_temperature_checks", models.BooleanField(default=False)),
                ("temperature_min_celsius", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("temperature_max_celsius", models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="stock_settings", to="departments.department")),
            ],
            options={"db_table": "department_stock_settings"},
        ),
    ]