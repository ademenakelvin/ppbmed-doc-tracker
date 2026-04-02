from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import LoginHistory


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    staff_profile = getattr(user, 'staff_profile', None)

    LoginHistory.objects.create(
        staff=staff_profile,
        event_type='login',
        username=user.get_username(),
        role=staff_profile.role if staff_profile else '',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
    )


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    if not user:
        return

    staff_profile = getattr(user, 'staff_profile', None)

    LoginHistory.objects.create(
        staff=staff_profile,
        event_type='logout',
        username=user.get_username(),
        role=staff_profile.role if staff_profile else '',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:1000],
    )
