from datetime import time, timedelta

from django.contrib.messages import WARNING, get_messages
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, PhysicalTable, Table
from webapp.services.station_conflicts import station_conflict_ids


class StationConflictTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory(preferred_language='it')
        cls.location = LocationFactory(creator=cls.manager)
        cls.event = Event.objects.create(
            name='Night event', status=Event.PUBLISHED, organizer_location=cls.location,
            venue_location=cls.location,
        )
        cls.day = timezone.localdate() + timedelta(days=3)
        cls.previous_day = cls.day - timedelta(days=1)
        for day in (cls.previous_day, cls.day):
            EventDate.objects.create(event=cls.event, date=day)
        cls.event_station = PhysicalTable.objects.create(event=cls.event, name='Station 1')
        cls.location_station = PhysicalTable.objects.create(location=cls.location, name='Station 1')

    def table(self, title, *, station, starts, day=None, duration=120, event=None):
        return Table.objects.create(
            title=title, event=event, location=None if event else self.location,
            author=self.manager, physical_table=station, date=day or self.day, time=starts, duration=duration,
        )

    def test_shared_station_uses_full_intervals_and_ignores_abutting_slots(self):
        night = self.table('Overnight', station=self.event_station, starts=time(23, 30),
                           day=self.previous_day, duration=90, event=self.event)
        overlap = self.table('Early game', station=self.event_station, starts=time(0, 30),
                             duration=30, event=self.event)
        adjacent = self.table('Next game', station=self.event_station, starts=time(1), event=self.event)
        same_name = self.table('Separate station', station=self.location_station, starts=time(0, 30))

        self.assertEqual(station_conflict_ids([night, overlap, adjacent, same_name]), {night.pk, overlap.pk})

    def test_a_long_session_can_overlap_two_days_after_it_started(self):
        self.table('Long game', station=self.location_station, starts=time(22),
                   day=self.day - timedelta(days=2), duration=27 * 60)
        early = self.table('Early game', station=self.location_station, starts=time(0, 30))

        self.assertEqual(station_conflict_ids([early]), {early.pk})

    def test_the_check_takes_a_single_query(self):
        tables = [self.table(f'Game {i}', station=self.location_station, starts=time(20)) for i in range(5)]

        with self.assertNumQueries(1):
            self.assertEqual(station_conflict_ids(tables), {table.pk for table in tables})

    def test_assignment_detects_an_overnight_session_from_another_schedule(self):
        regular = self.table('Location game', station=None, starts=time(0, 30))
        event_table = self.table('Event game', station=self.location_station, starts=time(23, 30),
                                 day=self.previous_day, event=self.event)
        self.client.force_login(self.manager.user)
        assignment = reverse('location-manage-station-assignment', args=[self.location.slug])

        result = self.client.post(assignment, {'table': regular.pk, 'physical_table': self.location_station.pk})

        self.assertEqual(result.status_code, 302)
        self.assertIn(WARNING, [message.level for message in get_messages(result.wsgi_request)])
        regular.refresh_from_db()
        self.assertEqual(regular.physical_table, self.location_station)
        response = self.client.get(assignment)
        self.assertEqual(response.context['conflict_ids'], {regular.pk})
        self.assertNotContains(response, event_table.title)
        program = self.client.get(reverse('event-program', args=[self.event.slug]), {'date': 'all'})
        self.assertTrue(program.context['has_conflicts'])
        self.assertNotContains(program, regular.title)

    def test_public_program_hides_conflicts_with_private_sessions(self):
        self.table('Public game', station=self.event_station, starts=time(0, 30), event=self.event)
        private_event = Event.objects.create(name='Draft event', creator=self.manager)
        self.table('Private game', station=self.event_station, starts=time(23, 30),
                   day=self.previous_day, event=private_event)
        program = reverse('event-program', args=[self.event.slug])
        filters = {'date': self.day.isoformat(), 'view': 'grid'}

        self.assertFalse(self.client.get(program, filters).context['has_conflicts'])
        self.client.force_login(self.manager.user)
        response = self.client.get(program, filters)
        self.assertTrue(response.context['has_conflicts'])
        self.assertNotContains(response, 'Private game')

    def test_ordinary_location_create_warns_and_saves_the_session(self):
        self.table('Night game', station=self.location_station, starts=time(23, 30), day=self.previous_day)
        self.client.force_login(self.manager.user)
        create = reverse('location-table-create', args=[self.location.slug])

        response = self.client.post(create, {
            'title': 'Early game', 'description': 'Join the game', 'date': self.day.isoformat(), 'time': '00:30',
            'duration': 60, 'min_players': 2, 'max_players': 4, 'location': self.location.pk,
            'physical_table': self.location_station.pk, 'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0,
        })

        self.assertEqual(response.status_code, 302)
        self.assertIn(WARNING, [message.level for message in get_messages(response.wsgi_request)])
        self.assertTrue(self.location.tables.filter(title='Early game', physical_table=self.location_station).exists())
