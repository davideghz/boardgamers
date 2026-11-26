"""Who is looking at the page: the user's roles and relation to each location, computed
once per request and only when a page asks.

Views get it with `get_viewer(request)`; templates read `viewer` (see
context_processors.viewer) and `{% location_relation location as rel %}`. Every fact is a
cached set, so asking about many locations costs one query per fact, not per location.
"""
from collections import namedtuple

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.functional import cached_property

from webapp.models import (
    Event, EventParticipant, Location, LocationFollower, Membership, Player, Table,
)

Participations = namedtuple('Participations', 'table_ids event_ids')

# Relations of a viewer to a location, strongest first.
MANAGER, MEMBER, PENDING, FOLLOWER, VISITOR, ANONYMOUS = (
    'manager', 'member', 'pending', 'follower', 'visitor', 'anonymous')


class Viewer:
    def __init__(self, user, *, as_visitor=False):
        self.user = user
        self.profile = user.user_profile if user.is_authenticated else None
        self._as_visitor = as_visitor

    @property
    def is_authenticated(self):
        return self.profile is not None

    # ── Locations ────────────────────────────────────────────────────────────

    @cached_property
    def _ties(self):
        """Every location the user has a tie with, and which ties, in one query."""
        empty = {'created': frozenset(), 'managed': frozenset(), 'member': frozenset(),
                 'pending': frozenset(), 'followed': frozenset()}
        if not self.profile:
            return empty
        profile = self.profile
        managed = Exists(Location.managers.through.objects.filter(location_id=OuterRef('pk'), userprofile_id=profile.pk))
        member = Exists(Membership.active_for(profile).filter(member__location_id=OuterRef('pk')))
        pending = Exists(Membership.objects.filter(
            member__location_id=OuterRef('pk'), member__user_profile=profile, status=Membership.PENDING))
        followed = Exists(LocationFollower.objects.filter(location_id=OuterRef('pk'), user_profile=profile))
        rows = (Location.objects
                .annotate(is_manager=managed, is_member=member, is_pending=pending, is_followed=followed)
                .filter(Q(creator=profile) | Q(is_manager=True) | Q(is_member=True)
                        | Q(is_pending=True) | Q(is_followed=True))
                .values_list('pk', 'creator_id', 'is_manager', 'is_member', 'is_pending', 'is_followed'))
        ties = {key: set() for key in empty}
        for pk, creator_id, is_manager, is_member, is_pending, is_followed in rows:
            if creator_id == profile.pk:
                ties['created'].add(pk)
            for key, flag in (('managed', is_manager or creator_id == profile.pk), ('member', is_member),
                              ('pending', is_pending), ('followed', is_followed)):
                if flag:
                    ties[key].add(pk)
        return {key: frozenset(ids) for key, ids in ties.items()}

    @property
    def created_location_ids(self):
        return self._ties['created']

    @property
    def managed_location_ids(self):
        """Created or managed."""
        return self._ties['managed']

    @property
    def member_location_ids(self):
        """Where a membership covers today."""
        return self._ties['member']

    @property
    def pending_location_ids(self):
        """Where a membership request waits for approval."""
        return self._ties['pending']

    @property
    def followed_location_ids(self):
        return self._ties['followed']

    @property
    def own_location_ids(self):
        """The locations the user has a tie with: run, joined as a member, or followed."""
        return self.managed_location_ids | self.member_location_ids | self.followed_location_ids

    @property
    def sees_as_visitor(self):
        """?as=visitor, honored only for managers: they preview their location as a visitor."""
        return self._as_visitor and bool(self.managed_location_ids)

    def relation(self, location):
        if not self.profile:
            return ANONYMOUS
        pk = location.pk
        if self.sees_as_visitor:
            return VISITOR
        if pk in self.managed_location_ids:
            return MANAGER
        if pk in self.member_location_ids:
            return MEMBER
        if pk in self.pending_location_ids:
            return PENDING
        if pk in self.followed_location_ids:
            return FOLLOWER
        return VISITOR

    # Same rules as Location.*_access, from the cached sets (real permissions: ?as=visitor
    # only changes what the page shows).
    def _access(self, location, permission):
        pk = location.pk
        if pk in self.member_location_ids:
            membership = Membership.ACTIVE
        elif pk in self.pending_location_ids:
            membership = Membership.PENDING
        else:
            membership = None
        is_manager = pk in self.managed_location_ids
        return Location.decide_access(
            permission, signed_in=self.is_authenticated, is_manager=is_manager,
            membership=None if is_manager else membership,
            is_superuser=self.user.is_superuser,
        )

    def table_creation_access(self, location):
        return self._access(location, location.table_creation_permission)

    def table_join_access(self, location):
        return self._access(location, location.table_join_permission)

    def event_creation_access(self, location):
        return self._access(location, location.event_creation_permission)

    def event_join_access(self, location):
        return self._access(location, location.event_join_permission)

    # ── Activity ─────────────────────────────────────────────────────────────

    @cached_property
    def upcoming_participations(self):
        """The upcoming tables the user plays at and the published events they joined."""
        if not self.profile:
            return Participations(frozenset(), frozenset())
        today = timezone.localdate()
        tables = Table.objects.visible_to(self.user).filter(players=self.profile, date__gte=today)
        events = Event.objects.filter(
            participants__user_profile=self.profile, status=Event.PUBLISHED, dates__date__gte=today)
        return Participations(frozenset(tables.values_list('pk', flat=True)),
                              frozenset(events.values_list('pk', flat=True)))

    @cached_property
    def manages_events(self):
        return bool(self.profile) and Event.objects.managed_by(self.profile).exists()

    @cached_property
    def has_activity(self):
        """Ever joined a table or an event."""
        return bool(self.profile) and (
            Player.objects.filter(user_profile=self.profile).exists()
            or EventParticipant.objects.filter(user_profile=self.profile).exists())


def get_viewer(request):
    """The request's Viewer, created on first use and shared by the view and its templates."""
    viewer = getattr(request, '_viewer', None)
    if viewer is None:
        viewer = request._viewer = Viewer(request.user, as_visitor=request.GET.get('as') == 'visitor')
    return viewer
