"""Display-only currency formatting. No FX conversion is performed."""

from decimal import Decimal, InvalidOperation

CURRENCIES = {
    "USD": {"symbol": "$", "decimals": 2, "position": "before"},
    "JOD": {"symbol": "JD", "decimals": 3, "position": "after"},  # JOD has 3 minor units
    "SAR": {"symbol": "SR", "decimals": 2, "position": "after"},
}


def format_money(amount, currency: str = "USD") -> str:
    spec = CURRENCIES.get(currency, CURRENCIES["USD"])
    try:
        value = Decimal(str(amount or 0))
    except (InvalidOperation, TypeError):
        value = Decimal(0)
    number = f"{value:,.{spec['decimals']}f}"
    if spec["position"] == "before":
        return f"{spec['symbol']}{number}"
    return f"{number} {spec['symbol']}"


def currency_symbol(currency: str = "USD") -> str:
    return CURRENCIES.get(currency, CURRENCIES["USD"])["symbol"]
