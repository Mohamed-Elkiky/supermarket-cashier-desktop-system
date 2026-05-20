from django.contrib import admin
from .models import Department, DepartmentCategory, DepartmentPricingRule, DepartmentStockSettings


class DepartmentCategoryInline(admin.TabularInline):
    model = DepartmentCategory
    extra = 0
    fields = ["name", "slug", "parent", "display_order", "is_active"]
    readonly_fields = ["slug"]
    fk_name = "department"


class DepartmentPricingRuleInline(admin.StackedInline):
    model = DepartmentPricingRule
    extra = 0
    can_delete = False


class DepartmentStockSettingsInline(admin.StackedInline):
    model = DepartmentStockSettings
    extra = 0
    can_delete = False


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "tax_rate", "is_active", "display_order", "updated_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    ordering = ["display_order", "name"]
    inlines = [DepartmentPricingRuleInline, DepartmentStockSettingsInline, DepartmentCategoryInline]


@admin.register(DepartmentCategory)
class DepartmentCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "department", "parent", "display_order", "is_active"]
    list_filter = ["department", "is_active"]
    search_fields = ["name", "department__name"]
    ordering = ["department", "display_order", "name"]