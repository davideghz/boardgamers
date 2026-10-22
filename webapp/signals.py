from time import sleep

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.gis.geos import Point
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.contrib import messages
from django.conf import settings
from django.utils.translation import gettext as _, activate

from webapp.emails import send_user_email_verification_code, send_notification_new_table, \
    send_email_notification_deleted_table, send_email_notification_new_player
from webapp.models import UserProfile, Player, Table, Notification, NotificationType, Comment, CommentType, \
    EventParticipant, Game, Location, Event
from webapp.services.images import AVATAR_MAX_SIDE, COVER_MAX_SIDE, shrink_content_file


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


# Campi immagine da ridurre al caricamento: (modello, campo, lato lungo massimo)
SHRINKABLE_IMAGE_FIELDS = [
    (Game, 'image', COVER_MAX_SIDE),
    (Location, 'cover', COVER_MAX_SIDE),
    (Table, 'custom_cover', COVER_MAX_SIDE),
    (Event, 'cover', COVER_MAX_SIDE),
    (UserProfile, 'avatar', AVATAR_MAX_SIDE),
]


def _shrink_uploaded_images(sender, instance, **kwargs):
    """Riduce le immagini appena caricate (form, admin) prima che vadano su S3.

    Tocca solo i file non ancora salvati (`_committed=False`): un salvataggio
    del modello senza nuovo upload non riscarica né rielabora nulla.
    """
    for model, field_name, max_side in SHRINKABLE_IMAGE_FIELDS:
        if sender is not model:
            continue
        field_file = getattr(instance, field_name)
        if not field_file or field_file._committed:
            continue
        field_file.seek(0)
        name, content = shrink_content_file(field_file.read(), field_file.name, max_side)
        content.name = name
        setattr(instance, field_name, content)


for _model in {model for model, _f, _s in SHRINKABLE_IMAGE_FIELDS}:
    pre_save.connect(_shrink_uploaded_images, sender=_model, dispatch_uid=f'shrink_images_{_model.__name__}')
