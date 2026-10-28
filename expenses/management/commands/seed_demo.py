"""Populate a demo account so the app shows something real on first run.

    python manage.py seed_demo

Creates (or resets) demo@smartspend.app / demo1234 with 6 months of
expenses, income, category budgets, monthly bills and a couple of deliberate
anomalies, so the Insights page has something to detect.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from expenses.models import Category, CategoryBudget, Expense, Income, UserProfile

DEMO_EMAIL = "demo@smartspend.app"
DEMO_PASSWORD = "demo1234"

CATALOG = {
    "Groceries": [("Carrefour", 40, 85), ("Cozmo", 25, 60)],
    "Transport": [("Uber", 6, 18), ("Careem", 5, 16), ("Fuel", 30, 45)],
    "Dining": [("Cafe", 5, 14), ("Restaurant", 18, 40)],
    "Utilities": [("Electricity", 45, 70), ("Water", 12, 20)],
    "Entertainment": [("Cinema", 9, 22), ("Books", 8, 25)],
}

# (title, category, amount, day of month): paid every month, so recurring detection finds them.
MONTHLY_BILLS = [
    ("Rent", "Housing", 1200, 1),
    ("Internet", "Utilities", 30, 5),
    ("Mobile plan", "Utilities", 18, 9),
    ("Gym membership", "Health", 35, 3),
    ("Netflix", "Entertainment", 12, 14),
    ("Spotify", "Entertainment", 6, 20),
]


class Command(BaseCommand):
    help = "Seed a demo account with realistic finance data."

    def handle(self, *args, **options):
        User.objects.filter(username=DEMO_EMAIL).delete()
        user = User.objects.create_user(username=DEMO_EMAIL, email=DEMO_EMAIL, password=DEMO_PASSWORD)
        UserProfile.objects.create(
            user=user, monthly_income=Decimal("6000"), monthly_budget=Decimal("4000"), currency="USD"
        )

        names = set(CATALOG) | {bill[1] for bill in MONTHLY_BILLS}
        categories = {name: Category.objects.create(user=user, name=name) for name in sorted(names)}
        today = timezone.localdate()
        rng = random.Random(42)

        for months_ago in range(6):
            month = (today.replace(day=1) - timedelta(days=months_ago * 30)).replace(day=1)
            for title, cat_name, amount, day in MONTHLY_BILLS:
                bill_date = month.replace(day=day)
                if bill_date <= today:
                    Expense.objects.create(
                        user=user, title=title, amount=Decimal(amount), category=categories[cat_name], date=bill_date
                    )
            salary_date = month.replace(day=1)
            Income.objects.create(user=user, source="Salary", amount=Decimal("6000"), date=salary_date)
            if months_ago % 2 == 0:
                Income.objects.create(
                    user=user,
                    source="Freelance project",
                    amount=Decimal(rng.randint(400, 900)),
                    date=month.replace(day=min(18, today.day) if months_ago == 0 else 18),
                )

        for days_ago in range(0, 182):
            day = today - timedelta(days=days_ago)
            for _ in range(rng.randint(0, 3)):
                cat_name = rng.choice(list(CATALOG))
                merchant, low, high = rng.choice(CATALOG[cat_name])
                amount = Decimal(str(rng.randint(low, high)))
                Expense.objects.create(
                    user=user,
                    title=merchant,
                    amount=amount,
                    category=categories[cat_name],
                    date=day,
                )

        # A couple of deliberate anomalies for the radar to catch.
        Expense.objects.create(
            user=user,
            title="Restaurant",
            amount=Decimal("320"),
            category=categories["Dining"],
            date=today - timedelta(days=min(5, today.day - 1)),
            notes="Team dinner",
        )
        Expense.objects.create(
            user=user,
            title="Carrefour",
            amount=Decimal("410"),
            category=categories["Groceries"],
            date=today - timedelta(days=min(2, today.day - 1)),
            notes="Monthly stock-up",
        )

        CategoryBudget.objects.create(user=user, category=categories["Dining"], monthly_limit=Decimal("250"))
        CategoryBudget.objects.create(user=user, category=categories["Groceries"], monthly_limit=Decimal("600"))

        count = Expense.objects.filter(user=user).count()
        self.stdout.write(self.style.SUCCESS(f"Seeded {DEMO_EMAIL} (password: {DEMO_PASSWORD}) with {count} expenses."))
