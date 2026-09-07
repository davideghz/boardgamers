from functools import wraps
from urllib.parse import urlparse

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import resolve_url, get_object_or_404, redirect
from django.utils import translation
from django.utils.timezone import now
from django.utils.translation import gettext as _

from webapp.models import Table
from webapp.services.telegram import (
    miniapp_language, profile_from_init_data, validate_init_data,
)


def only_admin_can_edit_closed_table(view_func):
    """
    Decorator that allows only admin users to edit old tables (past dates).
    """
    @wraps(view_func)
    def _wrapped_view(request, location_slug, table_slug, *args, **kwargs):
        table = get_object_or_404(Table, slug=table_slug)
        if table.status == table.CLOSED and not request.user.is_superuser:
            messages.error(request, _("Can't edit closed tables."), extra_tags="danger")
            return redirect("table-detail", slug=table_slug)
        return view_func(request, location_slug, table_slug, *args, **kwargs)
    return _wrapped_view


def only_author_or_admin_can_edit(view_func):
    """
    Decorator that allows the author, an admin, or the location
    owner/managers to edit a table.
    """
    @wraps(view_func)
    def _wrapped_view(request, location_slug, table_slug, *args, **kwargs):
        table = get_object_or_404(Table, slug=table_slug)
        is_author = table.author_id is not None and request.user == table.author.user
        is_admin = request.user.is_staff
        is_location_manager = False
        if request.user.is_authenticated and table.location_id:
            up = request.user.user_profile
            loc = table.location
            is_location_manager = loc.creator_id == up.id or loc.managers.filter(id=up.id).exists()
        if not (is_author or is_admin or is_location_manager):
            messages.error(request, _("You don't have permission to edit this table."), extra_tags="danger")
            return redirect("table-detail", slug=table_slug)
        return view_func(request, location_slug, table_slug, *args, **kwargs)
    return _wrapped_view


def user_passes_test_with_messages(
        user_pass_test_func,
        error_message,
        login_url=None,
        redirect_field_name=REDIRECT_FIELD_NAME,
):
    """
    Decorator for views that checks that the user passes the given test, redirecting to the log-in page if necessary.
    The test should be a callable that takes the user object and returns True if the user passes.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if user_pass_test_func(request.user):
                return view_func(request, *args, **kwargs)
            path = request.build_absolute_uri()
            resolved_login_url = resolve_url(login_url or settings.LOGIN_URL)
            # If the login url is the same scheme and net location then just use the path as the "next" url.
            login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
            current_scheme, current_netloc = urlparse(path)[:2]
            if (
                    (not login_scheme or login_scheme == current_scheme) and
                    (not login_netloc or login_netloc == current_netloc)):
                path = request.get_full_path()
            messages.error(request, error_message, extra_tags="danger")
            return redirect_to_login(path, resolved_login_url, redirect_field_name)
        return _wrapped_view
    return decorator

def author_or_admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        table = get_object_or_404(Table, slug=kwargs['slug'])
        if (table.author_id is not None and table.author.user == request.user) or request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        return HttpResponseForbidden("Request not allowed")
    return _wrapped_view

def telegram_miniapp_auth(view_func):
    """Authenticate a Telegram Mini App request from its signed `initData`.

    Populates `request.telegram_user` (the validated payload's user),
    `request.telegram_start_param` (the location the app was opened for) and
    `request.telegram_profile` (the linked UserProfile, or None when the
    Telegram account was never connected to a Board-Gamers one).

    Deliberately ignores the Django session: inside Telegram's iframe the
    session cookie is unreliable, and the signature is the only identity worth
    trusting here. That also makes these endpoints immune to CSRF — a third
    party cannot set this header, nor forge its contents.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        data = validate_init_data(request.headers.get('X-Telegram-Init-Data', ''))
        if data is None:
            return JsonResponse({'error': 'invalid_init_data'}, status=401)

        request.telegram_user = data.get('user') or {}
        request.telegram_start_param = data.get('start_param', '')
        request.telegram_profile = profile_from_init_data(data)

        # Everything the endpoints return is user-facing — labels, day names,
        # refusal messages — so pick the language once, here, rather than in
        # each of them.
        language = miniapp_language(request.telegram_profile, request.telegram_user)
        if not language:
            return view_func(request, *args, **kwargs)
        with translation.override(language):
            return view_func(request, *args, **kwargs)
    return _wrapped_view
