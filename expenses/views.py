import csv
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import ai_utils, services
from .models import (
    CURRENCY_CHOICES,
    Category,
    CategoryBudget,
    ChatMessage,
    Expense,
    Income,
    UserProfile,
)
from .money import currency_symbol, format_money

MAX_AMOUNT = Decimal("99999999.99")


def _profile(user) -> UserProfile:
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _get_or_create_category(user, name: str) -> Category:
    name = (name or "Uncategorized").strip()[:100] or "Uncategorized"
    category = Category.objects.filter(user=user, name__iexact=name).first()
    return category or Category.objects.create(user=user, name=name)


def _amount(value) -> Decimal | None:
    """A positive amount with two decimals, or None when the value is missing, invalid, zero or negative."""
    try:
        amount = Decimal(str(value).strip().replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return amount if Decimal("0") < amount <= MAX_AMOUNT else None


def _amount_or_zero(value) -> Decimal | None:
    """Like _amount, but an empty field or 0 means zero (used for optional budget and income settings)."""
    if str(value or "").strip() in {"", "0"}:
        return Decimal("0")
    return _amount(value)


def _date(value, default: date | None = None) -> date | None:
    try:
        return date.fromisoformat(str(value).strip()[:10]) if value else default
    except ValueError:
        return None


def _category_names(user) -> list[str]:
    return list(Category.objects.filter(user=user).order_by("name").values_list("name", flat=True))


def _local_url(request, name: str) -> str:
    """A same-site URL from POST or GET, or "" when it is missing or points elsewhere."""
    target = request.POST.get(name) or request.GET.get(name) or ""
    ok = url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return target if ok else ""


def _safe_next(request, fallback: str):
    return redirect(_local_url(request, "next") or fallback)


def _ai_context(user, profile: UserProfile) -> dict:
    month = services.month_context(user)
    forecast = ai_utils.forecast_numbers(month["spent"], float(profile.monthly_budget))
    total_income = float(Income.objects.filter(user=user).aggregate(s=Sum("amount"))["s"] or 0)
    total_spent = float(Expense.objects.filter(user=user).aggregate(s=Sum("amount"))["s"] or 0)
    return {
        **month,
        "income": float(profile.monthly_income),
        "budget": float(profile.monthly_budget),
        "day": forecast["day"],
        "days": forecast["days"],
        "balance": total_income - total_spent,
    }


# --- Public -----------------------------------------------------------------


def home_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "expenses/home.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        user_obj = User.objects.filter(email__iexact=email).first()
        user = authenticate(request, username=user_obj.username, password=password) if user_obj else None
        if user is not None:
            login(request, user)
            return redirect("dashboard")
        messages.error(request, "That email or password is not right. Try again.")
    return render(request, "expenses/login.html")


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        confirm = request.POST.get("confirm_password", "")
        currency = request.POST.get("currency", settings.DEFAULT_CURRENCY)
        income = _amount(request.POST.get("income")) or Decimal("0")
        budget = _amount(request.POST.get("budget")) or Decimal("0")

        errors = []
        try:
            validate_email(email)
        except ValidationError:
            errors.append("Enter a valid email address.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if User.objects.filter(email__iexact=email).exists():
            errors.append("That email is already in use.")
        if not errors:
            try:
                validate_password(password, User(username=email, email=email))
            except ValidationError as e:
                errors.extend(e.messages)
        if currency not in dict(CURRENCY_CHOICES):
            currency = settings.DEFAULT_CURRENCY

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            user = User.objects.create_user(username=email, email=email, password=password)
            UserProfile.objects.create(user=user, monthly_income=income, monthly_budget=budget, currency=currency)
            login(request, user)
            return redirect("dashboard")
    return render(request, "expenses/signup.html")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


# --- Dashboard --------------------------------------------------------------


@login_required
def dashboard(request):
    user = request.user
    profile = _profile(user)
    start, next_start = services.month_bounds()

    month_expenses = Expense.objects.filter(user=user, date__gte=start, date__lt=next_start)
    month_spent = float(month_expenses.aggregate(s=Sum("amount"))["s"] or 0)
    month_income = float(
        Income.objects.filter(user=user, date__gte=start, date__lt=next_start).aggregate(s=Sum("amount"))["s"] or 0
    )

    all_income = float(Income.objects.filter(user=user).aggregate(s=Sum("amount"))["s"] or 0)
    all_spent = float(Expense.objects.filter(user=user).aggregate(s=Sum("amount"))["s"] or 0)
    total_balance = all_income - all_spent

    budget = float(profile.monthly_budget)
    budget_pct = round((month_spent / budget) * 100) if budget > 0 else 0
    forecast = ai_utils.forecast_numbers(month_spent, budget)

    category_rows = month_expenses.values("category__name").annotate(total=Sum("amount")).order_by("-total")
    chart_labels = [r["category__name"] or "Uncategorized" for r in category_rows]
    chart_data = [round(float(r["total"]), 2) for r in category_rows]

    trend = services.monthly_trend(user, months=6)

    context = {
        "recent_expenses": Expense.objects.filter(user=user).select_related("category")[:6],
        "month_spent": month_spent,
        "month_income": month_income,
        "total_balance": total_balance,
        "budget": budget,
        "budget_pct": budget_pct,
        "budget_over": budget > 0 and month_spent > budget,
        "forecast": forecast,
        "anomaly_count": len(services.detect_anomalies(user)),
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
        "trend_labels": json.dumps(trend["labels"]),
        "trend_data": json.dumps(trend["data"]),
        "chat_messages": ChatMessage.objects.filter(user=user).order_by("-timestamp")[:20][::-1],
        "categories": _category_names(user),
        "today": timezone.localdate(),
        "currency": profile.currency,
        "ai_label": ai_utils.provider_label(),
        "ai_on": ai_utils.provider() != "none",
    }
    return render(request, "expenses/dashboard.html", context)


# --- Expense CRUD -----------------------------------------------------------


@login_required
@require_POST
def add_expense(request):
    """Manual add: works with or without AI."""
    title = request.POST.get("title", "").strip()[:255]
    amount = _amount(request.POST.get("amount"))
    spent_on = _date(request.POST.get("date"), timezone.localdate())
    if not title or amount is None or spent_on is None:
        messages.error(request, "Enter a description, a positive amount and a valid date.")
        return _safe_next(request, "dashboard")
    Expense.objects.create(
        user=request.user,
        title=title,
        amount=amount,
        date=spent_on,
        notes=request.POST.get("notes", "").strip(),
        category=_get_or_create_category(request.user, request.POST.get("category")),
    )
    messages.success(request, f"Added {title}.")
    return _safe_next(request, "dashboard")


def _create_from_ai(request, data, fallback_title: str) -> Expense | None:
    if not isinstance(data, dict):
        return None
    amount = _amount(data.get("amount"))
    if amount is None:
        return None
    spent_on = _date(data.get("date"), timezone.localdate()) or timezone.localdate()
    if spent_on > timezone.localdate():
        spent_on = timezone.localdate()
    return Expense.objects.create(
        user=request.user,
        title=(str(data.get("title") or "").strip() or fallback_title)[:255],
        amount=amount,
        date=spent_on,
        category=_get_or_create_category(request.user, data.get("category")),
    )


@login_required
@require_POST
def smart_add_expense(request):
    text = request.POST.get("expense_text", "").strip()[:300]
    if ai_utils.provider() == "none":
        messages.error(request, ai_utils.NO_AI)
        return redirect("dashboard")
    data = ai_utils.parse_expense_text(text, _category_names(request.user)) if text else None
    expense = _create_from_ai(request, data, text[:60])
    if expense:
        money = format_money(expense.amount, _profile(request.user).currency)
        messages.success(request, f"Added {expense.title}: {money} in {expense.category.name}.")
    else:
        messages.error(request, "Could not read that. Try 'Paid 20 for lunch' or use the manual form.")
    return redirect("dashboard")


@login_required
@require_POST
def smart_add_receipt(request):
    upload = request.FILES.get("receipt_image")
    if upload is None:
        messages.error(request, "Choose a receipt photo first.")
        return redirect("dashboard")
    if upload.size > settings.RECEIPT_MAX_BYTES:
        messages.error(request, "That image is too large. The limit is 5 MB.")
        return redirect("dashboard")
    try:
        from PIL import Image

        image = Image.open(upload)
        image.verify()
        upload.seek(0)
        image = Image.open(upload).convert("RGB")
        image.thumbnail((1600, 1600))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88)
    except Exception:
        messages.error(request, "That file is not a readable image.")
        return redirect("dashboard")
    if ai_utils.provider() == "none":
        messages.error(request, ai_utils.NO_AI)
        return redirect("dashboard")
    data = ai_utils.parse_receipt_image(buffer.getvalue(), _category_names(request.user))
    expense = _create_from_ai(request, data, "Receipt")
    if expense:
        money = format_money(expense.amount, _profile(request.user).currency)
        messages.success(request, f"Scanned {money} for {expense.title}.")
    else:
        messages.error(request, "Couldn't read that receipt. Try a clearer photo.")
    return redirect("dashboard")


@login_required
@require_POST
def delete_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id, user=request.user)
    expense.delete()
    messages.success(request, "Expense deleted.")
    return _safe_next(request, "dashboard")


@login_required
def edit_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id, user=request.user)
    if request.method == "POST":
        title = request.POST.get("title", "").strip()[:255]
        amount = _amount(request.POST.get("amount"))
        spent_on = _date(request.POST.get("date"), expense.date)
        if not title or amount is None or spent_on is None:
            messages.error(request, "Enter a description, a positive amount and a valid date.")
            return render(
                request,
                "expenses/edit_expense.html",
                {"expense": expense, "categories": _category_names(request.user), "next": _local_url(request, "next")},
            )
        expense.title = title
        expense.amount = amount
        expense.date = spent_on
        expense.notes = request.POST.get("notes", "").strip()
        expense.category = _get_or_create_category(request.user, request.POST.get("category"))
        expense.save()
        messages.success(request, "Expense updated.")
        return _safe_next(request, "all_transactions")
    return render(
        request,
        "expenses/edit_expense.html",
        {"expense": expense, "categories": _category_names(request.user), "next": _local_url(request, "next")},
    )


def _filtered_expenses(request):
    """Expenses for the transactions page and CSV export, filtered by the query string."""
    expenses = Expense.objects.filter(user=request.user).select_related("category")
    filters = {
        "q": request.GET.get("q", "").strip(),
        "category": request.GET.get("category", ""),
        "start": _date(request.GET.get("start")),
        "end": _date(request.GET.get("end")),
    }
    if filters["q"]:
        expenses = expenses.filter(Q(title__icontains=filters["q"]) | Q(notes__icontains=filters["q"]))
    if filters["category"] == "none":
        expenses = expenses.filter(category__isnull=True)
    elif filters["category"].isdigit():
        expenses = expenses.filter(category_id=int(filters["category"]))
    if filters["start"]:
        expenses = expenses.filter(date__gte=filters["start"])
    if filters["end"]:
        expenses = expenses.filter(date__lte=filters["end"])
    return expenses, filters


@login_required
def all_transactions(request):
    expenses, filters = _filtered_expenses(request)
    page = Paginator(expenses, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    context = {
        "page": page,
        "filters": filters,
        "filtered_total": expenses.aggregate(s=Sum("amount"))["s"] or 0,
        "filtered_count": page.paginator.count,
        "categories": Category.objects.filter(user=request.user).order_by("name"),
        "query": query.urlencode(),
        "is_filtered": any(filters.values()),
    }
    return render(request, "expenses/all_transactions.html", context)


# --- Insights (deterministic) ----------------------------------------------


@login_required
def insights(request):
    user = request.user
    recurring = services.detect_recurring(user)
    context = {
        "anomalies": services.detect_anomalies(user),
        "recurring": recurring,
        "recurring_monthly": sum(r.monthly_estimate for r in recurring),
        "budgets": services.category_budget_status(user),
        "categories": Category.objects.filter(user=user).order_by("name"),
        "currency": _profile(user).currency,
    }
    return render(request, "expenses/insights.html", context)


@login_required
@require_POST
def set_category_budget(request):
    category = get_object_or_404(Category, id=request.POST.get("category"), user=request.user)
    limit = _amount(request.POST.get("monthly_limit"))
    if limit is None:
        messages.error(request, "Enter a positive limit.")
        return redirect("insights")
    CategoryBudget.objects.update_or_create(user=request.user, category=category, defaults={"monthly_limit": limit})
    messages.success(request, f"Budget set for {category.name}.")
    return redirect("insights")


@login_required
@require_POST
def delete_category_budget(request, budget_id):
    CategoryBudget.objects.filter(id=budget_id, user=request.user).delete()
    messages.success(request, "Category budget removed.")
    return redirect("insights")


# --- AI actions -------------------------------------------------------------


@login_required
@require_POST
def ai_insights(request):
    profile = _profile(request.user)
    advice = ai_utils.get_financial_advice(_ai_context(request.user, profile), symbol=currency_symbol(profile.currency))
    messages.info(request, advice)
    return redirect("dashboard")


@login_required
@require_POST
def budget_forecast(request):
    profile = _profile(request.user)
    spent = services.month_context(request.user)["spent"]
    messages.info(
        request,
        ai_utils.get_budget_forecast(spent, float(profile.monthly_budget), symbol=currency_symbol(profile.currency)),
    )
    return redirect("dashboard")


@login_required
@require_POST
def finance_chat(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid request"}, status=400)
    question = str(payload.get("question", "")).strip()[:500]
    if not question:
        return JsonResponse({"error": "Empty question"}, status=400)

    user = request.user
    profile = _profile(user)
    ChatMessage.objects.create(user=user, message=question, is_user=True)
    answer = ai_utils.ask_financial_assistant(
        question, _ai_context(user, profile), symbol=currency_symbol(profile.currency)
    )
    ChatMessage.objects.create(user=user, message=answer, is_user=False)
    return JsonResponse({"answer": answer})


@login_required
@require_POST
def clear_chat(request):
    ChatMessage.objects.filter(user=request.user).delete()
    return redirect("dashboard")


# --- Reports & income -------------------------------------------------------


def _month_param(request) -> date:
    """The report month from ?month=YYYY-MM, defaulting to the current month."""
    raw = request.GET.get("month", "")
    parsed = _date(f"{raw}-01") if raw else None
    return parsed or timezone.localdate().replace(day=1)


@login_required
def monthly_report(request):
    user = request.user
    first = _month_param(request)
    start, next_start = services.month_bounds(first)
    previous = (start - timezone.timedelta(days=1)).replace(day=1)
    incomes = Income.objects.filter(user=user, date__gte=start, date__lt=next_start)
    expenses = Expense.objects.filter(user=user, date__gte=start, date__lt=next_start).select_related("category")
    total_inc = float(incomes.aggregate(s=Sum("amount"))["s"] or 0)
    total_exp = float(expenses.aggregate(s=Sum("amount"))["s"] or 0)
    by_category = [
        {"name": r["category__name"] or "Uncategorized", "total": float(r["total"])}
        for r in expenses.values("category__name").annotate(total=Sum("amount")).order_by("-total")
    ]
    for row in by_category:
        row["pct"] = round(row["total"] / total_exp * 100) if total_exp else 0
    context = {
        "current_month": start.strftime("%B %Y"),
        "month_value": start.strftime("%Y-%m"),
        "month_end": (next_start - timezone.timedelta(days=1)).isoformat(),
        "prev_month": previous.strftime("%Y-%m"),
        "next_month": next_start.strftime("%Y-%m") if next_start <= timezone.localdate() else "",
        "incomes": incomes,
        "expenses": expenses,
        "by_category": by_category,
        "total_income": total_inc,
        "total_expense": total_exp,
        "net_savings": total_inc - total_exp,
        "savings_rate": round((total_inc - total_exp) / total_inc * 100) if total_inc else None,
        "today": timezone.localdate(),
        "currency": _profile(user).currency,
    }
    return render(request, "expenses/monthly_report.html", context)


def _report_redirect(day: date):
    return redirect(f"{reverse('monthly_report')}?month={day:%Y-%m}")


@login_required
@require_POST
def add_income(request):
    source = request.POST.get("source", "").strip()[:255] or "Income"
    amount = _amount(request.POST.get("amount"))
    received = _date(request.POST.get("date"), timezone.localdate())
    if amount is None or received is None:
        messages.error(request, "Enter a positive amount and a valid date.")
        return redirect("monthly_report")
    Income.objects.create(user=request.user, source=source, amount=amount, date=received)
    messages.success(request, f"Added {source}.")
    return _report_redirect(received)


@login_required
def edit_income(request, income_id):
    income = get_object_or_404(Income, id=income_id, user=request.user)
    if request.method == "POST":
        source = request.POST.get("source", "").strip()[:255]
        amount = _amount(request.POST.get("amount"))
        received = _date(request.POST.get("date"), income.date)
        if not source or amount is None or received is None:
            messages.error(request, "Enter a source, a positive amount and a valid date.")
            return render(request, "expenses/edit_income.html", {"income": income})
        income.source, income.amount, income.date = source, amount, received
        income.save()
        messages.success(request, "Income updated.")
        return _report_redirect(received)
    return render(request, "expenses/edit_income.html", {"income": income})


@login_required
@require_POST
def delete_income(request, income_id):
    income = get_object_or_404(Income, id=income_id, user=request.user)
    month = income.date
    income.delete()
    messages.success(request, "Income deleted.")
    return _report_redirect(month)


# --- Settings ---------------------------------------------------------------


@login_required
def settings_view(request):
    profile = _profile(request.user)
    if request.method == "POST":
        budget = _amount_or_zero(request.POST.get("budget"))
        income = _amount_or_zero(request.POST.get("income"))
        if budget is None or income is None:
            messages.error(request, "Enter zero or a positive number.")
            return redirect("settings")
        profile.monthly_budget, profile.monthly_income = budget, income
        currency = request.POST.get("currency")
        if currency in dict(CURRENCY_CHOICES):
            profile.currency = currency
        profile.save()
        messages.success(request, "Settings saved.")
        return redirect("dashboard")
    return render(
        request,
        "expenses/settings.html",
        {"profile": profile, "currency_choices": CURRENCY_CHOICES, "ai_label": ai_utils.provider_label()},
    )


# --- CSV import / export ----------------------------------------------------

CSV_COLUMNS = ["date", "title", "amount", "category", "notes"]


@login_required
def export_csv(request):
    expenses, _ = _filtered_expenses(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="smart_spend_{timezone.localdate():%Y%m%d}.csv"'
    writer = csv.writer(response)
    writer.writerow(CSV_COLUMNS)
    for e in expenses:
        writer.writerow([e.date.isoformat(), e.title, e.amount, e.category.name if e.category else "", e.notes])
    return response


def _parse_csv(raw: str) -> tuple[list[dict], list[str]]:
    """Validate every row first. Returns (rows, errors); errors name the line number."""
    reader = csv.DictReader(io.StringIO(raw))
    missing = {"title", "amount"} - {(f or "").strip().lower() for f in reader.fieldnames or []}
    if missing:
        return [], [f"Missing column(s): {', '.join(sorted(missing))}. Expected: {', '.join(CSV_COLUMNS)}."]
    rows, errors = [], []
    today = timezone.localdate()
    for line, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        if len(rows) + len(errors) >= settings.CSV_MAX_ROWS:
            errors.append(f"The file has more than {settings.CSV_MAX_ROWS} rows. Split it and import in parts.")
            break
        amount = _amount(row.get("amount"))
        spent_on = _date(row.get("date"), today)
        problems = []
        if not row.get("title"):
            problems.append("title is empty")
        if amount is None:
            problems.append(f"amount '{row.get('amount', '')}' is not a positive number")
        if spent_on is None:
            problems.append(f"date '{row.get('date', '')}' is not YYYY-MM-DD")
        if problems:
            errors.append(f"Line {line}: {'; '.join(problems)}.")
            continue
        rows.append(
            {
                "title": row["title"][:255],
                "amount": amount,
                "date": spent_on,
                "category": row.get("category", ""),
                "notes": row.get("notes", ""),
            }
        )
    return rows, errors


@login_required
def import_csv(request):
    if request.method == "POST" and request.FILES.get("csv_file"):
        upload = request.FILES["csv_file"]
        if upload.size > settings.CSV_MAX_BYTES:
            messages.error(request, "That file is too large. The limit is 2 MB.")
            return render(request, "expenses/import_csv.html")
        try:
            raw = upload.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            messages.error(request, "The file must be UTF-8 text (save it as 'CSV UTF-8').")
            return render(request, "expenses/import_csv.html")
        rows, errors = _parse_csv(raw)
        if errors:
            return render(request, "expenses/import_csv.html", {"errors": errors[:20], "error_count": len(errors)})
        if not rows:
            messages.error(request, "The file has no expense rows.")
            return render(request, "expenses/import_csv.html")
        with transaction.atomic():
            Expense.objects.bulk_create(
                Expense(
                    user=request.user,
                    title=r["title"],
                    amount=r["amount"],
                    date=r["date"],
                    notes=r["notes"],
                    category=_get_or_create_category(request.user, r["category"]),
                )
                for r in rows
            )
        messages.success(request, f"Imported {len(rows)} expense(s).")
        return redirect("all_transactions")
    return render(request, "expenses/import_csv.html")
