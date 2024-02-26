from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings

from webapp.emails import send_user_email_verification_code
from webapp.models import UserProfile


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Logout effettuato con successo.')


@receiver(post_save, sender=UserProfile)
def on_user_signed_up(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created:
        send_user_email_verification_code(instance)
