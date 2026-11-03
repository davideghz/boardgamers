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

        # Mock objects to inject SES/Handlebars placeholders
        class MockProfile:
            nickname = "{{name}}"

        # Un template SES per tipo di notifica in coda (vedi send_queued_notifications)
        templates = [
            {
                'name': "NewTableNotification",
                # Il gioco compare nell'oggetto solo se presente: "Nuovo tavolo: Root"
                'subject': "Nuovo tavolo{{#if game}}: {{game}}{{/if}}",
                'html': 'emails/email_notification_new_table_html.html',
                'text': 'emails/email_notification_new_table.html',
                'placeholders': ['title', 'game', 'creator_name', 'date', 'time', 'location_name', 'button_href'],
            },
            {
                'name': "TablesAddedNotification",
                'subject': "Sei stato aggiunto a {{sessions}}: {{title}}",
                'html': 'emails/email_notification_tables_added_html.html',
                'text': 'emails/email_notification_tables_added.html',
                'placeholders': ['title', 'game', 'organizer_name', 'sessions', 'dates', 'time', 'location_name',
                                 'button_href'],
            },
        ]
        for spec in templates:
            self._recreate_template(client, spec, MockProfile())

    def _recreate_template(self, client, spec, user_profile):
        template_name = spec['name']
        context = {'user_profile': user_profile}
        context.update({key: "{{%s}}" % key for key in spec['placeholders']})

        # Renderizza i template locali (in italiano) con i placeholder SES.
        # I condizionali {{#if ...}} restano letterali (via {% verbatim %}) e
        # vengono valutati da SES v2 al momento dell'invio.
        with translation.override(settings.LANGUAGE_CODE):
            html_part = render_to_string(spec['html'], context)
            text_part = render_to_string(spec['text'], context)

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
