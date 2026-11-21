from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import transaction
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


@transaction.atomic
def merge_profiles(keeper_id, duplicate_id):
    profiles = {
        profile.pk: profile for profile in
        UserProfile.objects.select_for_update().filter(pk__in=(keeper_id, duplicate_id)).order_by('pk')
    }
    if len(profiles) != 2:
        raise ValidationError(_("Select two different profiles that still exist."))
    keeper, duplicate = profiles[keeper_id], profiles[duplicate_id]
    users = {
        user.pk: user for user in
        User.objects.select_for_update().filter(pk__in=(keeper.user_id, duplicate.user_id)).order_by('pk')
    }
    keeper_user, duplicate_user = users[keeper.user_id], users[duplicate.user_id]
    validate_accounts(keeper_user, duplicate_user)
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

    # Refuse to delete the account if a new profile relation lacks a merge rule.
    for relation in UserProfile._meta.get_fields(include_hidden=True):
        if relation.auto_created and (relation.one_to_many or relation.one_to_one):
            if relation.related_model._base_manager.filter(**{relation.field.name: duplicate}).exists():
                raise ValidationError(_("The duplicate still has linked records that could not be transferred."))

    UserSocialAuth.objects.filter(user=duplicate_user).update(user=keeper_user)
    duplicate_user.delete()
    return keeper
