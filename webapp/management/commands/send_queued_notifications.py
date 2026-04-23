from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
import boto3
import json
import logging

from webapp.models import Notification, NotificationType

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Invia le notifiche in coda via AWS SES Batch'

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
        
        # Configura client SES
        client = boto3.client(
            'ses',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY
        )

        # 1. Recupera notifiche NEW_TABLE non inviate e non ancora lette sul sito
        notifications = Notification.objects.filter(
            sent=False,
            is_read=False,
            notification_type=NotificationType.NEW_TABLE
        ).select_related('recipient', 'recipient__user', 'table', 'table__game', 'table__location')

        if not notifications.exists():
            self.stdout.write("Nessuna notifica da inviare.")
            return


        # Processa in chunk di 50 (limite AWS SES)
        chunk_size = 50
        notification_list = list(notifications)  # Converti queryset in lista per indicizzazione

        # Attenzione: destinations e notification_list devono essere allineati.
        # Sopra ho saltato utenti senza email, quindi devo rifare la lista filtrata.
        valid_notifications = []
        valid_destinations = []

        for n in notifications:
            profile = n.recipient
            # Se l'utente non vuole notifiche email per nuovi tavoli, la segniamo come inviata (processata) ma non inviamo nulla
            if not profile.notification_new_table:
                n.sent = True
                n.sent_at = timezone.now()
                n.save(update_fields=['sent', 'sent_at'])
                continue

            if n.recipient.user.email:
                user = n.recipient.user
                table = n.table
                table_url = settings.DOMAIN_URL + reverse('table-detail', kwargs={'slug': table.slug})

                template_data = {
                    'name': profile.nickname,
                    'title': table.title,
                    'game': table.game.name if table.game else "N/A",
                    'date': table.date.strftime('%d/%m/%Y'),
                    'time': table.time.strftime('%H:%M'),
                    'location_name': table.location.name if table.location else "Location non disponibile",
                    'button_href': table_url
                }

                valid_notifications.append(n)
                valid_destinations.append({
                    'Destination': {'ToAddresses': [user.email]},
                    'ReplacementTemplateData': json.dumps(template_data)
                })

        total_sent = 0

        for i in range(0, len(valid_destinations), chunk_size):
            chunk_destinations = valid_destinations[i:i + chunk_size]
            chunk_notifications = valid_notifications[i:i + chunk_size]

            try:
                self.stdout.write(f"Inviando batch {i // chunk_size + 1} di {len(chunk_destinations)} email...")
                response = client.send_bulk_templated_email(
                    Source=settings.DEFAULT_FROM_EMAIL,
                    Template='NewTableNotification',
                    Destinations=chunk_destinations,
                    DefaultTemplateData=json.dumps({'name': 'Giocatore'}) # Fallback
                )

                # Controlla gli status individuali nella risposta se necessario
                # Per ora assumiamo successo se la chiamata non fallisce e marchiamo come sent
                # AWS restituisce 'Status': 'Success' per ogni messaggio nel blocco 'Status' della response

                # Aggiorna DB
                notif_ids = [n.id for n in chunk_notifications]
                Notification.objects.filter(id__in=notif_ids).update(sent=True, sent_at=timezone.now())

                total_sent += len(chunk_destinations)

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore durante l'invio del batch: {str(e)}"))
                # Qui potremmo implementare un retry o loggare l'errore specifico

        self.stdout.write(self.style.SUCCESS(f"Operazione completata. Inviate {total_sent} email."))
