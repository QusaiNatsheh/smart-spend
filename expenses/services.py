"""
Deterministic analytics for Smart Spend.

None of this needs an AI provider or a network call. Everything is computed
from the user's own rows, so it always works and every result is explainable.
"""

from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Expense


def month_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or timezone.localdate()
    start = today.replace(day=1)
    if start.month == 12:
        next_start = start.replace(year=start.year + 1, month=1)
    else:
        next_start = start.replace(month=start.month + 1)
    return start, next_start


def add_months(day: date, months: int) -> date:
    """Same day `months` later, clamped to the end of shorter months (Jan 31 + 1 month = Feb 28)."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def monthly_trend(user, months: int = 6) -> dict:
    """Total spend per month for the last `months` months, oldest first (one query)."""
    today = timezone.localdate()
    buckets: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(months):
        buckets.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    buckets.reverse()

    first = date(*buckets[0], 1)
    totals = {
        (row["month"].year, row["month"].month): row["total"]
        for row in Expense.objects.filter(user=user, date__gte=first)
        .annotate(month=TruncMonth("date"))
        .values("month")
        .annotate(total=Sum("amount"))
    }
    return {
        "labels": [date(year, month, 1).strftime("%b") for year, month in buckets],
        "data": [round(float(totals.get(bucket, 0)), 2) for bucket in buckets],
    }


def month_context(user, today: date | None = None) -> dict:
    """This month's spend broken down, for the AI prompts and the forecast."""
    start, next_start = month_bounds(today)
    month = Expense.objects.filter(user=user, date__gte=start, date__lt=next_start)
    by_category = [
        (row["category__name"] or "Uncategorized", float(row["total"]))
        for row in month.values("category__name").annotate(total=Sum("amount")).order_by("-total")[:6]
    ]
    top_merchants = [
        (row["title"], float(row["total"]))
        for row in month.values("title").annotate(total=Sum("amount")).order_by("-total")[:5]
    ]
    return {
        "spent": float(month.aggregate(s=Sum("amount"))["s"] or 0),
        "by_category": by_category,
        "top_merchants": top_merchants,
    }


@dataclass
class Anomaly:
    expense: Expense
    typical: float
    ratio: float
    baseline: str

    @property
    def reason(self) -> str:
        return f"{self.ratio:.1f}x your usual {self.baseline}"


def detect_anomalies(
    user, lookback_days: int = 90, threshold: float = 2.5, min_ratio: float = 1.5, min_history: int = 4
) -> list[Anomaly]:
    """
    Flag expenses that are unusually large compared with what you normally pay.

    Baseline: the same merchant when it has at least `min_history` expenses in the window, otherwise the
    category. Comparing like with like stops a normal fuel bill from looking huge next to cheap taxi rides
    in the same "Transport" category.

    Method: robust z-score using the median and MAD (median absolute deviation). MAD resists outliers far
    better than a plain mean/stddev, so one big purchase does not hide the next one. An expense is flagged
    when its score is at least `threshold` and it is at least `min_ratio` times the baseline median.
    """
    cutoff = timezone.localdate() - timezone.timedelta(days=lookback_days)
    rows = list(Expense.objects.filter(user=user, date__gte=cutoff).select_related("category"))

    by_merchant: dict[str, list[Expense]] = defaultdict(list)
    by_category: dict[int, list[Expense]] = defaultdict(list)
    for row in rows:
        by_merchant[row.title.strip().lower()].append(row)
        if row.category_id:
            by_category[row.category_id].append(row)

    # (rows to check, rows that form the baseline, label)
    checks = []
    for items in by_merchant.values():
        if len(items) >= min_history:
            checks.append((items, items, items[0].title))
    for items in by_category.values():
        rare = [i for i in items if len(by_merchant[i.title.strip().lower()]) < min_history]
        if rare and len(items) >= min_history:
            checks.append((rare, items, items[0].category.name))

    anomalies: list[Anomaly] = []
    for candidates, baseline, label in checks:
        amounts = [float(i.amount) for i in baseline]
        median = statistics.median(amounts)
        if median <= 0:
            continue
        mad = statistics.median([abs(a - median) for a in amounts]) or (median * 0.1)
        for item in candidates:
            amount = float(item.amount)
            score = (amount - median) / (mad * 1.4826)
            if score >= threshold and amount >= median * min_ratio:
                anomalies.append(Anomaly(item, round(median, 2), amount / median, label))

    anomalies.sort(key=lambda a: a.ratio, reverse=True)
    return anomalies[:5]


CADENCES = {"weekly": 7, "monthly": 30.4, "yearly": 365}


@dataclass
class RecurringGroup:
    title: str
    typical_amount: float
    occurrences: int
    category: str
    cadence: str
    last_date: date

    @property
    def monthly_estimate(self) -> float:
        return round(self.typical_amount * 30.4 / CADENCES[self.cadence], 2)

    @property
    def next_expected(self) -> date:
        if self.cadence == "monthly":
            return add_months(self.last_date, 1)
        if self.cadence == "yearly":
            return add_months(self.last_date, 12)
        return self.last_date + timezone.timedelta(days=7)


def _cadence(dates: list[date]) -> str | None:
    """Name the cadence when the gaps between dates are regular (weekly, monthly or yearly), else None."""
    gaps = [(b - a).days for a, b in zip(dates, dates[1:], strict=False)]
    if not gaps or min(gaps) == 0:
        return None
    typical = statistics.median(gaps)
    for name, days in CADENCES.items():
        tolerance = max(days * 0.2, 2)
        if abs(typical - days) <= tolerance and all(abs(g - days) <= tolerance for g in gaps):
            return name
    return None


def detect_recurring(user, min_occurrences: int = 3) -> list[RecurringGroup]:
    """
    Find subscriptions and regular bills.

    A merchant is recurring when it appears at least `min_occurrences` times, the amounts are within 15% of
    their median, and the payments come at a regular interval (weekly, monthly or yearly). The interval check
    keeps frequent but irregular spend, such as three coffees in one week, out of the list.
    """
    rows = Expense.objects.filter(user=user).select_related("category").order_by("date", "id")
    groups: dict[str, list[Expense]] = defaultdict(list)
    for row in rows:
        groups[row.title.strip().lower()].append(row)

    recurring: list[RecurringGroup] = []
    for items in groups.values():
        if len(items) < min_occurrences:
            continue
        amounts = [float(i.amount) for i in items]
        median = statistics.median(amounts)
        if median <= 0 or any(abs(a - median) > median * 0.15 for a in amounts):
            continue
        cadence = _cadence([i.date for i in items])
        if cadence is None:
            continue
        last = items[-1]
        recurring.append(
            RecurringGroup(
                title=last.title,
                typical_amount=median,
                occurrences=len(items),
                category=last.category.name if last.category else "Uncategorized",
                cadence=cadence,
                last_date=last.date,
            )
        )

    recurring.sort(key=lambda g: g.monthly_estimate, reverse=True)
    return recurring


def category_budget_status(user) -> list[dict]:
    """Per-category spend this month against its limit, with an alert flag."""
    from .models import CategoryBudget

    start, next_start = month_bounds()
    budgets = CategoryBudget.objects.filter(user=user).select_related("category")
    result = []
    for budget in budgets:
        spent = (
            Expense.objects.filter(
                user=user,
                category=budget.category,
                date__gte=start,
                date__lt=next_start,
            ).aggregate(s=Sum("amount"))["s"]
            or 0
        )
        spent = float(spent)
        limit = float(budget.monthly_limit)
        pct = round((spent / limit) * 100) if limit > 0 else 0
        result.append(
            {
                "id": budget.id,
                "category": budget.category.name,
                "spent": spent,
                "limit": limit,
                "pct": min(pct, 100),
                "raw_pct": pct,
                "over": spent > limit,
                "warning": 80 <= pct <= 100,
            }
        )
    result.sort(key=lambda r: r["raw_pct"], reverse=True)
    return result
