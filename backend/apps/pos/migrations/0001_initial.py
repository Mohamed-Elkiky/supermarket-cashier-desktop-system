from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("departments", "0003_seed_department_defaults"),
        ("inventory",   "0001_initial"),
        ("staff",       "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Promotion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("promotion_type", models.CharField(max_length=30, choices=[
                    ("percentage_discount", "Percentage Discount"),
                    ("fixed_amount_off",    "Fixed Amount Off"),
                    ("buy_one_get_one",     "Buy One Get One"),
                    ("three_for_two",       "Three for Two"),
                    ("meal_deal",           "Meal Deal"),
                    ("category_markdown",   "Category Markdown"),
                ])),
                ("discount_value", models.DecimalField(
                    decimal_places=2, max_digits=10,
                    validators=[django.core.validators.MinValueValidator(0.01)],
                )),
                ("min_spend_pence", models.IntegerField(null=True, blank=True)),
                ("starts_at",  models.DateTimeField()),
                ("ends_at",    models.DateTimeField()),
                ("is_active",  models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("department", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="promotions",
                    to="departments.department",
                )),
                ("created_by", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="created_promotions",
                    to="staff.staff",
                )),
            ],
            options={"db_table": "promotions", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="PromotionVariant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("promotion", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="variant_links",
                    to="pos.promotion",
                )),
                ("variant", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="promotion_links",
                    to="inventory.productvariant",
                )),
            ],
            options={"db_table": "promotion_variants"},
        ),
        migrations.AlterUniqueTogether(
            name="promotionvariant",
            unique_together={("promotion", "variant")},
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("status", models.CharField(max_length=20, default="open", choices=[
                    ("open", "Open"), ("confirmed", "Confirmed"),
                    ("paid", "Paid"), ("voided", "Voided"),
                ])),
                ("subtotal_pence",        models.IntegerField(default=0)),
                ("discount_total_pence",  models.IntegerField(default=0)),
                ("tax_total_pence",       models.IntegerField(default=0)),
                ("total_pence",           models.IntegerField(default=0)),
                ("cash_tendered_pence",   models.IntegerField(null=True, blank=True)),
                ("change_given_pence",    models.IntegerField(null=True, blank=True)),
                ("payment_method", models.CharField(max_length=20, null=True, blank=True, choices=[
                    ("cash", "Cash"), ("card", "Card"),
                    ("loyalty_points", "Loyalty Points"), ("mixed", "Mixed"),
                ])),
                ("loyalty_points_earned",   models.IntegerField(default=0)),
                ("loyalty_points_redeemed", models.IntegerField(default=0)),
                ("age_verified",             models.BooleanField(default=False)),
                ("age_verification_id_type", models.CharField(max_length=50, blank=True)),
                ("receipt_number", models.CharField(max_length=50, unique=True, null=True, blank=True)),
                ("notes",      models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("paid_at",    models.DateTimeField(null=True, blank=True)),
                ("voided_at",  models.DateTimeField(null=True, blank=True)),
                ("cashier", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="orders",
                    to="staff.staff",
                )),
            ],
            options={"db_table": "orders", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["status"],     name="idx_orders_status"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["-created_at"], name="idx_orders_created_at"),
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("variant_name_snapshot", models.CharField(max_length=255)),
                ("unit_price_pence",      models.IntegerField()),
                ("weight_kg",   models.DecimalField(decimal_places=3, max_digits=10, null=True, blank=True)),
                ("quantity",    models.IntegerField(default=1, validators=[django.core.validators.MinValueValidator(1)])),
                ("discount_pence",   models.IntegerField(default=0)),
                ("line_total_pence", models.IntegerField()),
                ("created_at",       models.DateTimeField(auto_now_add=True)),
                ("order", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="items",
                    to="pos.order",
                )),
                ("variant", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="order_items",
                    to="inventory.productvariant",
                )),
                ("promotion", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="applied_items",
                    to="pos.promotion",
                )),
            ],
            options={"db_table": "order_items"},
        ),
        migrations.AddIndex(
            model_name="orderitem",
            index=models.Index(fields=["order"],   name="idx_order_items_order_id"),
        ),
        migrations.AddIndex(
            model_name="orderitem",
            index=models.Index(fields=["variant"], name="idx_order_items_variant_id"),
        ),
    ]