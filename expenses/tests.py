"""Tests. AI providers are replaced with stubs, so no key, model or network is needed."""

import io
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import ai_utils, services
from .models import Category, CategoryBudget, ChatMessage, Expense, Income, UserProfile
from .money import format_money


class MoneyTests(TestCase):
    def test_usd_symbol_before_two_decimals(self):
        self.assertEqual(format_money(1234.5, "USD"), "$1,234.50")

    def test_jod_three_decimals_symbol_after(self):
        self.assertEqual(format_money(1234.5, "JOD"), "1,234.500 JD")

    def test_bad_input_falls_back_to_zero(self):
        self.assertEqual(format_money("not-a-number", "USD"), "$0.00")


class AuthedTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="a@b.com", email="a@b.com", password="pw12345x")
        UserProfile.objects.create(user=self.user, monthly_budget=Decimal("1000"), currency="USD")
        self.client.force_login(self.user)

    def expense(self, title="Lunch", amount="10", category=None, **kwargs):
        cat = Category.objects.get_or_create(user=self.user, name=category)[0] if category else None
        return Expense.objects.create(user=self.user, title=title, amount=Decimal(amount), category=cat, **kwargs)


class AuthTests(TestCase):
    def signup(self, password="Str0ng-pass-2026", email="new@x.com"):
        return self.client.post(
            reverse("signup"),
            {"email": email, "password": password, "confirm_password": password, "currency": "JOD"},
        )

    def test_signup_creates_user_and_profile(self):
        self.signup()
        user = User.objects.get(email="new@x.com")
        self.assertEqual(user.profile.currency, "JOD")

    def test_signup_rejects_weak_password(self):
        response = self.signup(password="123")
        self.assertFalse(User.objects.filter(email="new@x.com").exists())
        self.assertContains(response, "too short")

    def test_signup_rejects_invalid_email(self):
        self.signup(email="not-an-email")
        self.assertEqual(User.objects.count(), 0)

    def test_logout_requires_post(self):
        user = User.objects.create_user(username="u@x.com", email="u@x.com", password="pw12345x")
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)


class ExpenseViewTests(AuthedTestCase):
    def test_dashboard_ok(self):
        self.expense(category="Food")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_manual_add(self):
        self.client.post(
            reverse("add_expense"),
            {"title": "Taxi", "amount": "7.5", "category": "Transport", "date": "2026-01-15"},
        )
        exp = Expense.objects.get(title="Taxi")
        self.assertEqual(exp.amount, Decimal("7.50"))
        self.assertEqual(exp.date, date(2026, 1, 15))
        self.assertEqual(exp.category.user, self.user)

    def test_rejects_zero_negative_and_invalid_amounts(self):
        for amount in ("0", "-5", "abc", ""):
            self.client.post(reverse("add_expense"), {"title": "Bad", "amount": amount, "category": "X"})
        self.assertFalse(Expense.objects.filter(title="Bad").exists())

    def test_database_rejects_non_positive_amount(self):
        with self.assertRaises(IntegrityError):
            Expense.objects.create(user=self.user, title="Bad", amount=Decimal("-1"))

    def test_category_reused_case_insensitively(self):
        self.expense(category="Food")
        self.client.post(reverse("add_expense"), {"title": "Snack", "amount": "3", "category": "food"})
        self.assertEqual(Category.objects.filter(user=self.user).count(), 1)

    def test_edit_expense_updates_date_notes_and_user_scoped_category(self):
        exp = self.expense(category="Food")
        self.client.post(
            reverse("edit_expense", args=[exp.id]),
            {"title": "Dinner", "amount": "22", "category": "Dining", "date": "2026-02-01", "notes": "with team"},
        )
        exp.refresh_from_db()
        self.assertEqual((exp.title, exp.notes, exp.date), ("Dinner", "with team", date(2026, 2, 1)))
        self.assertEqual(exp.category.user, self.user)

    def test_edit_ignores_offsite_next(self):
        exp = self.expense()
        response = self.client.get(reverse("edit_expense", args=[exp.id]) + "?next=https://evil.example/")
        self.assertNotContains(response, "evil.example")
        response = self.client.post(
            reverse("edit_expense", args=[exp.id]),
            {"title": "X", "amount": "1", "category": "Y", "next": "https://evil.example/"},
        )
        self.assertEqual(response.url, reverse("all_transactions"))

    def test_delete_expense(self):
        exp = self.expense()
        self.client.post(reverse("delete_expense", args=[exp.id]))
        self.assertFalse(Expense.objects.filter(id=exp.id).exists())

    def test_cannot_edit_or_delete_other_users_expense(self):
        other = User.objects.create_user(username="c@d.com", password="pw12345x")
        exp = Expense.objects.create(user=other, title="Secret", amount=Decimal("9"))
        self.assertEqual(self.client.get(reverse("edit_expense", args=[exp.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete_expense", args=[exp.id])).status_code, 404)
        self.assertTrue(Expense.objects.filter(id=exp.id).exists())


class TransactionsTests(AuthedTestCase):
    def setUp(self):
        super().setUp()
        self.expense("Coffee", "3", "Dining", date=date(2026, 3, 2), notes="morning")
        self.expense("Uber", "9", "Transport", date=date(2026, 3, 10))
        self.expense("Rent", "1200", "Housing", date=date(2026, 4, 1))

    def titles(self, **params):
        response = self.client.get(reverse("all_transactions"), params)
        return {e.title for e in response.context["page"]}

    def test_search_title_and_notes(self):
        self.assertEqual(self.titles(q="uber"), {"Uber"})
        self.assertEqual(self.titles(q="morning"), {"Coffee"})

    def test_category_and_date_filters(self):
        transport = Category.objects.get(user=self.user, name="Transport")
        self.assertEqual(self.titles(category=transport.id), {"Uber"})
        self.assertEqual(self.titles(start="2026-03-05", end="2026-03-31"), {"Uber"})

    def test_filtered_total_and_export(self):
        response = self.client.get(reverse("all_transactions"), {"start": "2026-03-01", "end": "2026-03-31"})
        self.assertEqual(response.context["filtered_total"], Decimal("12"))
        csv_text = self.client.get(reverse("export_csv"), {"q": "rent"}).content.decode()
        self.assertIn("Rent", csv_text)
        self.assertNotIn("Coffee", csv_text)

    def test_pagination(self):
        for i in range(30):
            self.expense(f"Item {i}", "1")
        response = self.client.get(reverse("all_transactions"), {"page": 2})
        self.assertEqual(response.context["page"].number, 2)
        self.assertEqual(len(response.context["page"]), 8)


class IncomeTests(AuthedTestCase):
    def test_add_edit_delete_income(self):
        self.client.post(reverse("add_income"), {"source": "Salary", "amount": "5000", "date": "2026-05-01"})
        income = Income.objects.get(user=self.user)
        self.client.post(
            reverse("edit_income", args=[income.id]), {"source": "Pay", "amount": "5100", "date": "2026-05-02"}
        )
        income.refresh_from_db()
        self.assertEqual((income.source, income.amount), ("Pay", Decimal("5100.00")))
        self.client.post(reverse("delete_income", args=[income.id]))
        self.assertFalse(Income.objects.exists())

    def test_report_for_selected_month(self):
        self.expense("Old", "50", "Food", date=date(2026, 1, 10))
        Income.objects.create(user=self.user, source="Salary", amount=Decimal("200"), date=date(2026, 1, 1))
        response = self.client.get(reverse("monthly_report"), {"month": "2026-01"})
        self.assertEqual(response.context["total_expense"], 50)
        self.assertEqual(response.context["savings_rate"], 75)

    def test_cannot_touch_other_users_income(self):
        other = User.objects.create_user(username="c@d.com", password="pw12345x")
        income = Income.objects.create(user=other, source="X", amount=Decimal("1"))
        self.assertEqual(self.client.post(reverse("delete_income", args=[income.id])).status_code, 404)


class CsvImportTests(AuthedTestCase):
    def upload(self, text):
        return self.client.post(
            reverse("import_csv"), {"csv_file": SimpleUploadedFile("e.csv", text.encode(), content_type="text/csv")}
        )

    def test_valid_file_imports_all_rows(self):
        self.upload("date,title,amount,category,notes\n2026-01-02,Bread,2.5,Food,\n2026-01-03,Bus,1,Transport,x\n")
        self.assertEqual(Expense.objects.filter(user=self.user).count(), 2)

    def test_one_bad_row_imports_nothing_and_reports_line(self):
        response = self.upload("date,title,amount,category\n2026-01-02,Bread,2.5,Food\n2026-13-40,Bus,-1,Transport\n")
        self.assertEqual(Expense.objects.count(), 0)
        self.assertContains(response, "Line 3")
        self.assertContains(response, "not a positive number")

    def test_missing_column_reported(self):
        response = self.upload("date,title,category\n2026-01-02,Bread,Food\n")
        self.assertContains(response, "Missing column")

    def test_export_round_trip(self):
        self.expense("Coffee", "3.50", "Dining", notes="oat milk")
        exported = self.client.get(reverse("export_csv")).content.decode()
        Expense.objects.all().delete()
        self.upload(exported)
        exp = Expense.objects.get()
        self.assertEqual((exp.title, exp.amount, exp.notes), ("Coffee", Decimal("3.50"), "oat milk"))


class ServiceTests(AuthedTestCase):
    def test_anomaly_detection_flags_outlier(self):
        for _ in range(6):
            self.expense("Cafe", "10", "Dining")
        self.expense("Feast", "300", "Dining")
        anomalies = services.detect_anomalies(self.user)
        self.assertTrue(any(a.expense.title == "Feast" for a in anomalies))

    def test_anomaly_compares_merchant_with_its_own_history(self):
        for amount in ("8", "10", "12", "9", "11"):
            self.expense("Uber", amount, "Transport")
        for amount in ("40", "42", "38", "41"):
            self.expense("Fuel", amount, "Transport")
        self.expense("Fuel", "44", "Transport")
        self.expense("Uber", "95", "Transport")
        flagged = {(a.expense.title, a.baseline) for a in services.detect_anomalies(self.user)}
        self.assertEqual(flagged, {("Uber", "Uber")})

    def test_monthly_recurring_detected_with_cadence(self):
        today = timezone.localdate()
        for i in range(4):
            self.expense("Netflix", "12", "Entertainment", date=today - timedelta(days=30 * i))
        recurring = services.detect_recurring(self.user)
        self.assertEqual([(r.title, r.cadence) for r in recurring], [("Netflix", "monthly")])
        self.assertEqual(recurring[0].next_expected, services.add_months(today, 1))

    def test_add_months_clamps_to_month_end(self):
        self.assertEqual(services.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(services.add_months(date(2026, 12, 1), 1), date(2027, 1, 1))

    def test_frequent_irregular_spend_is_not_recurring(self):
        today = timezone.localdate()
        for days_ago in (0, 1, 3, 4, 9):
            self.expense("Coffee", "4", "Dining", date=today - timedelta(days=days_ago))
        self.assertEqual(services.detect_recurring(self.user), [])

    def test_weekly_monthly_estimate(self):
        today = timezone.localdate()
        for i in range(4):
            self.expense("Cleaner", "20", "Home", date=today - timedelta(days=7 * i))
        (group,) = services.detect_recurring(self.user)
        self.assertEqual(group.cadence, "weekly")
        self.assertAlmostEqual(group.monthly_estimate, 20 * 30.4 / 7, places=2)

    def test_monthly_trend_shape_and_totals(self):
        self.expense("Now", "40")
        trend = services.monthly_trend(self.user, months=6)
        self.assertEqual(len(trend["labels"]), 6)
        self.assertEqual(trend["data"][-1], 40.0)

    def test_category_budget_status(self):
        self.expense("Dinner", "90", "Dining")
        CategoryBudget.objects.create(
            user=self.user, category=Category.objects.get(name="Dining"), monthly_limit=Decimal("100")
        )
        (status,) = services.category_budget_status(self.user)
        self.assertTrue(status["warning"])
        self.assertFalse(status["over"])


class ForecastTests(TestCase):
    def test_projection_and_safe_daily(self):
        f = ai_utils.forecast_numbers(spent=300, budget=1000, today=date(2026, 4, 10))
        self.assertEqual(f["days"], 30)
        self.assertAlmostEqual(f["projected"], 900)
        self.assertAlmostEqual(f["safe_daily"], 35)
        self.assertFalse(f["over"])

    def test_last_day_has_no_division_error(self):
        f = ai_utils.forecast_numbers(spent=300, budget=100, today=date(2026, 4, 30))
        self.assertEqual(f["remaining"], 0)
        self.assertTrue(f["over"])


@override_settings(AI_PROVIDER="ollama", OLLAMA_URL="http://ollama.test")
class AiTests(AuthedTestCase):
    def reply(self, value):
        text = json.dumps(value) if isinstance(value, dict) else value
        return mock.patch.object(ai_utils, "_generate", return_value=text)

    def test_provider_selection(self):
        with override_settings(AI_PROVIDER="auto", GEMINI_API_KEY="", OLLAMA_URL=""):
            self.assertEqual(ai_utils.provider(), "none")
        with override_settings(AI_PROVIDER="auto", GEMINI_API_KEY="k", OLLAMA_URL="http://x"):
            self.assertEqual(ai_utils.provider(), "gemini")
        with override_settings(AI_PROVIDER="auto", GEMINI_API_KEY="", OLLAMA_URL="http://x"):
            self.assertEqual(ai_utils.provider(), "ollama")

    def test_natural_language_add_uses_ai_fields(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        reply = {"title": "Lunch", "amount": 18, "category": "Dining", "date": yesterday.isoformat()}
        with self.reply(reply):
            self.client.post(reverse("smart_add_expense"), {"expense_text": "paid 18 for lunch yesterday"})
        exp = Expense.objects.get()
        self.assertEqual((exp.title, exp.amount, exp.date), ("Lunch", Decimal("18.00"), yesterday))

    def test_ai_negative_amount_or_bad_json_creates_nothing(self):
        with self.reply({"title": "X", "amount": -5, "category": "Y"}):
            self.client.post(reverse("smart_add_expense"), {"expense_text": "refund"})
        with self.reply("not json"):
            self.client.post(reverse("smart_add_expense"), {"expense_text": "??"})
        self.assertFalse(Expense.objects.exists())

    def test_ai_future_date_is_clamped_to_today(self):
        with self.reply({"title": "X", "amount": 5, "category": "Y", "date": "2099-01-01"}):
            self.client.post(reverse("smart_add_expense"), {"expense_text": "x"})
        self.assertEqual(Expense.objects.get().date, timezone.localdate())

    def test_receipt_scan(self):
        buffer = io.BytesIO()
        Image.new("RGB", (40, 60), "white").save(buffer, format="PNG")
        upload = SimpleUploadedFile("r.png", buffer.getvalue(), content_type="image/png")
        with self.reply({"title": "Carrefour", "amount": 42.75, "category": "Groceries"}) as stub:
            self.client.post(reverse("smart_add_receipt"), {"receipt_image": upload})
        self.assertEqual(Expense.objects.get().amount, Decimal("42.75"))
        self.assertIsNotNone(stub.call_args.kwargs["image"])

    def test_receipt_rejects_non_image(self):
        upload = SimpleUploadedFile("r.png", b"not an image", content_type="image/png")
        with self.reply({"title": "X", "amount": 1, "category": "Y"}) as stub:
            self.client.post(reverse("smart_add_receipt"), {"receipt_image": upload})
        stub.assert_not_called()
        self.assertFalse(Expense.objects.exists())

    def test_advice_uses_this_month_not_all_time(self):
        self.expense("Old", "5000", "Housing", date=timezone.localdate() - timedelta(days=200))
        self.expense("Now", "120", "Dining")
        with self.reply("Cut dining.") as stub:
            self.client.post(reverse("ai_insights"))
        prompt = stub.call_args.args[0]
        self.assertIn("Spent this month so far: $120.00", prompt)
        self.assertIn("1. Dining $120.00 (100%)", prompt)

    def test_chat_saves_both_messages(self):
        with self.reply("You spent most on Dining."):
            response = self.client.post(
                reverse("finance_chat"), {"question": "Where did it go?"}, content_type="application/json"
            )
        self.assertEqual(response.json()["answer"], "You spent most on Dining.")
        self.assertEqual(ChatMessage.objects.filter(user=self.user).count(), 2)

    def test_ai_off_shows_message_and_forecast_still_works(self):
        with override_settings(AI_PROVIDER="none"):
            response = self.client.post(reverse("smart_add_expense"), {"expense_text": "x"}, follow=True)
            self.assertContains(response, "AI is off")
            self.expense("Now", "100")
            response = self.client.post(reverse("budget_forecast"), follow=True)
            self.assertContains(response, "At your current pace")

    def test_ollama_request_shape(self):
        captured = {}

        class FakeResponse(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data)
            return FakeResponse(
                json.dumps({"message": {"content": '{"title":"A","amount":1,"category":"B"}'}}).encode()
            )

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            result = ai_utils.parse_expense_text("a for 1")
        self.assertEqual(result["title"], "A")
        self.assertEqual(captured["body"]["format"], ai_utils.EXPENSE_SCHEMA)
        self.assertFalse(captured["body"]["stream"])


class SeedTests(TestCase):
    def test_seed_demo_builds_insights(self):
        call_command("seed_demo", stdout=io.StringIO())
        user = User.objects.get(email="demo@smartspend.app")
        titles = {r.title for r in services.detect_recurring(user)}
        self.assertTrue({"Rent", "Netflix", "Internet"} <= titles)
        self.assertTrue(services.detect_anomalies(user))
