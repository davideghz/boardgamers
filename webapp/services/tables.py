"""Rules for joining and leaving a table, and for bringing guests to it.

These live here rather than in the views because the same rules are enforced
from two entry points — the website and the Telegram Mini App API — and five
security checks silently drifting apart is exactly the failure mode to avoid.

Division of labour: the caller resolves objects (`get_object_or_404`) and
renders the outcome; this module owns the rules and the side effects (Player
rows and the system comments that feed the table timeline).
"""

import datetime
from collections import namedtuple

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from webapp.models import (
    Comment, CommentType, GameOutcome, Location, Membership, Notification, NotificationType, Player, ResultMode,
    Table,
)


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


def leaderboard_turned_off(table):
    """An event table whose event has switched the leaderboard off: no section, no editing, no notifications."""
    return bool(table.event_id) and not table.event.leaderboard_enabled


def leaderboard_available(table):
    """Whether a table has a leaderboard to fill in: a game and an effective mode other than "none".

    Drives the leaderboard notifications. A "none" table still shows its section
    (with "enable the leaderboard" for whoever may change the mode), and tables
    that already have results always show them (see the table detail view).
    """
    return (bool(table.game_id) and table.effective_result_mode != ResultMode.NONE
            and not leaderboard_turned_off(table))


def reopen_location_leaderboards(location):
    """After a location lengthened its leaderboard window: reopen the tables back inside it.

    Queryset update, so no notifications fire. Shortening the window is left to
    the update_table_status cron, which locks the tables with the usual notice.
    """
    since = timezone.localdate() - datetime.timedelta(days=Location.LEADERBOARD_EDIT_DAYS_MAX + 1)
    tables = Table.objects.filter(
        location=location, status=Table.CLOSED,
        leaderboard_status=Table.LEADERBOARD_NOT_EDITABLE, date__gte=since,
    )
    reopen = []
    for table in tables:
        table.location = location
        if table.computed_leaderboard_status() == Table.LEADERBOARD_EDITABLE:
            reopen.append(table.pk)
    return Table.objects.filter(pk__in=reopen).update(leaderboard_status=Table.LEADERBOARD_EDITABLE)


def sync_legacy_result(table):
    """After positions are written by a legacy path (old endpoint, admin): keep the new fields in sync.

    Legacy paths only record free-for-all rankings, so a table without a mode that
    has positions becomes "ffa" (queryset update: no table signals). Then outcomes
    are recomputed. Positions and scores are never changed.
    """
    if table.result_mode is None and any(
        Table.is_position_set(p) for p in table.player_set.values_list('position', flat=True)
    ):
        Table.objects.filter(pk=table.pk).update(result_mode=ResultMode.FFA)
        table.result_mode = ResultMode.FFA
    table.recompute_outcomes()


def can_change_result_mode(profile, table):
    """Who may change how a table's result is recorded: author, location/event staff, superusers."""
    return can_manage_roster(profile, table)


def _is_competition_ranking(positions):
    """1, 1, 3, 4… : starts at 1, each value repeats the previous (tie) or equals its rank."""
    ordered = sorted(positions)
    return bool(ordered) and ordered[0] == 1 and all(
        p == ordered[i - 1] or p == i + 1 for i, p in enumerate(ordered) if i > 0
    )


def _int_or_none(value, field):
    if value in (None, ''):
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TableActionError('invalid_' + field, _('Invalid value.'))
    return value


def save_table_result(profile, table, data):
    """Validate and store a table result sent by the leaderboard editor.

    `data`: {result_mode, game_outcome, coop_score, players: [{id, team, position, score}]}.
    Every player of the table must be listed. Positions are recomputed server side
    for coop and "the game won"; outcomes always come from Table.recompute_outcomes().
    Notifies the other players once if anything changed. Returns the saved table.
    """
    if not can_edit_leaderboard(profile, table):
        raise TableActionError('forbidden', _('You cannot edit this leaderboard.'))

    mode = data.get('result_mode')
    if mode not in ResultMode.values:
        raise TableActionError('invalid_mode', _('Invalid result mode.'))
    if mode != table.effective_result_mode and not can_change_result_mode(profile, table):
        raise TableActionError('mode_forbidden', _('Only the table author and the managers can change the mode.'))

    game_outcome = data.get('game_outcome') or None
    if game_outcome is not None and game_outcome not in GameOutcome.values:
        raise TableActionError('invalid_outcome', _('Invalid outcome.'))
    coop_score = _int_or_none(data.get('coop_score'), 'coop_score')

    players = {p.pk: p for p in table.player_set.all()}
    rows = data.get('players') or []
    try:
        sent = {int(r['id']): r for r in rows}
    except (KeyError, TypeError, ValueError):
        raise TableActionError('invalid_players', _('Invalid players.'))
    if set(sent) != set(players):
        raise TableActionError('players_changed', _('The players of this table have changed: reload the page.'))

    team_of, position_of, score_of = {}, {}, {}
    for pid, row in sent.items():
        team_of[pid] = str(row.get('team') or '').strip()[:10]
        position_of[pid] = _int_or_none(row.get('position'), 'position')
        score = _int_or_none(row.get('score'), 'score')
        score_of[pid] = 0 if score is None else score  # Player.score is not nullable: 0 = not entered

    if mode == ResultMode.NONE:
        game_outcome, coop_score = None, None
        team_of = dict.fromkeys(players, '')
        position_of = dict.fromkeys(players)
    elif mode == ResultMode.COOP:
        if game_outcome is None:
            raise TableActionError('outcome_required', _('Tell us whether you won or lost.'))
        team_of = dict.fromkeys(players, '')
        # A coop win is a gold medal for everyone; a loss gives no position.
        position_of = dict.fromkeys(players, 1 if game_outcome == GameOutcome.WON else None)
    elif mode == ResultMode.FFA:
        coop_score = None
        team_of = dict.fromkeys(players, '')
        if game_outcome == GameOutcome.LOST:
            position_of = dict.fromkeys(players)
        else:
            game_outcome = None
            if None in position_of.values() or not _is_competition_ranking(position_of.values()):
                raise TableActionError('invalid_positions', _('Invalid positions.'))
    else:  # teams
        game_outcome, coop_score = None, None
        if '' in team_of.values():
            raise TableActionError('team_required', _('Assign a team to every player.'))
        team_position = {}
        for pid, team in team_of.items():
            pos = position_of[pid]
            if pos is None or team_position.setdefault(team, pos) != pos:
                raise TableActionError('invalid_positions', _('Invalid positions.'))
        if len(team_position) < 2:
            raise TableActionError('teams_required', _('At least 2 teams are needed.'))
        if not _is_competition_ranking(team_position.values()):
            raise TableActionError('invalid_positions', _('Invalid positions.'))

    def signature():
        return (table.result_mode, table.game_outcome, table.coop_score,
                sorted((p.pk, p.team, p.position, p.score) for p in players.values()))

    with transaction.atomic():
        before = signature()
        for pid, player in players.items():
            # Player.position is not nullable until the cleanup phase: "no position" is still 99.
            position = position_of[pid] if position_of[pid] is not None else Table.UNSET_POSITION
            player.team, player.position, player.score = team_of[pid], position, score_of[pid]
        Player.objects.bulk_update(list(players.values()), ['team', 'position', 'score'])
        table.result_mode, table.game_outcome, table.coop_score = mode, game_outcome, coop_score
        # queryset update: no table signals (status notifications) fire.
        Table.objects.filter(pk=table.pk).update(
            result_mode=mode, game_outcome=game_outcome, coop_score=coop_score)
        table.recompute_outcomes()
        changed = signature() != before

        if changed:
            recipients = table.players.exclude(id=profile.id)
            Notification.objects.bulk_create([
                Notification(recipient=recipient, notification_type=NotificationType.LEADERBOARD_UPDATED,
                             table=table, location=table.location)
                for recipient in recipients
            ])
    return table


def can_edit_leaderboard(profile, table):
    """Who may fill in a table's leaderboard.

    Nobody on an event table whose event turned the leaderboard off. Otherwise
    superusers always, and everyone else only for tables with a game, while the
    leaderboard is editable: the players at the table, plus whoever can manage
    its roster (author, location or event staff). On a "none" table only the
    latter can actually enable it: save_table_result() refuses mode changes
    from the others.
    """
    if profile is None or leaderboard_turned_off(table):
        return False
    if profile.user.is_superuser:
        return True
    if not table.game_id:
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

    # The exists() check above is racy (double click, two tabs): let the unique
    # constraint decide and report the loser as "already joined" instead of a 500.
    try:
        with transaction.atomic():
            player = Player.objects.create(user_profile=profile, table=table)
    except IntegrityError:
        raise TableActionError(
            'already_joined', _('You are already at this table.'), level='warning')
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
