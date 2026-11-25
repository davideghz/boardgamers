import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from webapp.models import Event, EventParticipantDate, Location, MasterEvent, Player, Sponsor


def valid_id(value):
    return type(value) is int and 0 < value < 2**63


def read_mappings(path):
    try:
        rows = json.loads(Path(path).read_text(encoding='utf-8'))['events']
        if not isinstance(rows, list):
            raise TypeError
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise CommandError('Expected the JSON report produced by audit_legacy_events.') from exc
    ids = set()
    for row in rows:
        if not (isinstance(row, dict) and valid_id(row.get('event_id')) and isinstance(row.get('slug'), str)
                and row['slug'] and isinstance(row.get('mapping'), dict)):
            raise CommandError('Each row must contain a positive event_id, its audit slug and a mapping object.')
        if row['event_id'] in ids:
            raise CommandError(f"Duplicate event ID {row['event_id']}.")
        ids.add(row['event_id'])
    return sorted(rows, key=lambda row: row['event_id'])


def validate(row, event, masters):
    mapping = row['mapping']
    organizer_id = mapping.get('organizer_location_id')
    venue_id = mapping.get('venue_location_id')
    venue_name = mapping.get('venue_name', event.venue_name)
    classification = mapping.get('classification')
    slug = mapping.get('master_slug')
    if row['slug'] != event.slug:
        raise ValueError('Event slug changed since the audit.')
    if not valid_id(organizer_id) or not Location.objects.filter(pk=organizer_id).exists():
        raise ValueError('Choose an existing organizer_location_id.')
    if venue_id is not None and (not valid_id(venue_id) or not Location.objects.filter(pk=venue_id).exists()):
        raise ValueError('venue_location_id must identify a registered location.')
    if not isinstance(venue_name, str) or len(venue_name) > 255:
        raise ValueError('venue_name must be a string of up to 255 characters.')
    if classification not in ('standalone', 'master_child') or (
            classification == 'standalone' and slug not in (None, '')):
        raise ValueError('Choose standalone or master_child with an existing master_slug.')
    if classification == 'master_child' and (not isinstance(slug, str) or slug not in masters):
        raise ValueError('The master_slug does not identify a manifestation.')
    master = masters[slug] if classification == 'master_child' else None
    master_id = master.pk if master else None
    if event.organizer_location_id:
        venue_conflict = ('venue_location_id' in mapping and event.venue_location_id != venue_id) or (
            'venue_name' in mapping and event.venue_name != venue_name)
        if event.organizer_location_id != organizer_id or event.master_event_id != master_id or venue_conflict:
            raise ValueError('Event has already been assigned with different values.')
        return None

    date_ids = dict(event.dates.values_list('date', 'pk'))
    missing = list(event.tables.exclude(date__in=date_ids).order_by('pk').values_list('pk', 'date'))
    if missing:
        details = ', '.join(f'#{pk} ({day.isoformat()})' for pk, day in missing)
        raise ValueError(f'Tables outside the event calendar: {details}. Fix their dates or add the corresponding days.')
    if master:
        if event.is_published and (not master.is_published or not master.approved_at):
            raise ValueError('A public legacy event needs an admin-approved manifestation.')
        unmatched = sorted(date_ids.keys() - set(master.dates.values_list('date', flat=True)))
        if unmatched:
            raise ValueError(f'Days outside the manifestation calendar: {", ".join(day.isoformat() for day in unmatched)}.')

    return {
        'organizer_location_id': organizer_id,
        'venue_location_id': venue_id if 'venue_location_id' in mapping else event.venue_location_id,
        'venue_name': venue_name,
        'master_event_id': master_id,
        'catalog_mode': Event.CATALOG_SELECTED,
    }


def reconstruct_dates(event):
    participants = dict(event.participants.values_list('user_profile_id', 'pk'))
    day_ids = dict(event.dates.values_list('date', 'pk'))
    bookings = Player.objects.filter(table__event=event, table__date__in=day_ids, user_profile_id__in=participants)
    EventParticipantDate.objects.bulk_create([
        EventParticipantDate(participant_id=participants[person], event_date_id=day_ids[day], inferred_from_booking=True)
        for person, day in bookings.order_by().values_list('user_profile_id', 'table__date').distinct()
    ], ignore_conflicts=True)


def link_sponsors(locations, master):
    for location in locations:
        sponsor = Sponsor.objects.filter(location=location).order_by('pk').first()
        if sponsor is None:
            website = location.website or ''
            try:
                Sponsor._meta.get_field('website').run_validators(website)
            except ValidationError:
                website = ''
            sponsor = Sponsor.objects.create(location=location, name=location.name,
                                             logo=location.cover.name if location.cover else '',
                                             website=website)
        master.sponsors.add(sponsor)


class Command(BaseCommand):
    help = ('Validate a reviewed audit_legacy_events report. By default performs a dry run. '
            'Use --apply to write the assignments atomically. Existing events keep their IDs, '
            'URLs and publication status. Optional mapping keys: venue_location_id and venue_name.')
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('mapping_file')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--require-complete', action='store_true',
                            help='Fail if the report omits any event that still needs an organizer.')

    @transaction.atomic
    def handle(self, *args, **options):
        rows = read_mappings(options['mapping_file'])
        ids = [row['event_id'] for row in rows]
        slugs = {row['mapping']['master_slug'] for row in rows if isinstance(row['mapping'].get('master_slug'), str)}
        events = Event.objects.filter(pk__in=ids).order_by('pk')
        masters = MasterEvent.objects.filter(slug__in=slugs).order_by('pk')
        if options['apply']:
            events = events.select_for_update()
            masters = masters.select_for_update()
        events = {event.pk: event for event in events}
        masters = {master.slug: master for master in masters}
        errors = []
        changes = []
        for row in rows:
            pk = row['event_id']
            if pk not in events:
                errors.append(f'Event {pk} no longer exists.')
                continue
            try:
                values = validate(row, events[pk], masters)
            except ValueError as exc:
                errors.append(f'Event {pk}: {exc}')
            else:
                if values:
                    changes.append((events[pk], row['mapping'].get('master_slug'), values))
        unmapped = list(Event.objects.filter(organizer_location__isnull=True).exclude(pk__in=ids)
                        .order_by('pk').values_list('pk', flat=True))
        if unmapped and options['require_complete']:
            errors.append(f'Events missing from the mapping: {unmapped}.')
        if errors:
            raise CommandError('\n'.join(errors))
        if options['apply']:
            sponsor_ids = {
                event.pk: list(event.sponsor_locations.values_list('pk', flat=True))
                for event, slug, _ in changes if slug
            }
            # A sponsor location can be shared across independently migrated batches.
            location_ids = {pk for ids in sponsor_ids.values() for pk in ids}
            locations = Location.objects.select_for_update(no_key=True).filter(pk__in=location_ids).order_by('pk')
            sponsor_locations = {location.pk: location for location in locations}
            if location_ids - sponsor_locations.keys():
                raise CommandError('A legacy sponsor location was removed while applying the mapping. Run a new audit.')
            for event, slug, values in changes:
                # The slug and legacy relations stay attached to the same record.
                Event.objects.filter(pk=event.pk).update(**values)
                reconstruct_dates(event)
                if slug:
                    link_sponsors([sponsor_locations[pk] for pk in sponsor_ids[event.pk]], masters[slug])
        mode = 'Applied' if options['apply'] else 'Dry run'
        self.stdout.write(f'{mode}: {len(changes)} assignment(s), {len(rows) - len(changes)} already assigned, '
                          f'{len(unmapped)} unassigned event(s) outside the report.')
        for event, slug, values in changes:
            destination = f'manifestation {slug}' if slug else 'standalone'
            self.stdout.write(f'  {event.pk} ({event.slug}): {destination}, organizer #{values["organizer_location_id"]}')
        if unmapped:
            self.stdout.write(f'Events missing from the mapping: {unmapped}.')
