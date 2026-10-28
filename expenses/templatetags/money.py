from django import template

from ..money import currency_symbol as _symbol
from ..money import format_money as _format

register = template.Library()


@register.filter
def money(amount, currency="USD"):
    return _format(amount, currency)


@register.simple_tag
def currency_symbol(currency="USD"):
    return _symbol(currency)
