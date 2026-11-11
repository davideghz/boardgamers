from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Exists, OuterRef, Subquery
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from webapp.models import Location, LocationGame, LocationGameLoan, Membership


class GameLoanError(Exception):
    pass


def active_members(location, on_date=None):
    on_date = on_date or timezone.localdate()
    memberships = Membership.objects.filter(
        member_id=OuterRef('pk'), status=Membership.ACTIVE,
        start_date__lte=on_date, end_date__gte=on_date,
    )
    return location.members.filter(Exists(memberships))


def is_active_member(location, profile):
    return bool(profile and active_members(location).filter(user_profile=profile).exists())


def open_game_loans(**filters):
    return LocationGameLoan.objects.filter(returned_at__isnull=True, **filters)


def can_view_game_library(location, *, is_member):
    return location.enable_public_games or (
        is_member and (location.enable_game_loans or open_game_loans(location=location).exists())
    )


def with_game_loan_status(games, *, include_dates=False, include_borrower=False):
    open_loan = open_game_loans(location_game_id=OuterRef('pk'), location_id=OuterRef('location_id')).order_by()
    games = games.annotate(is_on_loan=Exists(open_loan))
    if include_dates:
        games = games.annotate(
            loaned_at=Subquery(open_loan.values('loaned_at')[:1]),
            loan_due_date=Subquery(open_loan.values('due_date')[:1]),
        )
    if include_borrower:
        borrower = open_loan.filter(member__location_id=OuterRef('location_id'))
        games = games.annotate(borrower_nickname=Subquery(borrower.values('member__user_profile__nickname')[:1]))
    return games


def default_loan_due_date(location, on_date=None):
    return (on_date or timezone.localdate()) + timedelta(days=location.game_loan_days)


def get_borrowing_member(location, profile, on_date=None, *, lock=False):
    if not profile or not location.enable_game_loans or not location.enable_member_game_loans:
        raise PermissionDenied
    members = active_members(location, on_date).filter(user_profile=profile)
    if lock:
        members = members.select_for_update()
    members = list(members.order_by('pk')[:2])
    if not members:
        raise PermissionDenied
    if len(members) > 1:
        raise GameLoanError(_('Ask a manager to record this loan. Your account is linked to more than one active member record.'))
    return members[0]


def check_game_loan_availability(location, location_game):
    if not location.enable_game_loans:
        raise GameLoanError(_('Game loans are disabled for this location.'))
    if location_game.is_archived:
        raise GameLoanError(_('This game is archived.'))
    if not location_game.is_lendable:
        raise GameLoanError(_('Only games owned by the location and kept on site can be borrowed.'))
    if open_game_loans(location_game=location_game).exists():
        raise GameLoanError(_('This game is already on loan.'))


@transaction.atomic
def create_game_loan(location, location_game, actor, *, member=None, due_date=None):
    # Read the current settings and lock the library entry before checking availability.
    location = Location.objects.select_for_update().get(pk=location.pk)
    loaned_at = timezone.now()
    today = timezone.localdate(loaned_at)
    if member is None:
        member = get_borrowing_member(location, actor, today, lock=True)
        due_date = None
    elif not location.is_manager(actor):
        raise PermissionDenied
    elif not active_members(location, today).select_for_update().filter(pk=member.pk).exists():
        raise GameLoanError(_('Select a member with a valid membership for this location.'))

    try:
        location_game = LocationGame.objects.select_for_update().get(pk=location_game.pk, location=location)
    except LocationGame.DoesNotExist as exc:
        raise GameLoanError(_('This game is no longer in the library.')) from exc
    check_game_loan_availability(location, location_game)

    due_date = due_date or default_loan_due_date(location, today)
    if due_date < today:
        raise GameLoanError(_('The due date cannot be before the loan date.'))
    return LocationGameLoan.objects.create(
        location=location, location_game=location_game, member=member,
        loaned_at=loaned_at, due_date=due_date, loaned_by=actor,
    )


@transaction.atomic
def return_game_loan(location, loan, actor):
    if not location.is_manager(actor):
        raise PermissionDenied
    loan = LocationGameLoan.objects.select_for_update().get(pk=loan.pk, location=location)
    if loan.returned_at is not None:
        return False
    loan.returned_at = timezone.now()
    loan.returned_by = actor
    loan.save(update_fields=['returned_at', 'returned_by', 'updated_at'])
    return True
