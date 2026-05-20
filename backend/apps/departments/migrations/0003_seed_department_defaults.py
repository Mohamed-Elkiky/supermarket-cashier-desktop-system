from django.db import migrations

DEPARTMENT_SEEDS = {
    "fresh-produce": {
        "pricing": {"default_markup_percent": "35.00", "rounding_strategy": "nearest_penny", "minimum_margin_percent": "20.00", "max_discount_percent": "30.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 10, "track_expiry_by_default": True, "default_expiry_alert_days": 2, "default_pricing_mode": "weight_based", "requires_temperature_checks": True, "temperature_min_celsius": "1.00", "temperature_max_celsius": "8.00"},
        "categories": [
            {"name": "Vegetables", "slug": "vegetables", "display_order": 1, "children": [{"name": "Root Vegetables", "slug": "root-vegetables", "display_order": 1}, {"name": "Salad & Leaves", "slug": "salad-leaves", "display_order": 2}, {"name": "Brassicas", "slug": "brassicas", "display_order": 3}, {"name": "Alliums", "slug": "alliums", "display_order": 4}]},
            {"name": "Fruit", "slug": "fruit", "display_order": 2, "children": [{"name": "Citrus", "slug": "citrus", "display_order": 1}, {"name": "Berries", "slug": "berries", "display_order": 2}, {"name": "Stone Fruit", "slug": "stone-fruit", "display_order": 3}, {"name": "Tropical", "slug": "tropical", "display_order": 4}]},
            {"name": "Herbs", "slug": "herbs", "display_order": 3, "children": []},
            {"name": "Mushrooms", "slug": "mushrooms", "display_order": 4, "children": []},
        ],
    },
    "bakery": {
        "pricing": {"default_markup_percent": "60.00", "rounding_strategy": "psychological", "minimum_margin_percent": "30.00", "max_discount_percent": "50.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 5, "track_expiry_by_default": True, "default_expiry_alert_days": 1, "default_pricing_mode": "fixed", "requires_temperature_checks": False, "temperature_min_celsius": None, "temperature_max_celsius": None},
        "categories": [
            {"name": "Bread", "slug": "bread", "display_order": 1, "children": [{"name": "White Bread", "slug": "white-bread", "display_order": 1}, {"name": "Wholemeal & Seeded", "slug": "wholemeal-seeded", "display_order": 2}, {"name": "Artisan Loaves", "slug": "artisan-loaves", "display_order": 3}, {"name": "Rolls & Baps", "slug": "rolls-baps", "display_order": 4}]},
            {"name": "Pastries & Croissants", "slug": "pastries-croissants", "display_order": 2, "children": []},
            {"name": "Cakes & Tarts", "slug": "cakes-tarts", "display_order": 3, "children": [{"name": "Celebration Cakes", "slug": "celebration-cakes", "display_order": 1}, {"name": "Individual Cakes", "slug": "individual-cakes", "display_order": 2}, {"name": "Tarts & Slices", "slug": "tarts-slices", "display_order": 3}]},
            {"name": "Pies & Savoury", "slug": "pies-savoury", "display_order": 4, "children": []},
        ],
    },
    "deli-counter": {
        "pricing": {"default_markup_percent": "45.00", "rounding_strategy": "nearest_5p", "minimum_margin_percent": "25.00", "max_discount_percent": "20.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 3, "track_expiry_by_default": True, "default_expiry_alert_days": 2, "default_pricing_mode": "weight_based", "requires_temperature_checks": True, "temperature_min_celsius": "0.00", "temperature_max_celsius": "5.00"},
        "categories": [
            {"name": "Cooked Meats", "slug": "cooked-meats", "display_order": 1, "children": [{"name": "Ham & Gammon", "slug": "ham-gammon", "display_order": 1}, {"name": "Poultry", "slug": "poultry", "display_order": 2}, {"name": "Beef & Pork", "slug": "beef-pork", "display_order": 3}]},
            {"name": "Cheese", "slug": "cheese", "display_order": 2, "children": [{"name": "Hard Cheese", "slug": "hard-cheese", "display_order": 1}, {"name": "Soft Cheese", "slug": "soft-cheese", "display_order": 2}, {"name": "Blue Cheese", "slug": "blue-cheese", "display_order": 3}]},
            {"name": "Pâté & Spreads", "slug": "pate-spreads", "display_order": 3, "children": []},
            {"name": "Olives & Antipasti", "slug": "olives-antipasti", "display_order": 4, "children": []},
            {"name": "Salads & Prepared", "slug": "salads-prepared", "display_order": 5, "children": []},
        ],
    },
    "dairy": {
        "pricing": {"default_markup_percent": "25.00", "rounding_strategy": "psychological", "minimum_margin_percent": "10.00", "max_discount_percent": "15.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 12, "track_expiry_by_default": True, "default_expiry_alert_days": 5, "default_pricing_mode": "fixed", "requires_temperature_checks": True, "temperature_min_celsius": "1.00", "temperature_max_celsius": "8.00"},
        "categories": [
            {"name": "Milk", "slug": "milk", "display_order": 1, "children": [{"name": "Whole Milk", "slug": "whole-milk", "display_order": 1}, {"name": "Semi-Skimmed", "slug": "semi-skimmed", "display_order": 2}, {"name": "Skimmed", "slug": "skimmed", "display_order": 3}, {"name": "Plant-Based Milk", "slug": "plant-based-milk", "display_order": 4}]},
            {"name": "Butter & Spreads", "slug": "butter-spreads", "display_order": 2, "children": []},
            {"name": "Cheese", "slug": "cheese", "display_order": 3, "children": [{"name": "Cheddar", "slug": "cheddar", "display_order": 1}, {"name": "Continental", "slug": "continental", "display_order": 2}, {"name": "Soft & Cream Cheese", "slug": "soft-cream-cheese", "display_order": 3}]},
            {"name": "Yoghurt", "slug": "yoghurt", "display_order": 4, "children": []},
            {"name": "Eggs", "slug": "eggs", "display_order": 5, "children": []},
            {"name": "Cream & Crème Fraîche", "slug": "cream-creme-fraiche", "display_order": 6, "children": []},
        ],
    },
    "frozen": {
        "pricing": {"default_markup_percent": "40.00", "rounding_strategy": "psychological", "minimum_margin_percent": "20.00", "max_discount_percent": "10.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 8, "track_expiry_by_default": True, "default_expiry_alert_days": 30, "default_pricing_mode": "fixed", "requires_temperature_checks": True, "temperature_min_celsius": "-25.00", "temperature_max_celsius": "-18.00"},
        "categories": [
            {"name": "Frozen Meals", "slug": "frozen-meals", "display_order": 1, "children": [{"name": "Ready Meals", "slug": "ready-meals", "display_order": 1}, {"name": "Pizza", "slug": "pizza", "display_order": 2}, {"name": "Pies & Pastries", "slug": "pies-pastries", "display_order": 3}]},
            {"name": "Frozen Meat & Fish", "slug": "frozen-meat-fish", "display_order": 2, "children": [{"name": "Meat", "slug": "meat", "display_order": 1}, {"name": "Fish & Seafood", "slug": "fish-seafood", "display_order": 2}, {"name": "Poultry", "slug": "poultry", "display_order": 3}]},
            {"name": "Frozen Vegetables", "slug": "frozen-vegetables", "display_order": 3, "children": []},
            {"name": "Ice Cream & Desserts", "slug": "ice-cream-desserts", "display_order": 4, "children": [{"name": "Ice Cream", "slug": "ice-cream", "display_order": 1}, {"name": "Frozen Desserts", "slug": "frozen-desserts", "display_order": 2}]},
        ],
    },
    "beverages": {
        "pricing": {"default_markup_percent": "50.00", "rounding_strategy": "psychological", "minimum_margin_percent": "25.00", "max_discount_percent": "10.00", "display_prices_inclusive_of_tax": True},
        "stock": {"default_low_stock_threshold": 24, "track_expiry_by_default": False, "default_expiry_alert_days": 90, "default_pricing_mode": "fixed", "requires_temperature_checks": False, "temperature_min_celsius": None, "temperature_max_celsius": None},
        "categories": [
            {"name": "Soft Drinks", "slug": "soft-drinks", "display_order": 1, "children": [{"name": "Fizzy Drinks", "slug": "fizzy-drinks", "display_order": 1}, {"name": "Juices & Smoothies", "slug": "juices-smoothies", "display_order": 2}, {"name": "Water", "slug": "water", "display_order": 3}, {"name": "Energy Drinks", "slug": "energy-drinks", "display_order": 4}]},
            {"name": "Alcohol", "slug": "alcohol", "display_order": 2, "children": [{"name": "Beer & Cider", "slug": "beer-cider", "display_order": 1}, {"name": "Wine", "slug": "wine", "display_order": 2}, {"name": "Spirits", "slug": "spirits", "display_order": 3}]},
            {"name": "Hot Drinks", "slug": "hot-drinks", "display_order": 3, "children": [{"name": "Tea", "slug": "tea", "display_order": 1}, {"name": "Coffee", "slug": "coffee", "display_order": 2}, {"name": "Hot Chocolate", "slug": "hot-chocolate", "display_order": 3}]},
            {"name": "Cordials & Squash", "slug": "cordials-squash", "display_order": 4, "children": []},
        ],
    },
}


def seed_departments(apps, schema_editor):
    Department = apps.get_model("departments", "Department")
    DepartmentPricingRule = apps.get_model("departments", "DepartmentPricingRule")
    DepartmentStockSettings = apps.get_model("departments", "DepartmentStockSettings")
    DepartmentCategory = apps.get_model("departments", "DepartmentCategory")

    for slug, config in DEPARTMENT_SEEDS.items():
        try:
            dept = Department.objects.get(slug=slug)
        except Department.DoesNotExist:
            continue

        DepartmentPricingRule.objects.update_or_create(department=dept, defaults=config["pricing"])
        DepartmentStockSettings.objects.update_or_create(department=dept, defaults=config["stock"])

        if DepartmentCategory.objects.filter(department=dept).exists():
            continue

        for cat_data in config["categories"]:
            children = cat_data.pop("children", [])
            parent = DepartmentCategory.objects.create(department=dept, parent=None, **cat_data)
            for child_data in children:
                DepartmentCategory.objects.create(department=dept, parent=parent, **child_data)


def reverse_seed(apps, schema_editor):
    apps.get_model("departments", "DepartmentPricingRule").objects.all().delete()
    apps.get_model("departments", "DepartmentStockSettings").objects.all().delete()
    apps.get_model("departments", "DepartmentCategory").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("departments", "0002_category_pricing_stock"),
    ]

    operations = [
        migrations.RunPython(seed_departments, reverse_code=reverse_seed),
    ]