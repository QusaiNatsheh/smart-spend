from django.contrib import admin

from .models import Category, CategoryBudget, ChatMessage, Expense, Income, UserProfile


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "icon", "user"]
    search_fields = ["name"]


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ["title", "amount", "category", "date", "user"]
    list_filter = ["date", "category"]
    search_fields = ["title", "notes"]


@admin.register(CategoryBudget)
class CategoryBudgetAdmin(admin.ModelAdmin):
    list_display = ["category", "monthly_limit", "user"]


@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ["source", "amount", "date", "user"]


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "monthly_income", "monthly_budget", "currency"]


admin.site.register(ChatMessage)
