from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from social_django.models import UserSocialAuth

from webapp.models import (
    Comment, Event, EventParticipant, FavoriteUser, GuestProfile,
    Location, LocationFollower, LocationGameLoan, Member, Membership, Notification,
    Player, PushSubscription, Table, UserProfile,
)


def validate_accounts(*users):
    if any(
        user.is_staff or user.is_superuser or not user.is_active
        or user.groups.exists() or user.user_permissions.exists()
        for user in users
    ):
        raise ValidationError(_("Only active accounts without Django admin roles or permissions can be merged."))


def _merge_players(keeper, duplicate):
    keeper_players = Player.objects.filter(user_profile=keeper)
    duplicate_players = Player.objects.filter(user_profile=duplicate)
    overlaps = duplicate_players.filter(table_id__in=keeper_players.values('table_id'))
    for extra in overlaps.select_for_update().order_by('pk'):
        current = keeper_players.select_for_update().get(table_id=extra.table_id)
        current_result = (current.position, current.score, current.team, current.outcome, current.guest_profile_id)
        extra_result = (extra.position, extra.score, extra.team, extra.outcome, extra.guest_profile_id)
        if current_result != extra_result:
            raise ValidationError(
                _("Both profiles have different player records on table #%(table)s. Resolve them before merging."),
                params={'table': extra.table_id},
            )
        extra.delete()
        Table.objects.get(pk=current.table_id).recompute_outcomes()
    duplicate_players.update(user_profile=keeper)


def has_password(user):
    return bool(user.password) and user.has_usable_password()


def _merge_credentials(keeper, duplicate, keeper_user, duplicate_user):
    import_email = not keeper_user.email and bool(duplicate_user.email)
    if import_email:
        email = duplicate_user.email
        if User.objects.exclude(pk__in=(keeper_user.pk, duplicate_user.pk)).filter(
            Q(email__iexact=email) | Q(username__iexact=email)
        ).exists():
            raise ValidationError(_("The email or username is already used by another account."))
        if len(email) > User._meta.get_field('username').max_length:
            raise ValidationError(_("The email is too long to use as a username."))
        keeper_user.email = keeper_user.username = email
        keeper.is_email_verified = duplicate.is_email_verified
        keeper.save(update_fields=['is_email_verified'])

    logins = list(UserSocialAuth.objects.select_for_update().filter(
        user_id__in=(keeper_user.pk, duplicate_user.pk)
    ).order_by('pk'))
    providers = {login.provider for login in logins if login.user_id == keeper_user.pk}
    for login in logins:
        if login.user_id == duplicate_user.pk and login.provider not in providers:
            login.user = keeper_user
            login.save(update_fields=['user'])
            providers.add(login.provider)
    return import_email


def _merge_profile_data(keeper, duplicate):
    _merge_players(keeper, duplicate)

    for model, field in (
        (Location, 'creator'), (Event, 'creator'), (Table, 'author'), (Comment, 'author'),
        (GuestProfile, 'owner'), (Notification, 'recipient'), (Member, 'user_profile'),
        (Membership, 'approved_by'),
        (LocationGameLoan, 'loaned_by'), (LocationGameLoan, 'returned_by'),
    ):
        model.objects.filter(**{field: duplicate}).update(**{field: keeper})

    for model, field, key in (
        (LocationFollower, 'user_profile', 'location_id'),
        (EventParticipant, 'user_profile', 'event_id'),
        (PushSubscription, 'user_profile', 'endpoint'),
        (Location.managers.through, 'userprofile', 'location_id'),
        (Event.managers.through, 'userprofile', 'event_id'),
        (Event.allowed_table_creators.through, 'userprofile', 'event_id'),
    ):
        existing = model.objects.filter(**{field: keeper}).values(key)
        incoming = model.objects.filter(**{field: duplicate})
        incoming.filter(**{f'{key}__in': existing}).delete()
        incoming.update(**{field: keeper})

    for field, other in (('owner', 'favorite'), ('favorite', 'owner')):
        existing = FavoriteUser.objects.filter(**{field: keeper}).values(f'{other}_id')
        incoming = FavoriteUser.objects.filter(**{field: duplicate})
        incoming.filter(**{f'{other}__in': (keeper, duplicate)}).delete()
        incoming.filter(**{f'{other}_id__in': existing}).delete()
        incoming.update(**{field: keeper})


def _check_leftover_relations(instance, allowed_fields=()):
    for relation in instance._meta.get_fields(include_hidden=True):
        if relation.auto_created and (relation.one_to_many or relation.one_to_one):
            if (relation.field not in allowed_fields
                    and relation.related_model._base_manager.filter(**{relation.field.name: instance}).exists()):
                raise ValidationError(_("The duplicate still has linked records that could not be transferred."))


@transaction.atomic
def merge_accounts(keeper_id, duplicate_id):
    profiles = {
        profile.pk: profile for profile in
        UserProfile.objects.select_for_update().filter(pk__in=(keeper_id, duplicate_id)).order_by('pk')
    }
    if len(profiles) != 2:
        raise ValidationError(_("Select two different accounts that still exist."))
    keeper, duplicate = profiles[keeper_id], profiles[duplicate_id]
    users = {
        user.pk: user for user in
        User.objects.select_for_update().filter(pk__in=(keeper.user_id, duplicate.user_id)).order_by('pk')
    }
    keeper_user, duplicate_user = users[keeper.user_id], users[duplicate.user_id]
    validate_accounts(keeper_user, duplicate_user)
    import_email = _merge_credentials(keeper, duplicate, keeper_user, duplicate_user)
    _merge_profile_data(keeper, duplicate)

    if not keeper_user.email or not (
        has_password(keeper_user) or UserSocialAuth.objects.filter(user=keeper_user).exists()
    ):
        raise ValidationError(_("The merged account must have an email and at least one login method."))
    _check_leftover_relations(duplicate)
    _check_leftover_relations(duplicate_user, (
        UserProfile._meta.get_field('user'),
        UserSocialAuth._meta.get_field('user'),
    ))
    duplicate_user.delete()
    if import_email:
        keeper_user.save(update_fields=['email', 'username'])
    keeper.user = keeper_user
    return keeper
