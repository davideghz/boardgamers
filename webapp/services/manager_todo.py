"""What waits for the managers of some locations: pending membership requests, venue layout
requests, draft events, and published events open to table booking that have no table yet.

Used by the home page's to-do module; the management pages (plan G1, G2) reuse it.
"""
from collections import namedtuple

from django.db.models import Count, Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from webapp.models import Event, EventDate, Location, Membership

TodoItem = namedtuple('TodoItem', 'key count location url')

MEMBERSHIP_REQUESTS = 'membership_requests'
LAYOUT_REQUESTS = 'layout_requests'
DRAFT_EVENTS = 'draft_events'
EVENTS_WITHOUT_TABLES = 'events_without_tables'


def manager_todo(location_ids):
    """TodoItems for the locations in `location_ids`, one per location and kind, in this
    order: membership requests, layout requests, drafts, events without tables."""
    if not location_ids:
        return []
    today = timezone.localdate()
    counts = {
        MEMBERSHIP_REQUESTS: Membership.objects.filter(
            member__location_id__in=location_ids, status=Membership.PENDING,
        ).values_list('member__location_id').annotate(n=Count('pk')),
        LAYOUT_REQUESTS: Event.objects.filter(
            venue_layout_requested_from_id__in=location_ids, venue_layout_approved=False,
        ).values_list('venue_layout_requested_from_id').annotate(n=Count('pk')),
        DRAFT_EVENTS: Event.objects.filter(
            organizer_location_id__in=location_ids, status=Event.DRAFT,
        ).values_list('organizer_location_id').annotate(n=Count('pk')),
        # Only events that ask for tables: an evening without tables is a choice, not a gap.
        EVENTS_WITHOUT_TABLES: Event.objects.filter(
            organizer_location_id__in=location_ids, status=Event.PUBLISHED, table_booking_enabled=True,
            tables__isnull=True,
        ).filter(Exists(EventDate.objects.filter(event_id=OuterRef('pk'), date__gte=today)))
        .values_list('organizer_location_id').annotate(n=Count('pk', distinct=True)),
    }
    rows = [(key, location_id, n) for key, query in counts.items() for location_id, n in query if n]
    if not rows:
        return []
    locations = Location.objects.in_bulk({location_id for _key, location_id, _n in rows})
    url_names = {
        MEMBERSHIP_REQUESTS: 'location-manage-members', LAYOUT_REQUESTS: 'location-venue-layout-requests',
        DRAFT_EVENTS: 'location-manage-events', EVENTS_WITHOUT_TABLES: 'location-manage-events',
    }
    return [
        TodoItem(key, n, locations[location_id], reverse(url_names[key], args=[locations[location_id].slug]))
        for key, location_id, n in sorted(rows, key=lambda row: (list(counts).index(row[0]),
                                                                 locations[row[1]].name.lower()))
    ]
