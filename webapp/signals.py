from time import sleep

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.gis.geos import Point
from django.db.models.signals import m2m_changed, post_save, pre_delete
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings
from django.utils.translation import gettext as _, activate

from webapp.emails import send_user_email_verification_code, send_notification_new_table, \
    send_email_notification_deleted_table, send_email_notification_new_player
from webapp.models import UserProfile, Player, Table, Notification, NotificationType, Comment, CommentType, \
    EventParticipant, Event, EventGame


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    # fail_silently: logging out does not always happen through a request that
    # went past the message middleware (the test client's logout, for one).
    messages.add_message(request, messages.SUCCESS, _('Successfully logged out.'),
                         fail_silently=True)


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
    # Copies made by duplicate_table set the flag: a series of N tables would
    # otherwise notify every follower N times.
    if created and not getattr(instance, '_skip_follower_notification', False) and instance.location:
        location = instance.location
        recipient_ids = set(location.followers.values_list('user_profile_id', flat=True))
        # The location staff is notified too when the table could get a station:
        # send_queued_notifications adds the "assign a station" link to their mail.
        # Locations without stations only notify their followers.
        if instance.physical_table_id is None and not instance.event_id and location.physical_tables.exists():
            staff_ids = {location.creator_id, *location.managers.values_list('id', flat=True)}
            recipient_ids |= staff_ids
        # The author knows about their own table, even when they follow the location.
        recipient_ids -= {None, instance.author_id}
        Notification.objects.bulk_create([
            Notification(
                recipient_id=recipient_id,
                notification_type=NotificationType.NEW_TABLE,
                table=instance,
                location=location,
            )
            for recipient_id in recipient_ids
        ])


@receiver(post_save, sender=Table)
def add_table_game_to_event_library(sender, instance, created, **kwargs):
    """A game played at an event belongs to its library. Only on creation or when
    the game changes: a game the managers removed must not come back on any save."""
    if instance.event_id and instance.game_id and (created or instance.tracker.has_changed('game')):
        EventGame.objects.get_or_create(event_id=instance.event_id, game_id=instance.game_id)


@receiver(m2m_changed, sender=Event.sponsor_locations.through)
def drop_removed_sponsors_from_event_games(sender, instance, action, reverse, **kwargs):
    """A location that no longer sponsors the event can't bring games to it."""
    if reverse or action not in ('post_remove', 'post_clear'):
        return
    (EventGame.sponsor_locations.through.objects
     .filter(eventgame__event=instance)
     .exclude(location__in=instance.sponsor_locations.all())
     .delete())


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
def register_event_participation_on_join(sender, instance, created, **kwargs):
    """When a user joins a table belonging to an event, ensure they are also
    registered as a participant of that event."""
    if created and instance.user_profile_id and instance.table.event_id:
        EventParticipant.objects.get_or_create(
            event_id=instance.table.event_id,
            user_profile_id=instance.user_profile_id,
        )


# NB: la notifica di aggiornamento leaderboard NON è più gestita qui via signal.
# Scattava a ogni Player.save() (N×(N-1) notifiche per un singolo riordino, che
# salva i player in loop). Ora è inviata una sola volta, in batch, da
# save_table_result (webapp/services/tables.py) — una notifica per destinatario.


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
    from webapp.services.tables import leaderboard_available  # local import: avoid import cycles
    if instance.tracker.has_changed('leaderboard_status') and leaderboard_available(instance):
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
