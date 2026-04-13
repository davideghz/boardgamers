from time import sleep

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.gis.geos import Point
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings
from django.utils.translation import gettext as _, activate

from webapp.emails import send_user_email_verification_code, send_notification_new_table, \
    send_email_notification_deleted_table, send_email_notification_new_player
from webapp.models import UserProfile, Player, Table, Notification, NotificationType, Comment, CommentType


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    messages.add_message(request, messages.SUCCESS, 'Successfully logged out.')


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    """Apply user's preferred language to session when they log in."""
    try:
        if hasattr(user, 'user_profile') and user.user_profile.preferred_language:
            lang_code = user.user_profile.preferred_language
            activate(lang_code)
            request.session['_language'] = lang_code
    except Exception:
        pass


@receiver(post_save, sender=UserProfile)
def on_user_profile_saved(sender, instance, created, **kwargs):
    if settings.ENABLE_EMAIL_SIGNALS and created and not instance.is_email_verified:
        send_user_email_verification_code(instance)
    if created and instance.latitude and instance.longitude:
        instance.point = Point(float(instance.longitude), float(instance.latitude), srid=4326)
        instance.save()


@receiver(post_save, sender=Table)
def notify_followers_on_new_table(sender, instance, created, **kwargs):
    if created and instance.location:
        followers = instance.location.followers.all()
        for follower in followers:
            Notification.objects.create(
                recipient=follower.user_profile,
                notification_type=NotificationType.NEW_TABLE,
                table=instance,
                location=instance.location,
            )
            # if follower.user_profile.notification_new_table:
            #     send_notification_new_table(follower.user_profile, instance)


@receiver(pre_delete, sender=Table)
def notify_players_on_table_delete(sender, instance, **kwargs):
    """Invia una notifica a tutti i giocatori quando un tavolo viene cancellato"""
    players = Player.objects.filter(table=instance, user_profile__isnull=False).select_related('user_profile__user')
    for player in players:
        Notification.objects.create(
            recipient=player.user_profile,
            notification_type=NotificationType.TABLE_DELETED,
            message=_('The table "%(table_title)s" has been deleted by the organizer') % {
                'table_title': instance.title
            },
            location=instance.location,
        )
        send_email_notification_deleted_table(player.user_profile, instance)


@receiver(post_save, sender=Player)
def notify_players_on_new_player(sender, instance, created, **kwargs):
    if created and instance.user_profile_id:
        players = instance.table.players.exclude(id=instance.user_profile.id)
        for player in players:
            Notification.objects.create(
                recipient=player,
                notification_type=NotificationType.NEW_PLAYER,
                table=instance.table,
                location=instance.table.location,
            )
            if player.notification_new_player:
                send_email_notification_new_player(player, instance.table, instance.user_profile)


@receiver(post_save, sender=Player)
def notify_players_on_leaderboard_update(sender, instance, created, **kwargs):
    if instance.position != 99 and instance.user_profile_id:
        players = instance.table.players.exclude(id=instance.user_profile.id)
        for player in players:
            Notification.objects.create(
                recipient=player,
                notification_type=NotificationType.LEADERBOARD_UPDATED,
                table=instance.table,
                location=instance.table.location,
            )


@receiver(post_save, sender=Comment)
def notify_players_on_new_comments(sender, instance, created, **kwargs):
    if created and instance.comment_type == CommentType.USER:
        players = instance.table.players.exclude(id=instance.author.id)
        for player in players:
            Notification.objects.create(
                recipient=player,
                notification_type=NotificationType.NEW_COMMENT,
                table=instance.table,
                location=instance.table.location,
                message=instance.content,
            )


@receiver(post_save, sender=Table)
def table_status_change_notifications(sender, instance, created, **kwargs):
    if created:
        return

    # 1) leaderboard_status → EDITABLE / NOT_EDITABLE
    if instance.tracker.has_changed('leaderboard_status'):
        old_lb = instance.tracker.previous('leaderboard_status')
        new_lb = instance.leaderboard_status

        if new_lb == Table.LEADERBOARD_EDITABLE:
            subject = _("Time to fill in the leaderboard!")
            message = _("The table “%(title)s” is now open for leaderboard entry.") % {
                'title': instance.title
            }
            for player in instance.players.all():
                Notification.objects.create(
                    recipient=player,
                    table=instance,
                    notification_type=NotificationType.LEADERBOARD_EDITABLE,
                    subject=subject,
                    message=message,
                )

        elif new_lb == Table.LEADERBOARD_NOT_EDITABLE:
            subject = _("Leaderboard locked")
            message = _("The leaderboard for table “%(title)s” has been locked. Check your score!") % {
                'title': instance.title
            }
            for player in instance.players.all():
                Notification.objects.create(
                    recipient=player,
                    table=instance,
                    notification_type=NotificationType.LEADERBOARD_CLOSED,
                    subject=subject,
                    message=message,
                )

    # 2) status → CLOSED
    if instance.tracker.has_changed('status'):
        old_status = instance.tracker.previous('status')
        new_status = instance.status

        if new_status == Table.CLOSED:
            subject = _("Table closed")
            message = _("The table “%(title)s” has been closed.") % {
                'title': instance.title
            }
            for player in instance.players.all():
                Notification.objects.create(
                    recipient=player,
                    table=instance,
                    notification_type=NotificationType.TABLE_CLOSED,
                    subject=subject,
                    message=message,
                )
