import json
from pathlib import Path

from django.contrib.postgres.expressions import ArraySubquery
from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import F, OuterRef, Prefetch

from webapp.models import Event, EventDate, EventGame, EventParticipant, Location, Player, Table, UserProfile


def events_for_audit():
    profiles = UserProfile.objects.only('pk').order_by('pk')
    locations = Location.objects.only('pk', 'name').order_by('pk')
    games = EventGame.objects.select_related('game').only('event', 'game__name').prefetch_related(
        Prefetch('sponsor_locations', queryset=locations),
    ).order_by('game_id')
    # A booking is dated evidence only for this person, this event and an actual event day.
    booking_dates = Player.objects.filter(
        user_profile_id=OuterRef('user_profile_id'),
        table__event_id=OuterRef('event_id'),
        table__event__dates__date=F('table__date'),
    ).order_by('table__date').values('table__date').distinct()
    participants = EventParticipant.objects.only('event', 'user_profile').annotate(
        booking_dates=ArraySubquery(booking_dates),
    ).order_by('pk')
    return Event.objects.filter(organizer_location__isnull=True).order_by('pk').prefetch_related(
        Prefetch('dates', queryset=EventDate.objects.order_by('date')),
        Prefetch('tables', queryset=Table.objects.only('event', 'slug', 'date').order_by('pk')),
        Prefetch('managers', queryset=profiles),
        Prefetch('allowed_table_creators', queryset=profiles),
        Prefetch('sponsor_locations', queryset=locations),
        Prefetch('games', queryset=games),
        Prefetch('participants', queryset=participants),
    )


def audit_event(event):
    dates = list(event.dates.all())
    event_days = {day.date for day in dates}
    tables = event.tables.all()
    sponsors = event.sponsor_locations.all()
    return {
        'event_id': event.pk,
        'slug': event.slug,
        'name': event.name,
        'status': event.status,
        # Even a single sponsor is not evidence that they organized the event.
        'mapping': {'organizer_location_id': None, 'classification': None, 'master_slug': None},
        'venue': {
            'name': event.venue_name, 'location_id': event.venue_location_id,
            'address': event.address, 'city': event.city,
            'latitude': event.latitude, 'longitude': event.longitude,
        },
        'creator_profile_id': event.creator_id,
        'manager_profile_ids': [profile.pk for profile in event.managers.all()],
        'table_creator_profile_ids': [profile.pk for profile in event.allowed_table_creators.all()],
        'sponsor_locations': [{'id': location.pk, 'name': location.name} for location in sponsors],
        'dates': [
            {'id': day.pk, 'date': day.date, 'opening_time': day.opening_time, 'closing_time': day.closing_time}
            for day in dates
        ],
        'table_count': len(tables),
        'tables_outside_calendar': [
            {'id': table.pk, 'slug': table.slug, 'date': table.date}
            for table in tables if table.date not in event_days
        ],
        'public_catalog_enabled': event.enable_public_games,
        'catalog': [
            {
                'event_game_id': entry.pk, 'game_id': entry.game_id, 'name': entry.game.name,
                'sponsor_location_ids': [location.pk for location in entry.sponsor_locations.all()],
            }
            for entry in event.games.all()
        ],
        # Legacy registrations have no explicit days. Keep their identity even without a booking.
        'registrations': [
            {'id': participant.pk, 'profile_id': participant.user_profile_id,
             'booking_dates': participant.booking_dates}
            for participant in event.participants.all()
        ],
    }


class Command(BaseCommand):
    help = (
        'Audit legacy events and prepare a JSON mapping for review. All organizer and classification '
        'choices are left blank. Review each as standalone or master_child (with a master_slug). '
        'Apply a reviewed report with map_legacy_events. '
        'Booking dates are evidence from tables, not explicit selections.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--output', metavar='FILE', help='Write clean JSON to this file.')

    def handle(self, *args, **options):
        events = [audit_event(event) for event in events_for_audit().iterator(chunk_size=100)]
        summary = {
            'event_count': len(events),
            'events_with_multiple_sponsors': sum(len(row['sponsor_locations']) > 1 for row in events),
            'tables_outside_calendar': sum(len(row['tables_outside_calendar']) for row in events),
            'registrations_without_booking_dates': sum(
                not entry['booking_dates'] for row in events for entry in row['registrations']
            ),
        }
        report = json.dumps({'summary': summary, 'events': events}, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2)
        if options['output']:
            try:
                Path(options['output']).write_text(report + '\n', encoding='utf-8')
            except OSError as exc:
                raise CommandError(f'Could not write event audit: {exc}') from exc
        else:
            self.stdout.write(report)
