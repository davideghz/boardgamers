from django.core.management.base import BaseCommand
from django.conf import settings
import boto3
import json


class Command(BaseCommand):
    help = 'Crea o aggiorna il template email su AWS SES'

    def handle(self, *args, **kwargs):
        client = boto3.client(
            'ses',
            region_name=settings.AWS_SES_REGION_NAME,
            aws_access_key_id=settings.AWS_SES_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SES_SECRET_ACCESS_KEY
        )

        template_name = "NewTableNotification"

        from django.template.loader import render_to_string

        # Mock objects to inject SES placeholders
        class MockProfile:
            nickname = "{{name}}"

        context = {
            'user_profile': MockProfile(),
            'title': "{{title}}",
            'game': "{{game}}",
            'date': "{{date}}",
            'time': "{{time}}",
            'location_name': "{{location_name}}",
            'button_href': "{{button_href}}",
        }

        # Renderizza i template locali con i placeholder SES
        html_part = render_to_string('emails/email_notification_new_table_html.html', context)
        text_part = render_to_string('emails/email_notification_new_table.html', context)

        template = {
            'TemplateName': template_name,
            'SubjectPart': "Nuovo tavolo: {{title}}",
            'HtmlPart': html_part,
            'TextPart': text_part
        }

        try:
            self.stdout.write(f"Tentativo di aggiornamento del template '{template_name}'...")
            client.update_template(Template=template)
            self.stdout.write(self.style.SUCCESS(f"Template '{template_name}' aggiornato con successo."))
        except client.exceptions.TemplateDoesNotExistException:
            self.stdout.write(f"Template '{template_name}' non trovato. Tentativo di creazione...")
            client.create_template(Template=template)
            self.stdout.write(self.style.SUCCESS(f"Template '{template_name}' creato con successo."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Errore durante l'operazione: {str(e)}"))
