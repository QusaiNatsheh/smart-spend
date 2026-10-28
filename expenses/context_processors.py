from django.conf import settings

from .models import UserProfile


def user_currency(request):
    """Expose the active user's display currency to every template."""
    currency = settings.DEFAULT_CURRENCY
    if request.user.is_authenticated:
        profile = UserProfile.objects.filter(user=request.user).only("currency").first()
        if profile:
            currency = profile.currency
    return {"user_currency": currency}
