from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            login_url = reverse('login')
            logout_url = reverse('logout')
            current_path = request.path

            if current_path not in {login_url, logout_url}:
                now_ts = int(timezone.now().timestamp())
                last_activity = request.session.get('last_activity_ts')
                idle_timeout = getattr(settings, 'SESSION_IDLE_TIMEOUT', 1800)

                if last_activity and now_ts - int(last_activity) > idle_timeout:
                    logout(request)
                    messages.warning(request, 'Your session expired due to inactivity. Please sign in again.')
                    return redirect(f'{login_url}?next={current_path}')

                request.session['last_activity_ts'] = now_ts

        return self.get_response(request)
