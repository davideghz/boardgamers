"""What waits for the managers of some locations: pending membership requests, venue layout
requests, draft events, and published events open to table booking that have no table yet.

Used by the home page's to-do module; the management pages (plan G1, G2) reuse it.
"""
from collections import namedtuple

from django.db.models import Count, Exists, IntegerField, OuterRef, Subquery
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse
from django.utils import timezone

from webapp.models import Event, EventDate, Location, Membership

TodoItem = namedtuple('TodoItem', 'key count location url')

MEMBERSHIP_REQUESTS = 'membership_requests'
LAYOUT_REQUESTS = 'layout_requests'
DRAFT_EVENTS = 'draft_events'
EVENTS_WITHOUT_TABLES = 'events_without_tables'


def _count(queryset, field):
    """Rows of `queryset` pointing at the outer location through `field`, as a subquery."""
    counted = (queryset.filter(**{field: OuterRef('pk')}).order_by().values(field)
               .annotate(n=Count('pk', distinct=True)).values('n')[:1])
    return Coalesce(Subquery(counted, output_field=IntegerField()), 0)


def manager_todo(location_ids):
    """TodoItems for the locations in `location_ids`, one per location and kind, in this
    order: membership requests, layout requests, drafts, events without tables. One query."""
    if not location_ids:
        return []
    today = timezone.localdate()
    upcoming = Exists(EventDate.objects.filter(event_id=OuterRef('pk'), date__gte=today))
    counts = {
        MEMBERSHIP_REQUESTS: _count(Membership.objects.filter(status=Membership.PENDING), 'member__location_id'),
        LAYOUT_REQUESTS: _count(Event.objects.filter(venue_layout_approved=False), 'venue_layout_requested_from_id'),
        DRAFT_EVENTS: _count(Event.objects.filter(status=Event.DRAFT), 'organizer_location_id'),
        # Only events that ask for tables: an evening without tables is a choice, not a gap.
        EVENTS_WITHOUT_TABLES: _count(Event.objects.filter(
            upcoming, status=Event.PUBLISHED, table_booking_enabled=True, tables__isnull=True,
        ), 'organizer_location_id'),
    }
    locations = Location.objects.filter(pk__in=location_ids).annotate(**counts).order_by(Lower('name'), 'pk')
    url_names = {
        MEMBERSHIP_REQUESTS: 'location-manage-members', LAYOUT_REQUESTS: 'location-venue-layout-requests',
        DRAFT_EVENTS: 'location-manage-events', EVENTS_WITHOUT_TABLES: 'location-manage-events',
    }
    queries = {DRAFT_EVENTS: {'show': 'drafts'}}  # the drafts tab of the organized events (plan G3)
    items = [TodoItem(key, getattr(location, key), location,
                      reverse(url_names[key], args=[location.slug], query=queries.get(key)))
             for location in locations for key in counts if getattr(location, key)]
    return sorted(items, key=lambda item: list(counts).index(item.key))  # stable: by kind, then name
