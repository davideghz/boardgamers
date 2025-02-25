from django.contrib.auth.signals import user_logged_out
from django.contrib.gis.geos import Point
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings

from webapp.emails import send_user_email_verification_code
from webapp.models import UserProfile, Location


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Successfully logged out.')


@receiver(post_save, sender=UserProfile)
def on_user_profile_saved(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created and not instance.is_email_verified:
        send_user_email_verification_code(instance)
    if created:
        instance.point = Point(float(instance.longitude), float(instance.latitude), srid=4326)
        instance.save()
