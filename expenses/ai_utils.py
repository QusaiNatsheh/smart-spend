"""
AI helpers with two interchangeable providers.

- Gemini (hosted) when GEMINI_API_KEY is set.
- Ollama (local, free) when OLLAMA_URL is set, for example with a Qwen2.5-VL model.

AI_PROVIDER forces one of "gemini", "ollama" or "none"; by default the first configured provider is used.
Every function degrades gracefully: if no provider is configured or the call fails, the app keeps working and
the user sees a friendly fallback instead of a traceback. Structured answers use each provider's JSON-schema
output, so replies are parsed, not scraped.
"""

import base64
import calendar
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

EXPENSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "amount": {"type": "number"},
        "category": {"type": "string"},
        "date": {"type": "string", "description": "YYYY-MM-DD, only if the text mentions a day"},
    },
    "required": ["title", "amount", "category"],
}

NO_AI = "AI is off. Add a Gemini key or a local Ollama model in .env to use this."


def provider() -> str:
    """Return "gemini", "ollama" or "none"."""
    forced = settings.AI_PROVIDER
    if forced in {"gemini", "ollama", "none"}:
        return forced
    if settings.GEMINI_API_KEY:
        return "gemini"
    if settings.OLLAMA_URL:
        return "ollama"
    return "none"


def provider_label() -> str:
    return {
        "gemini": f"Gemini · {settings.GEMINI_MODEL}",
        "ollama": f"Local · {settings.OLLAMA_MODEL}",
    }.get(provider(), "AI off")


def _gemini(prompt: str, image: bytes | None, schema: dict | None) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    contents = [prompt]
    if image is not None:
        contents.append(types.Part.from_bytes(data=image, mime_type="image/jpeg"))
    config = types.GenerateContentConfig(
        response_mime_type="application/json" if schema else "text/plain",
        response_schema=schema,
        temperature=0.2,
    )
    response = client.models.generate_content(model=settings.GEMINI_MODEL, contents=contents, config=config)
    return response.text or ""


def _ollama(prompt: str, image: bytes | None, schema: dict | None) -> str:
    message = {"role": "user", "content": prompt}
    if image is not None:
        message["images"] = [base64.b64encode(image).decode()]
    body = {
        "model": settings.OLLAMA_MODEL,
        "messages": [message],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if schema:
        body["format"] = schema
    request = urllib.request.Request(
        f"{settings.OLLAMA_URL.rstrip('/')}/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=settings.AI_TIMEOUT) as response:
        return json.load(response)["message"]["content"]


def _generate(prompt: str, image: bytes | None = None, schema: dict | None = None) -> str | None:
    """Send one prompt (and optionally one image) to the active provider. Returns None when AI is unavailable."""
    name = provider()
    try:
        if name == "gemini":
            return _gemini(prompt, image, schema)
        if name == "ollama":
            return _ollama(prompt, image, schema)
    except ImportError:
        logger.warning("google-genai is not installed; AI features are disabled.")
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("The %s provider could not be reached.", name)
    except Exception:
        logger.exception("AI call to %s failed", name)
    return None


def _json(text: str | None) -> dict | None:
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("AI reply was not valid JSON: %r", text[:200])
        return None
    return data if isinstance(data, dict) else None


def parse_expense_text(user_input: str, categories: list[str] | None = None) -> dict | None:
    today = timezone.localdate()
    known = f"Prefer one of these existing categories: {', '.join(categories)}." if categories else ""
    prompt = f"""Extract one expense from the text below. Today is {today.isoformat()} ({today:%A}).
- title: a short description, for example "Lunch at the cafe"
- amount: the cost as a number, without currency symbols
- category: one short category name, for example Food, Transport, Utilities. {known}
- date: YYYY-MM-DD only if the text says when (for example "yesterday"); otherwise omit it
Text: "{user_input}\""""
    return _json(_generate(prompt, schema=EXPENSE_SCHEMA))


def parse_receipt_image(image_bytes: bytes, categories: list[str] | None = None) -> dict | None:
    known = f"Prefer one of these existing categories: {', '.join(categories)}." if categories else ""
    prompt = f"""Read this receipt.
- title: the store name, or a short description such as "Carrefour groceries"
- amount: the final total paid, as a number without currency symbols
- category: one short category name. {known}
- date: the receipt date as YYYY-MM-DD, if printed"""
    return _json(_generate(prompt, image=image_bytes, schema=EXPENSE_SCHEMA))


def _context_lines(data: dict, symbol: str) -> str:
    lines = [
        f"- Monthly income: {symbol}{data.get('income', 0):,.2f}",
        f"- Monthly budget: {symbol}{data.get('budget', 0):,.2f}",
        f"- Spent this month so far: {symbol}{data.get('spent', 0):,.2f} (day {data.get('day')} of {data.get('days')})",
    ]
    if data.get("by_category"):
        spent = data.get("spent") or sum(total for _, total in data["by_category"]) or 1
        lines.append("- This month by category, largest first:")
        lines.extend(
            f"  {rank}. {name} {symbol}{total:,.2f} ({total / spent:.0%})"
            for rank, (name, total) in enumerate(data["by_category"], start=1)
        )
    if data.get("top_merchants"):
        parts = ", ".join(f"{name} {symbol}{total:,.2f}" for name, total in data["top_merchants"])
        lines.append(f"- Top merchants this month: {parts}")
    if data.get("balance") is not None:
        lines.append(f"- Balance (all income minus all expenses): {symbol}{data['balance']:,.2f}")
    return "\n".join(lines)


def get_financial_advice(data: dict, symbol: str = "$") -> str:
    prompt = f"""You are a direct, practical personal finance coach.
{_context_lines(data, symbol)}
Give two short sentences of advice based only on these numbers. Name the category to cut, if any.
Quote numbers exactly as listed and do not calculate new totals or percentages."""
    return (_generate(prompt) or "").strip() or NO_AI


def ask_financial_assistant(question: str, data: dict, symbol: str = "$") -> str:
    prompt = f"""You are a concise personal finance assistant. The user's data:
{_context_lines(data, symbol)}

Question: "{question}"
Answer based only on the data above, in at most three friendly sentences. Quote numbers exactly as listed and
do not calculate new totals or percentages. If the data cannot answer it, say so."""
    return (_generate(prompt) or "").strip() or NO_AI


def forecast_numbers(spent: float, budget: float, today=None) -> dict:
    """Month-end projection at the current daily pace. Deterministic, so it works without AI."""
    today = today or timezone.localdate()
    days = calendar.monthrange(today.year, today.month)[1]
    remaining = days - today.day
    projected = spent / today.day * days
    safe_daily = (budget - spent) / remaining if budget and remaining > 0 else 0.0
    return {
        "day": today.day,
        "days": days,
        "remaining": remaining,
        "projected": projected,
        "safe_daily": max(safe_daily, 0.0),
        "over": bool(budget) and projected > budget,
    }


def get_budget_forecast(spent: float, budget: float, symbol: str = "$") -> str:
    f = forecast_numbers(spent, budget)
    plain = f"At your current pace you will spend about {symbol}{f['projected']:,.0f} this month"
    if budget:
        plain += f" against a {symbol}{budget:,.0f} budget"
        if f["remaining"]:
            plain += f". Safe daily spend for the remaining {f['remaining']} days: {symbol}{f['safe_daily']:,.0f}"
    plain += "."
    prompt = f"""Rewrite this budget forecast as two short, encouraging but realistic sentences. Keep every number.
{plain}"""
    return (_generate(prompt) or "").strip() or plain
