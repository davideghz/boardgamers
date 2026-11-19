import json
from datetime import date, time
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventGame, EventParticipant, Player, Table


class LegacyEventAuditTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory()
        cls.manager = UserProfileFactory()
        cls.first_sponsor = LocationFactory()
        cls.second_sponsor = LocationFactory()
        cls.event = Event.objects.create(
            name='Fiera', status=Event.PUBLISHED, creator=cls.owner, city='Vicenza',
            address='Via della Fiera 1', enable_public_games=True,
        )
        cls.event.managers.add(cls.manager)
        cls.event.allowed_table_creators.add(cls.owner)
        cls.event.sponsor_locations.add(cls.second_sponsor, cls.first_sponsor)
        cls.friday = date(2030, 4, 5)
        cls.saturday = date(2030, 4, 6)
        cls.sunday = date(2030, 4, 7)
        EventDate.objects.create(event=cls.event, date=cls.sunday)
        cls.day = EventDate.objects.create(event=cls.event, date=cls.friday,
                                           opening_time=time(20), closing_time=time(1))
        cls.title = GameFactory()
        cls.entry = EventGame.objects.create(event=cls.event, game=cls.title)
        cls.entry.sponsor_locations.add(cls.second_sponsor)
        friday_table = Table.objects.create(event=cls.event, date=cls.friday)
        other_friday_table = Table.objects.create(event=cls.event, date=cls.friday)
        cls.off_calendar = Table.objects.create(event=cls.event, date=cls.saturday)
        cls.other = Event.objects.create(name='Altra fiera', status=Event.BLOCKED)
        cls.other.sponsor_locations.add(cls.first_sponsor)
        EventDate.objects.create(event=cls.other, date=cls.sunday)
        foreign_table = Table.objects.create(event=cls.other, date=cls.sunday)
        standalone_table = Table.objects.create(location=cls.first_sponsor, date=cls.sunday)

        cls.with_booking = EventParticipant.objects.create(event=cls.event, user_profile=cls.owner)
        cls.undated = EventParticipant.objects.create(event=cls.event, user_profile=cls.manager)
        Player.objects.bulk_create([
            Player(table=friday_table, user_profile=cls.owner),
            Player(table=other_friday_table, user_profile=cls.owner),
            Player(table=cls.off_calendar, user_profile=cls.manager),
            Player(table=foreign_table, user_profile=cls.manager),
            Player(table=standalone_table, user_profile=cls.manager),
        ])

    def audit(self):
        output = StringIO()
        call_command('audit_legacy_events', stdout=output)
        return output.getvalue()

    def test_inventory_preserves_evidence_and_leaves_the_mapping_open(self):
        report = json.loads(self.audit())
        event, other = report['events']
        self.assertEqual([event['event_id'], other['event_id']], [self.event.pk, self.other.pk])
        self.assertEqual([event['status'], other['status']], [Event.PUBLISHED, Event.BLOCKED])
        self.assertEqual(event['creator_profile_id'], self.owner.pk)
        self.assertEqual(event['manager_profile_ids'], [self.manager.pk])
        self.assertEqual(event['table_creator_profile_ids'], [self.owner.pk])
        self.assertEqual(event['venue']['city'], 'Vicenza')
        self.assertEqual(event['sponsor_locations'], [
            {'id': sponsor.pk, 'name': sponsor.name} for sponsor in (self.first_sponsor, self.second_sponsor)
        ])
        self.assertEqual(event['catalog'], [{
            'event_game_id': self.entry.pk, 'game_id': self.title.pk, 'name': self.title.name,
            'sponsor_location_ids': [self.second_sponsor.pk],
        }])
        self.assertIs(event['public_catalog_enabled'], True)
        for row in (event, other):
            self.assertEqual(row['mapping'], {'organizer_location_id': None, 'classification': None, 'master_slug': None})
        self.assertEqual(report['summary']['events_with_multiple_sponsors'], 1)

    def test_calendar_and_registration_evidence_are_scoped_to_the_event(self):
        report = json.loads(self.audit())
        event = report['events'][0]
        self.assertEqual([day['date'] for day in event['dates']], [str(self.friday), str(self.sunday)])
        self.assertEqual(event['dates'][0], {
            'id': self.day.pk, 'date': str(self.friday), 'opening_time': '20:00:00', 'closing_time': '01:00:00',
        })
        self.assertEqual(event['table_count'], 3)
        self.assertEqual(event['tables_outside_calendar'], [
            {'id': self.off_calendar.pk, 'slug': self.off_calendar.slug, 'date': str(self.saturday)},
        ])
        self.assertEqual(event['registrations'], [
            {'id': self.with_booking.pk, 'profile_id': self.owner.pk, 'booking_dates': [str(self.friday)]},
            {'id': self.undated.pk, 'profile_id': self.manager.pk, 'booking_dates': []},
        ])
        self.assertEqual(report['summary']['registrations_without_booking_dates'], 1)
        self.assertEqual(report['summary']['tables_outside_calendar'], 1)

    def test_output_is_repeatable_and_queries_are_read_only(self):
        with CaptureQueriesContext(connection) as queries:
            first = self.audit()
        for query in queries:
            self.assertIn(query['sql'].lstrip().split()[0].upper(), {'SELECT', 'DECLARE'})
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'mapping.json'
            call_command('audit_legacy_events', '--output', str(output))
            self.assertEqual(output.read_text(encoding='utf-8'), first)

    def test_undated_draft_with_no_relations_is_reviewable(self):
        empty = Event.objects.create(name='Unscheduled')
        audit = json.loads(self.audit())['events'][-1]
        self.assertEqual(audit['event_id'], empty.pk)
        self.assertEqual(audit['status'], Event.DRAFT)
        self.assertEqual(audit['dates'], [])
        self.assertEqual(audit['catalog'], [])
        self.assertEqual(audit['registrations'], [])
