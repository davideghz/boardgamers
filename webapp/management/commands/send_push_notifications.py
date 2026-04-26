import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, activate

from pywebpush import webpush, WebPushException

from webapp.models import Notification, NotificationType, PushSubscription

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {
    NotificationType.NEW_TABLE,
    NotificationType.NEW_PLAYER,
}


def _build_payload(notification):
    """Build the push notification payload dict from a Notification instance."""
    # Activate recipient's preferred language for translated strings
    lang = getattr(notification.recipient, 'preferred_language', None) or 'it'
    activate(lang)

    table = notification.table
    ntype = notification.notification_type

    if table:
        url = settings.SITE_PROTOCOL + '://' + settings.SITE_DOMAIN + reverse('table-detail', kwargs={'slug': table.slug})
    else:
        url = settings.SITE_PROTOCOL + '://' + settings.SITE_DOMAIN + '/'

    if ntype == NotificationType.NEW_TABLE:
        location_name = table.location.name if table.location else ''
        title = _('New table')
        body = f'{table.title}' + (f' — {location_name}' if location_name else '')

    elif ntype == NotificationType.NEW_PLAYER:
        title = _('New player')
        body = _('A new player joined "%(title)s"') % {'title': table.title}

    else:
        # Fallback: use subject/message if available
        title = notification.subject or 'Board Gamers'
        body = notification.message or ''

    return {'title': title, 'body': body, 'url': url}


def _send_to_subscription(sub, payload_dict):
    """Send a push to a single PushSubscription. Returns True on success, False on expired."""
    subscription_info = {
        'endpoint': sub.endpoint,
        'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
    }
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload_dict),
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={'sub': f'mailto:{settings.VAPID_CLAIM_EMAIL}'},
        )
        return True
    except WebPushException as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 410):
            logger.info('Push subscription expired, deleting: %s', sub.endpoint[:60])
            sub.delete()
            return False
        logger.warning('Push send failed (status=%s): %s', status, e)
        return False
    except Exception as e:
        logger.error('Unexpected push error: %s', e)
        return False


class Command(BaseCommand):
    help = 'Invia le notifiche push in coda'

    def handle(self, *args, **kwargs):
        if not settings.VAPID_PRIVATE_KEY or not settings.VAPID_PUBLIC_KEY:
            self.stdout.write(self.style.WARNING('VAPID keys non configurate, comando ignorato.'))
            return

        notifications = Notification.objects.filter(
            push_sent=False,
            is_read=False,
            notification_type__in=SUPPORTED_TYPES,
            created_at__gte=timezone.now() - timedelta(hours=24),
        ).select_related('recipient', 'table', 'table__game', 'table__location')

        if not notifications.exists():
            self.stdout.write('Nessuna notifica push da inviare.')
            return

        sent_count = 0

        for notification in notifications:
            profile = notification.recipient

            # Rispetta le preferenze dell'utente
            if notification.notification_type == NotificationType.NEW_TABLE:
                if not profile.push_notification_new_table:
                    notification.push_sent = True
                    notification.push_sent_at = timezone.now()
                    notification.save(update_fields=['push_sent', 'push_sent_at'])
                    continue

            if notification.notification_type == NotificationType.NEW_PLAYER:
                if not profile.push_notification_new_player:
                    notification.push_sent = True
                    notification.push_sent_at = timezone.now()
                    notification.save(update_fields=['push_sent', 'push_sent_at'])
                    continue

            subscriptions = PushSubscription.objects.filter(user_profile=profile)
            if not subscriptions.exists():
                # Nessun device registrato: segna come processata
                notification.push_sent = True
                notification.push_sent_at = timezone.now()
                notification.save(update_fields=['push_sent', 'push_sent_at'])
                continue

            payload = _build_payload(notification)
            any_success = False
            for sub in subscriptions:
                if _send_to_subscription(sub, payload):
                    sent_count += 1
                    any_success = True

            if any_success:
                notification.push_sent = True
                notification.push_sent_at = timezone.now()
                notification.save(update_fields=['push_sent', 'push_sent_at'])

        self.stdout.write(self.style.SUCCESS(f'Push inviate: {sent_count}.'))
