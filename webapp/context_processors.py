from webapp.models import Notification


def unread_notifications_count(request):
    if request.user.is_authenticated:
        try:
            user_profile = request.user.user_profile
            count = Notification.objects.filter(recipient=user_profile, is_read=False).count()
            return {'unread_notifications_count': count}
        except Exception:
            pass
    return {'unread_notifications_count': 0}
