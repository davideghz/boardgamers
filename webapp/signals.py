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

from webapp.emails import send_user_email_verification_code


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Logout effettuato con successo.')


@receiver(post_save, sender=User)
def on_user_signed_up(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created:
        send_user_email_verification_code(instance)
