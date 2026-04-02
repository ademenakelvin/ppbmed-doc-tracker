from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.shortcuts import redirect
from django.utils import timezone

from .models import AuditLog


class RateLimitedLoginView(LoginView):
    template_name = 'registration/login.html'

    def get_client_ip(self):
        forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        return self.request.META.get('REMOTE_ADDR', 'unknown')

    def get_submitted_username(self):
        return self.request.POST.get('username', '').strip().lower() or 'anonymous'

    def get_cache_keys(self):
        username = self.get_submitted_username()
        ip_address = self.get_client_ip()
        return (
            f'login-limit:user:{username}',
            f'login-limit:ip:{ip_address}',
        )

    def get_staff_profile(self, user):
        return getattr(user, 'staff_profile', None)

    def get_auth_details(self, username):
        ip_address = self.get_client_ip()
        user_agent = self.request.META.get('HTTP_USER_AGENT', '')[:500]
        return f'Username: {username}. IP: {ip_address}. User agent: {user_agent}'

    def log_auth_event(self, action, username, details, actor=None):
        AuditLog.objects.create(
            actor=actor,
            action=action,
            target_type='Authentication',
            target_label=username,
            details=details,
        )

    def is_rate_limited(self):
        max_attempts = getattr(settings, 'LOGIN_RATE_LIMIT_ATTEMPTS', 5)
        user_key, ip_key = self.get_cache_keys()
        return cache.get(user_key, 0) >= max_attempts or cache.get(ip_key, 0) >= max_attempts

    def bump_rate_limit(self):
        timeout = getattr(settings, 'LOGIN_RATE_LIMIT_WINDOW', 900)
        for key in self.get_cache_keys():
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, timeout)

    def clear_rate_limit(self):
        for key in self.get_cache_keys():
            cache.delete(key)

    def post(self, request, *args, **kwargs):
        if self.is_rate_limited():
            request.rate_limit_blocked = True
            username = self.get_submitted_username()
            window_minutes = max(getattr(settings, 'LOGIN_RATE_LIMIT_WINDOW', 900) // 60, 1)
            self.log_auth_event(
                'Login Blocked',
                username,
                self.get_auth_details(username),
            )
            form = self.get_form()
            form.add_error(None, f'Too many failed login attempts. Please wait {window_minutes} minute(s) and try again.')
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        self.clear_rate_limit()
        self.request.session['last_activity_ts'] = int(timezone.now().timestamp())
        return super().form_valid(form)

    def form_invalid(self, form):
        if (
            self.request.method == 'POST'
            and not getattr(self.request, 'rate_limit_blocked', False)
            and not getattr(self.request, 'auth_infrastructure_error', False)
        ):
            self.bump_rate_limit()
            username = self.get_submitted_username()
            self.log_auth_event(
                'Login Failed',
                username,
                self.get_auth_details(username),
            )
        return super().form_invalid(form)
