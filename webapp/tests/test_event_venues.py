import json
from datetime import date
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate


class EventVenueTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organizer = LocationFactory(name='Magno Gato')
        cls.venue = LocationFactory(name='Fiera di Vicenza', city='Vicenza')

    def test_registered_venue_and_organizer_are_independent(self):
        event = Event.objects.create(name='Ludoteca', organizer_location=self.organizer, venue_location=self.venue)
        EventDate.objects.create(event=event, date=date(2030, 4, 5))
        self.assertFalse(event.is_at_organizer_location)
        data = event.structured_data()
        self.assertEqual(data['organizer']['name'], self.organizer.name)
        self.assertEqual(data['location'], self.venue.as_schema_place())
        event.venue_location = self.organizer
        self.assertTrue(event.is_at_organizer_location)

    def test_external_manual_venue_and_legacy_urls(self):
        event = Event.objects.create(name='Fiera', city='Vicenza', creator=UserProfileFactory())
        original_url = event.get_absolute_url()
        self.assertEqual(event.as_schema_place()['name'], 'Vicenza')
        event.organizer_location = self.organizer
        event.venue_name = 'Padiglione B'
        event.address = 'Via della Fiera 1'
        event.latitude, event.longitude = '45.5', '11.5'
        event.save()
        event.refresh_from_db()
        self.assertFalse(event.is_at_organizer_location)
        self.assertEqual(event.as_schema_place()['name'], 'Padiglione B')
        self.assertEqual(event.get_absolute_url(), original_url)

    def test_only_unassigned_events_require_legacy_mapping(self):
        legacy = Event.objects.create(name='Edizione storica')
        Event.objects.create(name='Serata', organizer_location=self.organizer, venue_location=self.organizer)
        output = StringIO()
        call_command('audit_legacy_events', stdout=output)
        self.assertEqual([row['event_id'] for row in json.loads(output.getvalue())['events']], [legacy.pk])
