from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import RestrictedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, PhysicalTable, PlayArea, Table


class EventVenueLayoutTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory(preferred_language='it')
        cls.venue = LocationFactory(name='Club', creator=cls.manager)
        cls.other_venue = LocationFactory(name='Fair')
        cls.date = timezone.localdate() + timedelta(days=3)
        cls.event = Event.objects.create(
            name='Open night', status=Event.PUBLISHED, organizer_location=cls.venue, venue_location=cls.venue,
        )
        EventDate.objects.create(event=cls.event, date=cls.date, opening_time=time(18), closing_time=time(23))
        cls.venue_area = PlayArea.objects.create(location=cls.venue, name='Club room')
        cls.venue_station = PhysicalTable.objects.create(location=cls.venue, play_area=cls.venue_area, name='Club station')
        cls.event_area = PlayArea.objects.create(event=cls.event, name='Event room')
        cls.event_station = PhysicalTable.objects.create(event=cls.event, play_area=cls.event_area, name='Event station')

    def select_venue_layout(self):
        self.event.layout_mode = Event.LayoutMode.VENUE
        self.event.save(update_fields=['layout_mode'])

    def session(self, **fields):
        return Table.objects.create(title='Event session', author=self.manager, event=self.event, date=self.date, **fields)

    def test_default_uses_the_events_own_resources(self):
        self.assertEqual(self.event.layout_mode, Event.LayoutMode.EVENT)
        self.assertQuerySetEqual(self.event.effective_play_areas(), [self.event_area])
        self.assertQuerySetEqual(self.event.effective_physical_tables(), [self.event_station])
        with self.assertRaises(ValidationError):
            self.session(physical_table=self.venue_station)

    def test_only_an_on_site_event_can_enable_venue_layout(self):
        self.event.layout_mode = Event.LayoutMode.VENUE
        self.event.venue_location = self.other_venue
        with self.assertRaises(ValidationError):
            self.event.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.filter(pk=self.event.pk).update(layout_mode=Event.LayoutMode.VENUE, venue_location=None)

    def test_event_form_saves_existing_venue_station_and_program_filters_on_its_area(self):
        self.select_venue_layout()
        self.client.force_login(self.manager.user)
        create = reverse('event-table-create', args=[self.event.slug])
        form = self.client.get(create, {'area': self.venue_area.pk}).context['form']
        self.assertEqual(form.initial['play_area'], self.venue_area)
        self.assertQuerySetEqual(form.fields['physical_table'].queryset, [self.venue_station])
        fields = {
            'title': 'Game in the club room', 'event': self.event.pk, 'date': self.date.isoformat(),
            'time': '20:00', 'min_players': 2, 'max_players': 4, 'physical_table': self.venue_station.pk,
            'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0,
        }
        self.assertEqual(self.client.post(create, fields).status_code, 302)
        table = self.event.tables.get()
        self.assertEqual((table.physical_table, table.play_area), (self.venue_station, self.venue_area))
        edit = reverse('event-table-update', args=[self.event.slug, table.slug])
        forged = self.client.post(edit, {**fields, 'physical_table': self.event_station.pk})
        self.assertIn('physical_table', forged.context['form'].errors)
        self.assertEqual(self.event.tables.get().physical_table, self.venue_station)

        self.client.logout()
        program = reverse('event-program', args=[self.event.slug])
        response = self.client.get(program, {'area': self.venue_area.pk, 'view': 'grid'})
        self.assertContains(response, table.title)
        self.assertContains(response, self.venue_station.name)
        self.assertNotContains(response, self.event_station.name)
        self.assertEqual(response.context['grid']['rows'][0]['cells'], [[table]])

    def test_store_uses_the_actual_event_for_partial_session_writes(self):
        other = Event.objects.create(name='Other schedule')
        other_station = PhysicalTable.objects.create(event=other, name='Other station')
        table = self.session(physical_table=self.event_station)
        table.event = other
        table.physical_table = other_station
        table.play_area = None
        with self.assertRaises(ValidationError):
            table.save(update_fields=['physical_table', 'play_area'])
        table.refresh_from_db()
        self.assertEqual(table.physical_table, self.event_station)

    def test_switching_layout_requires_reassigning_future_sessions(self):
        table = self.session(physical_table=self.event_station)
        self.event.layout_mode = Event.LayoutMode.VENUE
        with self.assertRaisesMessage(ValidationError, table.title):
            self.event.save(update_fields=['layout_mode'])
        table.physical_table = None
        table.play_area = None
        table.save(update_fields=['physical_table', 'play_area'])
        self.event.save(update_fields=['layout_mode'])
        table.physical_table = self.venue_station
        table.save(update_fields=['physical_table'])
        table.refresh_from_db()
        self.assertEqual(table.play_area, self.venue_area)

        self.event.venue_location = self.other_venue
        self.event.layout_mode = Event.LayoutMode.EVENT
        # Saving only the venue must still validate against the stored venue mode.
        with self.assertRaises(ValidationError):
            self.event.save(update_fields=['venue_location'])

    def test_removing_assigned_resources_is_blocked_on_venue_management_pages(self):
        self.select_venue_layout()
        table = self.session(physical_table=self.venue_station)
        self.client.force_login(self.manager.user)
        for name, resource in (('location-manage-station-delete', self.venue_station),
                               ('location-manage-area-delete', self.venue_area)):
            response = self.client.post(reverse(name, args=[self.venue.slug, resource.pk]), follow=True)
            self.assertContains(response, 'Riassegna le sessioni future')
            self.assertTrue(type(resource).objects.filter(pk=resource.pk).exists())
        table.refresh_from_db()
        self.assertEqual((table.physical_table, table.play_area), (self.venue_station, self.venue_area))

    def test_future_assignments_protect_event_owned_resources_and_allow_whole_event_deletion(self):
        self.session(physical_table=self.event_station)
        with self.assertRaises(RestrictedError):
            self.event_station.delete()
        with self.assertRaises(RestrictedError):
            self.event_area.delete()
        self.event.delete()

    def test_legacy_station_only_assignment_also_protects_its_area(self):
        table = self.session(physical_table=self.event_station)
        Table.objects.filter(pk=table.pk).update(play_area=None)
        with self.assertRaises(RestrictedError):
            self.event_area.delete()
