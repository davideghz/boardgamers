from django.contrib.auth.signals import user_logged_out
from django.contrib.gis.geos import Point
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings

from webapp.emails import send_user_email_verification_code
from webapp.models import UserProfile, Location, Player, Table, Notification, NotificationType


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Successfully logged out.')


@receiver(post_save, sender=UserProfile)
def on_user_profile_saved(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created and not instance.is_email_verified:
        send_user_email_verification_code(instance)
    if created:
        # Set geolocation point
        instance.point = Point(float(instance.longitude), float(instance.latitude), srid=4326)
        instance.save()


@receiver(post_save, sender=Table)
def notify_followers_on_new_table(sender, instance, created, **kwargs):
    if created:
        followers = instance.location.followers.all()
        for follower in followers:
            Notification.objects.create(
                recipient=follower.user,
                notification_type=NotificationType.NEW_TABLE,
                table=instance
            )


@receiver(post_save, sender=Player)
def notify_players_on_new_player(sender, instance, created, **kwargs):
    if created:
        players = instance.table.players.exclude(id=instance.user_profile.id)
        for player in players:
            Notification.objects.create(
                recipient=player.user,
                notification_type=NotificationType.NEW_PLAYER,
                table=instance.table
            )


@receiver(post_save, sender=Player)
def notify_players_on_leaderboard_update(sender, instance, **kwargs):
    if instance.position != 99:  # Assumendo che 99 significhi posizione non assegnata
        players = instance.table.players.exclude(id=instance.user_profile.id)
        for player in players:
            Notification.objects.create(
                recipient=player.user,
                notification_type=NotificationType.LEADERBOARD_UPDATE,
                table=instance.table
            )
