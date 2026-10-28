from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

POSITIVE = [MinValueValidator(Decimal("0.01"))]

CURRENCY_CHOICES = [
    ("USD", "US Dollar ($)"),
    ("JOD", "Jordanian Dinar (JD)"),
    ("SAR", "Saudi Riyal (SR)"),
]


class Category(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=10, blank=True)

    class Meta:
        verbose_name_plural = "Categories"
        constraints = [models.UniqueConstraint(fields=["user", "name"], name="unique_category_per_user")]

    def __str__(self):
        return f"{self.icon} {self.name}".strip()


class Expense(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="expenses")
    title = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=POSITIVE)
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["user", "date"])]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="expense_amount_positive")]

    def __str__(self):
        return f"{self.title} - {self.amount}"


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    monthly_income = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monthly_budget = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default=settings.DEFAULT_CURRENCY)

    def __str__(self):
        return f"{self.user.username}'s profile"


class CategoryBudget(models.Model):
    """A monthly spending limit for one category."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="category_budgets")
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="budgets")
    monthly_limit = models.DecimalField(max_digits=10, decimal_places=2, validators=POSITIVE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "category"], name="unique_budget_per_category")]

    def __str__(self):
        return f"{self.category.name}: {self.monthly_limit}"


class Income(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="incomes")
    source = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=POSITIVE)
    date = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["user", "date"])]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="income_amount_positive")]

    def __str__(self):
        return f"{self.source} - {self.amount}"


class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_messages")
    message = models.TextField()
    is_user = models.BooleanField(default=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]

    def __str__(self):
        sender = "User" if self.is_user else "AI"
        return f"{sender}: {self.message[:30]}"
