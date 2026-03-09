from django.shortcuts import redirect
from django.utils.translation import get_language
from django.conf import settings


class NewUIMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.use_new_ui = True
        return self.get_response(request)


def get_v2_template(request, template_name):
    return f'v2/{template_name}'


class UserLanguageRedirectMiddleware:
    """
    Middleware to redirect users to their preferred language version of the site.

    Priority order:
    1. For authenticated users: UserProfile.preferred_language (DB)
    2. For non-authenticated users: Language cookie

    If a user is authenticated and has a preferred_language set in their profile,
    and they're not already on a URL with that language prefix, redirect them.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip for non-GET requests, AJAX, API calls, admin, static files, etc.
        if (request.method != 'GET' or
            request.headers.get('X-Requested-With') == 'XMLHttpRequest' or
            request.path.startswith('/api/') or
            request.path.startswith('/admin/') or
            request.path.startswith('/static/') or
            request.path.startswith('/media/') or
            request.path.startswith('/__debug__/') or
            request.path.startswith('/i18n/') or
            request.path.startswith('/login/') or  # Social auth URLs
            request.path.startswith('/complete/') or  # Social auth callback URLs
            request.path.startswith('/disconnect/')):  # Social auth disconnect URLs
            return self.get_response(request)

        preferred_lang = None

        # Priority 1: Check if user is authenticated and has a preferred language in DB
        if request.user.is_authenticated:
            try:
                preferred_lang = request.user.user_profile.preferred_language
            except AttributeError:
                # User doesn't have user_profile
                pass

        # Priority 2: If no DB preference (or not authenticated), check cookie
        if not preferred_lang:
            preferred_lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)

        # If we have a preferred language, check if we need to redirect
        if preferred_lang:
            current_lang = get_language()

            # If preferred language differs from current language
            if preferred_lang != current_lang:
                # Get the path without language prefix
                path = request.path

                # Remove current language prefix if present
                for lang_code, _ in settings.LANGUAGES:
                    if path.startswith(f'/{lang_code}/'):
                        path = path[len(f'/{lang_code}'):]
                        break

                # Build new URL with preferred language
                if preferred_lang == settings.LANGUAGE_CODE:
                    # Default language - no prefix needed
                    new_path = path
                else:
                    # Non-default language - add prefix
                    new_path = f'/{preferred_lang}{path}'

                # Only redirect if the path actually changed
                if new_path != request.path:
                    return redirect(new_path)

        return self.get_response(request)

