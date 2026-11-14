from django.core.management.base import BaseCommand
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import translation
import boto3


class Command(BaseCommand):
    help = 'Crea o aggiorna i template email su AWS SES (API v2)'

    def handle(self, *args, **kwargs):
        client = boto3.client(
            'sesv2',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY
        )

        # Un template SES per tipo di notifica in coda (vedi send_queued_notifications)
        templates = [
            {
                'name': "NewTableNotification",
                # Il gioco compare nell'oggetto solo se presente: "Nuovo tavolo: Root"
                # L'oggetto è testo semplice: usa i valori non escapati (*_text)
                'subject': "Nuovo tavolo{{#if game_text}}: {{game_text}}{{/if}}",
                'html': 'emails/email_notification_new_table_html.html',
                'text': 'emails/email_notification_new_table.html',
                'placeholders': ['title', 'game', 'creator_name', 'date', 'time', 'location_name', 'button_href',
                                 'assign_station_href'],
                'escaped': ['name', 'title', 'game', 'creator_name', 'location_name'],
            },
            {
                'name': "TablesAddedNotification",
                'subject': "Sei stato aggiunto a {{sessions}}: {{title_text}}",
                'html': 'emails/email_notification_tables_added_html.html',
                'text': 'emails/email_notification_tables_added.html',
                'placeholders': ['title', 'game', 'organizer_name', 'sessions', 'dates', 'time', 'location_name',
                                 'button_href'],
                'escaped': ['name', 'title', 'game', 'organizer_name', 'location_name'],
            },
        ]
        for spec in templates:
            self._recreate_template(client, spec)

    @staticmethod
    def _placeholder_context(spec, suffix=''):
        """Contesto con i placeholder SES/Handlebars. Con suffix='_text' i valori
        che send_queued_notifications escapa puntano alla loro versione non escapata."""
        def placeholder(key):
            return "{{%s%s}}" % (key, suffix if key in spec['escaped'] else '')

        class MockProfile:
            nickname = placeholder('name')

        context = {'user_profile': MockProfile()}
        context.update({key: placeholder(key) for key in spec['placeholders']})
        return context

    def _recreate_template(self, client, spec):
        template_name = spec['name']

        # Renderizza i template locali (in italiano) con i placeholder SES.
        # I condizionali {{#if ...}} restano letterali (via {% verbatim %}) e
        # vengono valutati da SES v2 al momento dell'invio.
        with translation.override(settings.LANGUAGE_CODE):
            # L'HTML usa i valori escapati, la parte testuale quelli originali (*_text)
            html_part = render_to_string(spec['html'], self._placeholder_context(spec))
            text_part = render_to_string(spec['text'], self._placeholder_context(spec, '_text'))

        template_content = {
            'Subject': spec['subject'],
            'Html': html_part,
            'Text': text_part,
        }

        # Elimina e ricrea il template così è sempre nativo SES v2:
        # un template creato in origine con l'API v1 resta in modalità "basic"
        # e NON supporta i condizionali Handlebars {{#if}}, anche se aggiornato
        # via v2. Ricrearlo con create_email_template garantisce il rendering
        # avanzato (conditionals) usato nell'oggetto e nel corpo.
        try:
            try:
                client.delete_email_template(TemplateName=template_name)
                self.stdout.write(f"Template '{template_name}' esistente eliminato.")
            except client.exceptions.NotFoundException:
                self.stdout.write(f"Template '{template_name}' non presente, verrà creato.")

            client.create_email_template(TemplateName=template_name, TemplateContent=template_content)
            self.stdout.write(self.style.SUCCESS(f"Template '{template_name}' creato (nativo v2) con successo."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore durante l'operazione: {str(e)}"))
