from django.conf import settings

from webapp.models import Notification


def maps_api_key(request):
    return {'maps_api_key': settings.MAPS_API_KEY}


def telegram_config(request):
    bot_token = settings.SOCIAL_AUTH_TELEGRAM_BOT_TOKEN
    bot_username = settings.TELEGRAM_BOT_USERNAME
    if not bot_token or ':' not in bot_token or not bot_username:
        return {'telegram_bot_username': '', 'telegram_auth_url': None}
    from urllib.parse import quote
    bot_id = bot_token.split(':')[0]
    origin = f"{request.scheme}://{request.get_host()}"
    return_to = request.build_absolute_uri()
    auth_url = (
        f"https://oauth.telegram.org/auth"
        f"?bot_id={bot_id}"
        f"&origin={quote(origin, safe='')}"
        f"&request_access=write"
        f"&return_to={quote(return_to, safe='')}"
    )
    return {
        'telegram_bot_username': bot_username,
        'telegram_auth_url': auth_url,
    }


def vapid_public_key(request):
    return {'vapid_public_key': settings.VAPID_PUBLIC_KEY}


def unread_notifications_count(request):
    if request.user.is_authenticated:
        try:
            user_profile = request.user.user_profile
            count = Notification.objects.filter(recipient=user_profile, is_read=False).count()
            return {'unread_notifications_count': count}
        except Exception:
            pass
    return {'unread_notifications_count': 0}
