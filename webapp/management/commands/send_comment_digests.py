from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings

from webapp.emails import send_batch_notification_new_messages
from webapp.models import Notification, NotificationType
from collections import defaultdict


class Command(BaseCommand):
    help = 'Invia digest email per commenti non letti, raggruppati per tavolo'

    def handle(self, *args, **kwargs):
        # Recupera tutte le notifiche non inviate e non lette di tipo NEW_COMMENT
        notifications = Notification.objects.filter(
            sent=False,
            is_read=False,
            notification_type=NotificationType.NEW_COMMENT
        ).select_related('recipient', 'table')

        # Raggruppa per utente -> tavolo
        grouped_notifications = defaultdict(lambda: defaultdict(list))
        for notif in notifications:
            grouped_notifications[notif.recipient][notif.table].append(notif)

        for user_profile, tables in grouped_notifications.items():
            total_unread = sum(len(n) for n in tables.values())
            if not user_profile.user.email:
                continue  # salta utenti senza email

            if not user_profile.notification_new_comments:
                continue  # salta utenti che non vogliono notifiche

            # Prepara dettagli dei tavoli
            table_details = [
                {
                    'table': table,
                    'count': len(notifs),
                    'link': f"{settings.DOMAIN_URL}/tables/{table.slug}/"
                }
                for table, notifs in tables.items()
            ]

            send_batch_notification_new_messages(user_profile, total_unread, table_details)

            # Marca tutte le notifiche come inviate
            for notifs in tables.values():
                for n in notifs:
                    n.sent = True
                    n.sent_at = timezone.now()
                    n.save(update_fields=['sent', 'sent_at'])

        self.stdout.write(self.style.SUCCESS('Batch notifications inviate con successo.'))
