"""Rules for joining and leaving a table, and for bringing guests to it.

These live here rather than in the views because the same rules are enforced
from two entry points — the website and the Telegram Mini App API — and five
security checks silently drifting apart is exactly the failure mode to avoid.

Division of labour: the caller resolves objects (`get_object_or_404`) and
renders the outcome; this module owns the rules and the side effects (Player
rows and the system comments that feed the table timeline).
"""

from collections import namedtuple

from django.utils.translation import gettext_lazy as _

from webapp.models import Comment, CommentType, Membership, Player, Table


class TableActionError(Exception):
    """A table action refused by the rules.

    `code` is for machine consumers (the JSON API), `message` for humans, and
    `level` maps to django.contrib.messages levels so the web views keep
    rendering warnings as warnings and errors as errors.
    """

    def __init__(self, code, message, level='error'):
        super().__init__(message)
        self.code = code
        self.message = message
        self.level = level


# Non-blocking notices produced by an action that still succeeded.
TableActionWarning = namedtuple('TableActionWarning', 'code message')

JoinResult = namedtuple('JoinResult', 'player warnings')


# ── Membership ────────────────────────────────────────────────────────────────

def is_active_member(profile, location):
    return Membership.objects.filter(
        member__location=location,
        member__user_profile=profile,
        status=Membership.ACTIVE,
    ).exists()


def can_manage_roster(profile, table):
    """Who may add or remove *other people* at a table.

    The table's author, superusers, and the staff of whatever hosts the table —
    the location, or the event when it belongs to one (a table has exactly one
    of the two, per the `table_location_xor_event` constraint).

    Distinct from joining or leaving, which is about one's own seat.
    """
    if profile is None:
        return False
    if table.author_id == profile.id or profile.user.is_superuser:
        return True
    if table.location_id:
        location = table.location
        return (location.creator_id == profile.id
                or location.managers.filter(id=profile.id).exists())
    if table.event_id:
        return table.event.is_manager(profile)
    return False


def can_edit_leaderboard(profile, table):
    """Who may reorder a table's leaderboard.

    Superusers always. Everyone else only while the game has a leaderboard and
    the table's leaderboard is editable: the players at the table, plus whoever
    can manage its roster (author, location or event staff).
    """
    if profile is None:
        return False
    if profile.user.is_superuser:
        return True
    if not (table.game_id and table.game.leaderboard_enabled):
        return False
    if table.leaderboard_status != Table.LEADERBOARD_EDITABLE:
        return False
    return (table.player_set.filter(user_profile=profile).exists()
            or can_manage_roster(profile, table))


def _is_location_staff(profile, location):
    return (
        location.creator == profile
        or profile in location.managers.all()
        or profile.user.is_superuser
    )


def _may_join_restricted_location(profile, table):
    location = table.location
    if not location or location.table_join_permission != location.PERM_MEMBERS_ONLY:
        return True
    if _is_location_staff(profile, location):
        return True
    return is_active_member(profile, location)


def _has_overlapping_table(profile, table):
    others = Table.objects.filter(
        event_id=table.event_id, date=table.date, players=profile,
    ).exclude(id=table.id)
    return any(table.overlaps_with(o) for o in others)


# ── Actions ───────────────────────────────────────────────────────────────────

def join_table(profile, table):
    """Add `profile` to `table`. Returns a JoinResult; raises TableActionError."""
    if not profile.is_email_verified:
        raise TableActionError('email_not_verified', 'Verify email to join table.')

    if not table.is_session_active:
        raise TableActionError('table_closed', _('The table is closed. You cannot join.'))

    if not _may_join_restricted_location(profile, table):
        raise TableActionError('members_only', _('This table is reserved for members.'))

    # Already at the table? (avoids hitting the unique constraint with a 500)
    if Player.objects.filter(table=table, user_profile=profile).exists():
        raise TableActionError(
            'already_joined', _('You are already at this table.'), level='warning')

    # Capacity check — guards against direct POSTs bypassing the disabled button
    if not table.unlimited_seats and table.seats_available <= 0:
        raise TableActionError('table_full', _('The table is full.'))

    player = Player.objects.create(user_profile=profile, table=table)
    Comment.objects.create(
        table=table,
        content=f"PLAYER_IN:{profile.nickname}",
        comment_type=CommentType.SYSTEM,
    )

    warnings = []
    if table.event_id and _has_overlapping_table(profile, table):
        warnings.append(TableActionWarning('overlapping_table', _(
            "Heads up: you're also signed up for another table at an overlapping time.")))

    return JoinResult(player=player, warnings=warnings)


def leave_table(profile, table):
    """Remove `profile` from `table`, along with the guests they brought."""
    if not table.is_session_active:
        raise TableActionError('table_closed', _('The table is closed. You cannot leave.'))

    player = Player.objects.filter(user_profile=profile, table=table).first()
    if not player:
        raise TableActionError('not_at_table', _('You are not at this table.'))

    # Cascade-remove guests owned by this user at this table
    guest_players = Player.objects.filter(
        table=table, guest_profile__owner=profile
    ).select_related('guest_profile')
    for gp in guest_players:
        Comment.objects.create(
            table=table,
            content=f"GUEST_REMOVED:{gp.guest_profile.name}",
            comment_type=CommentType.SYSTEM,
        )
    guest_players.delete()

    # System comment before deleting the player, so the timeline keeps the name
    Comment.objects.create(
        table=table,
        content=f"PLAYER_OUT:{profile.nickname}",
        comment_type=CommentType.SYSTEM,
    )
    player.delete()


def add_guest(profile, table, guest):
    """Seat `guest` (owned by `profile`) at `table`. Returns the Player row."""
    if not table.is_session_active:
        raise TableActionError('table_closed', _("The table is closed."))

    # Only players at the table can add guests
    if not Player.objects.filter(table=table, user_profile=profile).exists():
        raise TableActionError('not_at_table', _("Only table players can add guests."))

    if Player.objects.filter(table=table, guest_profile=guest).exists():
        raise TableActionError(
            'guest_already_added', _("This guest is already at the table."), level='warning')

    # NB: unlike join_table this ignores `unlimited_seats`, so guests are refused
    # once an unlimited table passes max_players. Behaviour kept from the
    # original view — it looks like an oversight, but changing it is a decision.
    if table.seats_available <= 0:
        raise TableActionError('table_full', _("The table is full."))

    player = Player.objects.create(table=table, guest_profile=guest)
    Comment.objects.create(
        table=table,
        content=f"GUEST_ADDED:{guest.name}",
        comment_type=CommentType.SYSTEM,
    )
    return player


def remove_guest(profile, table, player):
    """Remove a guest Player row. Returns the guest's name."""
    if not (player.guest_profile.owner == profile
            or can_manage_roster(profile, table)):
        raise TableActionError(
            'forbidden', _("You don't have permission to remove this guest."))

    name = player.guest_profile.name
    player.delete()
    Comment.objects.create(
        table=table,
        content=f"GUEST_REMOVED:{name}",
        comment_type=CommentType.SYSTEM,
    )
    return name
