import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from django.db import transaction
from django.utils.text import slugify

from .models import Department, DepartmentCategory, DepartmentPricingRule, DepartmentStockSettings

logger = logging.getLogger("apps.departments")


def apply_rounding(price_pence: int, strategy: str) -> int:
    if strategy == "nearest_penny":
        return price_pence
    if strategy == "nearest_5p":
        return int(round(price_pence / 5) * 5)
    if strategy == "nearest_10p":
        return int(round(price_pence / 10) * 10)
    if strategy == "psychological":
        pounds = round(price_pence / 100)
        if pounds == 0:
            return 99
        return (pounds * 100) - 1
    logger.warning("Unknown rounding strategy '%s' — falling back to nearest_penny", strategy)
    return price_pence


def calculate_sell_price(cost_price_pence: int, pricing_rule: DepartmentPricingRule) -> int:
    if cost_price_pence <= 0:
        raise ValueError("Cost price must be greater than zero.")
    markup = Decimal(str(pricing_rule.default_markup_percent)) / 100
    raw_sell = Decimal(cost_price_pence) * (1 + markup)
    raw_pence = int(raw_sell.to_integral_value(rounding=ROUND_HALF_UP))
    sell_pence = apply_rounding(raw_pence, pricing_rule.rounding_strategy)
    if pricing_rule.minimum_margin_percent > 0 and sell_pence > 0:
        actual_margin = ((sell_pence - cost_price_pence) / sell_pence) * 100
        if actual_margin < float(pricing_rule.minimum_margin_percent):
            raise ValueError(
                f"Calculated sell price {sell_pence}p yields a margin of "
                f"{actual_margin:.1f}%, which is below the department minimum of "
                f"{pricing_rule.minimum_margin_percent}%."
            )
    return sell_pence


def validate_discount(discount_percent: Decimal, pricing_rule: DepartmentPricingRule) -> bool:
    return discount_percent <= pricing_rule.max_discount_percent


@transaction.atomic
def create_department(*, name: str, tax_rate=Decimal("0"), display_order: int = 0,
                      pricing_rule_data: Optional[dict] = None,
                      stock_settings_data: Optional[dict] = None) -> Department:
    slug = slugify(name)
    if Department.objects.filter(slug=slug).exists():
        raise ValueError(f"A department with the slug '{slug}' already exists.")
    dept = Department.objects.create(name=name, slug=slug, tax_rate=tax_rate, display_order=display_order)
    pricing_defaults = {"default_markup_percent": Decimal("30.00"), "rounding_strategy": "nearest_penny", "minimum_margin_percent": Decimal("0.00"), "max_discount_percent": Decimal("10.00"), "display_prices_inclusive_of_tax": True}
    if pricing_rule_data:
        pricing_defaults.update(pricing_rule_data)
    DepartmentPricingRule.objects.create(department=dept, **pricing_defaults)
    stock_defaults = {"default_low_stock_threshold": 5, "track_expiry_by_default": False, "default_expiry_alert_days": 3, "default_pricing_mode": "fixed", "requires_temperature_checks": False}
    if stock_settings_data:
        stock_defaults.update(stock_settings_data)
    DepartmentStockSettings.objects.create(department=dept, **stock_defaults)
    logger.info("Created department '%s' (slug=%s)", dept.name, dept.slug)
    return dept


@transaction.atomic
def update_department(dept: Department, validated_data: dict) -> Department:
    for attr, value in validated_data.items():
        setattr(dept, attr, value)
    dept.full_clean()
    dept.save()
    return dept


@transaction.atomic
def update_pricing_rule(rule: DepartmentPricingRule, validated_data: dict) -> DepartmentPricingRule:
    for attr, value in validated_data.items():
        setattr(rule, attr, value)
    rule.full_clean()
    rule.save()
    logger.info("Updated pricing rule for department '%s'", rule.department.name)
    return rule


@transaction.atomic
def update_stock_settings(settings: DepartmentStockSettings, validated_data: dict) -> DepartmentStockSettings:
    for attr, value in validated_data.items():
        setattr(settings, attr, value)
    settings.full_clean()
    settings.save()
    logger.info("Updated stock settings for department '%s'", settings.department.name)
    return settings


def get_category_tree(department: Department) -> list:
    roots = (
        DepartmentCategory.objects.filter(department=department, parent=None)
        .prefetch_related("children")
        .order_by("display_order", "name")
    )
    tree = []
    for root in roots:
        node = {
            "id": root.id, "name": root.name, "slug": root.slug,
            "display_order": root.display_order, "is_active": root.is_active,
            "children": [
                {"id": child.id, "name": child.name, "slug": child.slug,
                 "display_order": child.display_order, "is_active": child.is_active}
                for child in root.children.filter(is_active=True).order_by("display_order", "name")
            ],
        }
        tree.append(node)
    return tree


@transaction.atomic
def create_category(*, department: Department, name: str,
                    parent_id: Optional[int] = None, display_order: int = 0) -> DepartmentCategory:
    slug = slugify(name)
    parent = None
    if parent_id is not None:
        try:
            parent = DepartmentCategory.objects.get(pk=parent_id, department=department)
        except DepartmentCategory.DoesNotExist:
            raise ValueError(f"Parent category {parent_id} does not exist in department '{department.name}'.")
        if parent.parent_id is not None:
            raise ValueError("Cannot create a category under a level-2 category. Maximum category depth is two levels.")
    if DepartmentCategory.objects.filter(department=department, parent=parent, slug=slug).exists():
        raise ValueError(f"A category with slug '{slug}' already exists at this level in '{department.name}'.")
    category = DepartmentCategory.objects.create(department=department, parent=parent, name=name, slug=slug, display_order=display_order)
    logger.info("Created category '%s' in department '%s' (parent=%s)", name, department.name, parent.name if parent else None)
    return category


@transaction.atomic
def update_category(category: DepartmentCategory, validated_data: dict) -> DepartmentCategory:
    validated_data.pop("department", None)
    validated_data.pop("parent", None)
    for attr, value in validated_data.items():
        setattr(category, attr, value)
    category.full_clean()
    category.save()
    return category


@transaction.atomic
def delete_category(category: DepartmentCategory) -> None:
    if category.parent is None:
        category.children.all().update(is_active=False)
    category.is_active = False
    category.save(update_fields=["is_active", "updated_at"])
    logger.info("Deactivated category '%s' (id=%s)", category.name, category.pk)