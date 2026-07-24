import json

from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
from django.utils.html import escape
import boto3


class Command(BaseCommand):
    help = (
        "Invia una mail di prova 'nuovo tavolo' usando il template SES v2 "
        "'NewTableNotification'. Utile per verificare oggetto/corpo dopo "
        "setup_ses_template.\n"
        "Esempi:\n"
        "  python manage.py send_test_new_table_email davideghz@gmail.com\n"
        "  python manage.py send_test_new_table_email davideghz@gmail.com --no-game --no-description"
    )

    def add_arguments(self, parser):
        parser.add_argument('recipient', nargs='?', help="Indirizzo email destinatario della prova")
        parser.add_argument('--name', default='Davide', help="Nickname destinatario (saluto)")
        parser.add_argument('--creator', default='Marco', help="Nome del creatore del tavolo")
        parser.add_argument('--location', default='Ludoteca di Prova', help="Nome location")
        parser.add_argument('--title', default='Serata giochi', help="Titolo del tavolo")
        parser.add_argument('--game', default='Root', help="Nome del gioco")
        parser.add_argument('--description', default='Portate pure i vostri snack!\nInizio puntuale.',
                            help="Descrizione del tavolo (multi-riga con \\n)")
        parser.add_argument('--no-game', action='store_true', help="Simula un tavolo senza gioco")
        parser.add_argument('--no-description', action='store_true', help="Simula un tavolo senza descrizione")
        parser.add_argument('--show-template', action='store_true',
                            help="Non invia nulla: stampa il template live 'NewTableNotification' su SES")
        parser.add_argument('--simple', action='store_true',
                            help="Invia una mail v2 SEMPLICE (senza template) per isolare trasporto vs template")
        parser.add_argument('--render-test', action='store_true',
                            help="Non invia: chiede a SES di renderizzare il template e mostra l'errore se fallisce")

    def handle(self, *args, **opts):
        required = ['AWS_SES_REGION_NAME', 'AWS_SES_ACCESS_KEY_ID', 'AWS_SES_SECRET_ACCESS_KEY']
        missing = [s for s in required if not getattr(settings, s, None)]
        if missing:
            self.stdout.write(self.style.ERROR(
                f"Credenziali AWS SES mancanti in questo ambiente: {', '.join(missing)}.\n"
                f"Esegui il comando su Heroku (heroku run ...) oppure imposta le variabili in locale."
            ))
            return

        client = boto3.client(
            'sesv2',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY,
        )

        self.stdout.write(f"Region: {settings.AWS_SES_REGION_NAME} | From: {settings.DEFAULT_FROM_EMAIL}")

        # 1) Diagnostica: stampa il template attualmente su SES
        if opts['show_template']:
            try:
                t = client.get_email_template(TemplateName='NewTableNotification')
                content = t['TemplateContent']
                self.stdout.write(self.style.SUCCESS("=== Subject live su SES ==="))
                self.stdout.write(content.get('Subject', '(nessuno)'))
                self.stdout.write(self.style.SUCCESS("=== Html live (primi 600 char) ==="))
                self.stdout.write((content.get('Html') or '')[:600])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore get_email_template: {e}"))
            return

        recipient = opts['recipient']

        # 2) Diagnostica: mail v2 SEMPLICE (senza template) per isolare il trasporto
        if opts['simple']:
            self.stdout.write(f"Invio mail v2 SEMPLICE (no template) a {recipient}...")
            try:
                response = client.send_email(
                    FromEmailAddress=settings.DEFAULT_FROM_EMAIL,
                    Destination={'ToAddresses': [recipient]},
                    Content={
                        'Simple': {
                            'Subject': {'Data': 'Test semplice SES v2'},
                            'Body': {
                                'Text': {'Data': 'Corpo di prova (nessun template).'},
                                'Html': {'Data': '<p>Corpo di prova (nessun template).</p>'},
                            },
                        }
                    },
                )
                self.stdout.write(self.style.SUCCESS(f"Inviata (semplice). MessageId: {response.get('MessageId')}"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Errore invio semplice: {e}"))
            return

        game = '' if opts['no_game'] else opts['game']
        description = '' if opts['no_description'] else opts['description']
        now = timezone.localtime()

        template_data = {
            'name': opts['name'],
            'title': opts['title'],
            'game': game,
            'creator_name': opts['creator'],
            'location_name': opts['location'],
            'description': escape(description).replace('\n', '<br>') if description else '',
            'description_text': description,
            'button_href': settings.DOMAIN_URL + '/tables/serata-giochi',
        }

        # 3) Diagnostica: chiedi a SES di renderizzare il template. Se il rendering
        #    fallisce (es. condizionali non supportati) qui vediamo l'errore esatto,
        #    mentre send_email restituisce comunque un MessageId senza consegnare.
        if opts['render_test']:
            self.stdout.write("Test di rendering del template 'NewTableNotification' su SES...")
            try:
                r = client.test_render_email_template(
                    TemplateName='NewTableNotification',
                    TemplateData=json.dumps(template_data),
                )
                self.stdout.write(self.style.SUCCESS("RENDER OK. Anteprima:"))
                self.stdout.write((r.get('RenderedTemplate') or '')[:800])
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"RENDER FALLITO: {e}"))
            return

        recipient = opts['recipient']
        self.stdout.write(
            f"Invio mail di prova a {recipient} "
            f"(gioco: {game or '—'}, descrizione: {'sì' if description else 'no'})..."
        )

        try:
            response = client.send_email(
                FromEmailAddress=settings.DEFAULT_FROM_EMAIL,
                Destination={'ToAddresses': [recipient]},
                Content={
                    'Template': {
                        'TemplateName': 'NewTableNotification',
                        'TemplateData': json.dumps(template_data),
                    }
                },
            )
            self.stdout.write(self.style.SUCCESS(
                f"Inviata. MessageId: {response.get('MessageId')}"
            ))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore durante l'invio: {e}"))
