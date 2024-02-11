from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_out
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from django.conf import settings


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Logout effettuato con successo.')


@receiver(post_save, sender=User)
def send_email_verification_code(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created:
        account_activation_token = PasswordResetTokenGenerator()
        params = {
            'uidb64': urlsafe_base64_encode(force_bytes(instance.pk)),
            'token': account_activation_token.make_token(instance),
        }
        activation_link = settings.DOMAIN_URL + reverse('email_verify', kwargs=params)

        context = {
            'button_href': activation_link,
            'username': instance.username,
        }

        subject = "Benvenuto nel nostro sito"
        text_content = render_to_string('emails/email_verification_code.html', context=context)
        html_content = render_to_string('emails/email_verification_code_html.html', context=context)

        send_mail(
            subject,
            text_content,
            settings.DEFAULT_FROM_EMAIL,
            [instance.email],
            html_message=html_content)
