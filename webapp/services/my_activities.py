"""The user's own tables, events and festivals: My activities lists them, the home shows the
next ones. One query for both, so the two never disagree."""
from collections import namedtuple

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from webapp.models import (
    Event, EventDate, EventParticipant, EventParticipantDate, Location, MasterEvent, MasterEventDate,
    MasterEventDateParticipant, Player, Table,
)
from webapp.services.appointments import paginate_appointments, with_matching_day

MyActivities = namedtuple('MyActivities', 'sources locations')


def my_activities(user, *, past=False, organizer=False, activity_type='all', venue='', query=''):
    """The sources for paginate_appointments ('table', 'event', 'manifestation' querysets) and
    the locations they happen at, for the venue filter."""
    profile = user.user_profile
    today = timezone.localdate()
    period = {'date__lt' if past else 'date__gte': today}

    # The tables the user plays at or created (My tables lives here now, plan E5)
    playing = Exists(Player.objects.filter(table_id=OuterRef('pk'), user_profile=profile))
    my_tables = Table.objects.visible_to(user).filter(playing | Q(author=profile))
    registrations = EventParticipant.objects.filter(event_id=OuterRef('pk'), user_profile=profile)
    attending = Exists(registrations) | Exists(my_tables.filter(event_id=OuterRef('pk')))
    my_events = Event.objects.filter(attending)
    if not user.is_superuser:
        my_events = my_events.filter(Q(status=Event.PUBLISHED) | Q(pk__in=Event.objects.managed_by(profile)))

    # Festivals: the published ones the user signed up for, on their days, and the ones they run
    # (drafts too), on every day. Few people run one, unlike events: they are listed without the filter.
    festival_days = MasterEventDateParticipant.objects.filter(user_profile=profile)
    attending_festival = Exists(festival_days.filter(master_event_date__master_event_id=OuterRef('pk')))
    managed_festivals = MasterEvent.objects.filter(managers=profile)
    runs_festival = Q(pk__in=managed_festivals.values('pk'))
    my_festivals = MasterEvent.objects.filter(runs_festival | (Q(status=Event.PUBLISHED) & attending_festival))

    locations = Location.objects.filter(
        Q(pk__in=my_tables.order_by().values('location_id'))
        | Q(pk__in=my_tables.order_by().values('event__venue_location_id'))
        | Q(pk__in=my_events.order_by().values('venue_location_id'))
        | Q(pk__in=my_festivals.order_by().values('venue_location_id')),
    ).order_by('name', 'pk')

    tables = my_tables.filter(**period)
    # Registrations without a day nor a table: a day inferred from a cancelled booking is not a choice.
    undated = EventParticipant.objects.filter(user_profile=profile).exclude(
        selected_dates__inferred_from_booking=False,
    ).exclude(Exists(my_tables.filter(event_id=OuterRef('event_id'))))
    # They follow the event's own days: its next one, or its last one once the event is over.
    event_days = Exists(undated.filter(event_id=OuterRef('event_id')))
    if past:
        event_days &= ~Exists(EventDate.objects.filter(event_id=OuterRef('event_id'), date__gte=today))
    dates = EventDate.objects.filter(event_id=OuterRef('pk'), **period).filter(
        Exists(EventParticipantDate.objects.filter(
            event_date_id=OuterRef('pk'), participant__user_profile=profile, inferred_from_booking=False,
        )) | Exists(my_tables.filter(event_id=OuterRef('event_id'), date=OuterRef('date'))) | event_days,
    )
    # Events without any day stay in the upcoming tab, after dated activities.
    events = with_matching_day(
        my_events, dates, newest_first=past,
        undated=None if past else undated.filter(event_id=OuterRef('pk'), event__dates__isnull=True),
    )
    festivals = with_matching_day(my_festivals, MasterEventDate.objects.filter(
        master_event_id=OuterRef('pk'), **period,
    ).filter(Q(participants__user_profile=profile) | Q(master_event__managers=profile)), newest_first=past)
    if organizer:
        # Organized by me: the tables I created, the events I run or proposed (a member's proposal
        # waits as a draft for the location's managers), the festivals I run
        tables = tables.filter(author=profile)
        proposed = Q(creator=profile) & ~Q(status=Event.BLOCKED)
        events = with_matching_day(
            Event.objects.filter(Q(pk__in=Event.objects.managed_by(profile).values('pk')) | proposed),
            EventDate.objects.filter(event_id=OuterRef('pk'), **period), newest_first=past,
        )
        festivals = with_matching_day(
            managed_festivals, MasterEventDate.objects.filter(master_event_id=OuterRef('pk'), **period),
            newest_first=past,
        )
    if venue:
        tables = tables.filter(Q(location__slug=venue) | Q(event__venue_location__slug=venue))
        events = events.filter(venue_location__slug=venue)
        festivals = festivals.filter(venue_location__slug=venue)
    if query:
        tables = tables.filter(Q(title__icontains=query) | Q(description__icontains=query)
                               | Q(game__name__icontains=query) | Q(event__name__icontains=query))
        events = events.filter(Q(name__icontains=query) | Q(description__icontains=query))
        festivals = festivals.filter(Q(name__icontains=query) | Q(description__icontains=query))

    sources = {}
    if activity_type != 'events':
        sources['table'] = tables.annotate(playing=playing).select_related(
            'author', 'location', 'game', 'event__venue_location', 'event__organizer_location', 'event__master_event',
        )
    if activity_type != 'tables':
        sources['event'] = events.annotate(attending=attending).select_related(
            'organizer_location', 'venue_location', 'master_event')
        # Festivals go with the events: My activities has no tab of their own for them
        sources['manifestation'] = festivals.annotate(attending=attending_festival).select_related('venue_location')
    return MyActivities(sources, locations)


def next_activities(user, count):
    """The first `count` upcoming rows of My activities, as (kind, item), and whether there are more."""
    _page, items = paginate_appointments(my_activities(user).sources, 1, newest_first=False, per_page=count + 1)
    return items[:count], len(items) > count
