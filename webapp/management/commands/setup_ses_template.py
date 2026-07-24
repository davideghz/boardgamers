from django.core.management.base import BaseCommand
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import translation
import boto3


class Command(BaseCommand):
    help = 'Crea o aggiorna il template email su AWS SES (API v2)'

    def handle(self, *args, **kwargs):
        client = boto3.client(
            'sesv2',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY
        )

        template_name = "NewTableNotification"

        # Mock objects to inject SES/Handlebars placeholders
        class MockProfile:
            nickname = "{{name}}"

        context = {
            'user_profile': MockProfile(),
            'title': "{{title}}",
            'game': "{{game}}",
            'creator_name': "{{creator_name}}",
            'date': "{{date}}",
            'time': "{{time}}",
            'location_name': "{{location_name}}",
            'button_href': "{{button_href}}",
        }

        # Renderizza i template locali (in italiano) con i placeholder SES.
        # I condizionali {{#if ...}} restano letterali (via {% verbatim %}) e
        # vengono valutati da SES v2 al momento dell'invio.
        with translation.override(settings.LANGUAGE_CODE):
            html_part = render_to_string('emails/email_notification_new_table_html.html', context)
            text_part = render_to_string('emails/email_notification_new_table.html', context)

        template_content = {
            # Il gioco compare nell'oggetto solo se presente: "Nuovo tavolo: Root"
            'Subject': "Nuovo tavolo{{#if game}}: {{game}}{{/if}}",
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
