from django.conf import settings

from webapp.models import Notification


def maps_api_key(request):
    return {'maps_api_key': settings.MAPS_API_KEY}


def unread_notifications_count(request):
    if request.user.is_authenticated:
        try:
            user_profile = request.user.user_profile
            count = Notification.objects.filter(recipient=user_profile, is_read=False).count()
            return {'unread_notifications_count': count}
        except Exception:
            pass
    return {'unread_notifications_count': 0}
