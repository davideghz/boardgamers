from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone, translation
from django.utils.html import escape
from django.urls import reverse
from django.utils.translation import ngettext
import boto3
import json
import logging

from webapp.models import Notification, NotificationType

logger = logging.getLogger(__name__)


def _html_and_text(**values):
    """SES non fa escaping dell'HTML: per ogni valore restituisce `chiave`, escapata
    per la parte HTML, e `chiave_text`, invariata per l'oggetto e la parte testuale."""
    data = {}
    for key, value in values.items():
        data[key] = escape(value)
        data[f'{key}_text'] = value
    return data


class Command(BaseCommand):
    help = 'Invia le notifiche in coda via AWS SES v2 Batch'

    def handle(self, *args, **kwargs):
        # Verifica che le impostazioni AWS SES siano configurate
        # Questo comando è pensato solo per l'ambiente di produzione
        required_settings = ['AWS_SES_REGION_NAME', 'AWS_SES_ACCESS_KEY_ID', 'AWS_SES_SECRET_ACCESS_KEY']
        missing_settings = [s for s in required_settings if not hasattr(settings, s) or not getattr(settings, s, None)]

        if missing_settings:
            self.stdout.write(
                self.style.WARNING(
                    f"Comando non eseguito: mancano le seguenti impostazioni AWS SES: {', '.join(missing_settings)}\n"
                    f"Questo comando è pensato per essere eseguito solo in produzione."
                )
            )
            return

        # Configura client SES v2
        client = boto3.client(
            'sesv2',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY
        )

        total_sent = self._send_new_table(client) + self._send_tables_added(client)
        self.stdout.write(self.style.SUCCESS(f"Operazione completata. Inviate {total_sent} email."))

    def _send_new_table(self, client):
        # 1. Recupera notifiche NEW_TABLE non inviate e non ancora lette sul sito
        notifications = Notification.objects.filter(
            sent=False,
            is_read=False,
            notification_type=NotificationType.NEW_TABLE
        ).select_related(
            'recipient', 'recipient__user',
            'table', 'table__game', 'table__location', 'table__author',
        )

        # Costruisce le entry del batch, saltando gli utenti senza email o che
        # hanno disattivato le notifiche email per i nuovi tavoli.
        valid_notifications = []
        bulk_entries = []

        for n in notifications:
            profile = n.recipient
            # Se l'utente non vuole notifiche email per nuovi tavoli, la segniamo come inviata (processata) ma non inviamo nulla
            if not profile.notification_new_table:
                n.sent = True
                n.sent_at = timezone.now()
                n.save(update_fields=['sent', 'sent_at'])
                continue

            if n.recipient.user.email:
                table = n.table
                game_name = table.game.name if table.game else ""
                description = (table.description or "").strip()

                template_data = _html_and_text(
                    name=profile.nickname,
                    title=table.title,
                    # game vuoto => nascosto nell'oggetto e "Non ancora deciso" nel corpo (via Handlebars)
                    game=game_name,
                    creator_name=table.author.nickname if table.author else "un utente",
                    location_name=table.location.name if table.location else "Location non disponibile",
                )
                template_data.update({
                    'date': table.date.strftime('%d/%m/%Y'),
                    'time': table.time.strftime('%H:%M'),
                    'description': escape(description).replace("\n", "<br>") if description else "",
                    'description_text': description,
                    'button_href': _table_url(table),
                })
                valid_notifications.append(n)
                bulk_entries.append(_bulk_entry(n.recipient.user.email, template_data))

        return self._send_bulk(client, 'NewTableNotification', valid_notifications, bulk_entries)

    def _send_tables_added(self, client):
        # Notifiche TABLES_ADDED (duplicazione di un tavolo con i partecipanti):
        # una sola per persona per tutta la serie. Vale la preferenza "nuovo tavolo".
        notifications = Notification.objects.filter(
            sent=False,
            is_read=False,
            notification_type=NotificationType.TABLES_ADDED,
            table__isnull=False,
        ).select_related(
            'recipient', 'recipient__user',
            'table', 'table__game', 'table__location', 'table__author',
        )

        valid_notifications = []
        bulk_entries = []
        with translation.override(settings.LANGUAGE_CODE):  # il template SES è in italiano
            for n in notifications:
                if not n.recipient.notification_new_table:
                    n.sent = True
                    n.sent_at = timezone.now()
                    n.save(update_fields=['sent', 'sent_at'])
                    continue
                if not n.recipient.user.email:
                    continue
                table = n.table
                dates = [d for d in (n.message or '').split(', ') if d] or [table.date.strftime('%d/%m/%Y')]
                template_data = _html_and_text(
                    name=n.recipient.nickname,
                    title=table.title,
                    game=table.game.name if table.game else "",
                    organizer_name=table.author.nickname if table.author else "un utente",
                    location_name=table.location.name if table.location else "Location non disponibile",
                )
                template_data.update({
                    'sessions': ngettext('%(count)d session', '%(count)d sessions', len(dates)) % {
                        'count': len(dates)},
                    'dates': ', '.join(dates),
                    'time': table.time.strftime('%H:%M'),
                    'button_href': _table_url(table),
                })
                valid_notifications.append(n)
                bulk_entries.append(_bulk_entry(n.recipient.user.email, template_data))

        return self._send_bulk(client, 'TablesAddedNotification', valid_notifications, bulk_entries)

    def _send_bulk(self, client, template_name, valid_notifications, bulk_entries):
        # Processa in chunk di 50 (limite AWS SES per send_bulk_email)
        chunk_size = 50
        total_sent = 0

        for i in range(0, len(bulk_entries), chunk_size):
            chunk_entries = bulk_entries[i:i + chunk_size]
            chunk_notifications = valid_notifications[i:i + chunk_size]

            try:
                self.stdout.write(
                    f"{template_name}: inviando batch {i // chunk_size + 1} di {len(chunk_entries)} email...")
                response = client.send_bulk_email(
                    FromEmailAddress=settings.DEFAULT_FROM_EMAIL,
                    DefaultContent={
                        'Template': {
                            'TemplateName': template_name,
                            'TemplateData': json.dumps({'name': 'Giocatore'})  # Fallback
                        }
                    },
                    BulkEmailEntries=chunk_entries,
                )

                # Logga eventuali esiti non riusciti per singola destinazione
                for result in response.get('BulkEmailEntryResults', []):
                    if result.get('Status') != 'SUCCESS':
                        logger.warning(
                            "Invio notifica %s non riuscito: %s - %s",
                            template_name, result.get('Status'), result.get('Error')
                        )

                # Aggiorna DB
                notif_ids = [n.id for n in chunk_notifications]
                Notification.objects.filter(id__in=notif_ids).update(sent=True, sent_at=timezone.now())

                total_sent += len(chunk_entries)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore durante l'invio del batch: {str(e)}"))
                # Qui potremmo implementare un retry o loggare l'errore specifico

        return total_sent


def _table_url(table):
    return settings.DOMAIN_URL + reverse('table-detail', kwargs={'slug': table.slug})


def _bulk_entry(email, template_data):
    return {
        'Destination': {'ToAddresses': [email]},
        'ReplacementEmailContent': {
            'ReplacementTemplate': {'ReplacementTemplateData': json.dumps(template_data)}
        }
    }
