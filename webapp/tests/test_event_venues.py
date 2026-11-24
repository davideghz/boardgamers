import json
from datetime import date, time
from io import StringIO

from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, Table


class EventVenueTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organizer = LocationFactory(name='Magno Gato', creator=UserProfileFactory())
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

    def test_venue_without_address_falls_back_to_the_event_address(self):
        venue = LocationFactory(name='Senza indirizzo', address='', city='')
        event = Event(name='Fiera', venue_location=venue, city='Verona')
        self.assertEqual(event.as_schema_place()['name'], 'Senza indirizzo')
        self.assertEqual(event.as_schema_place()['address']['addressLocality'], 'Verona')
        event.city = ''
        self.assertIsNone(event.as_schema_place())

    def test_event_table_inherits_the_venue_on_the_request_host(self):
        event = Event.objects.create(name='Ludoteca', organizer_location=self.organizer, venue_location=self.venue)
        table = Table(title='Tavolo', event=event, date=date(2030, 4, 5), time=time(21), slug='tavolo')
        request = RequestFactory().get('/', HTTP_HOST='localhost')
        EventDate.objects.create(event=event, date=date(2030, 4, 5))
        for data in (event.structured_data(request), table.structured_data(request)):
            self.assertEqual(data['location']['name'], self.venue.name)
            self.assertTrue(data['location']['url'].startswith('http://localhost/'))

    def test_public_page_exposes_organizer_and_venue(self):
        event = Event.objects.create(name='Ludoteca', status=Event.PUBLISHED, organizer_location=self.organizer,
                                     venue_location=self.venue)
        EventDate.objects.create(event=event, date=date(2030, 4, 5))
        response = self.client.get(event.get_absolute_url())
        self.assertContains(response, self.organizer.name)
        self.assertContains(response, self.venue.name)

    def test_locations_of_an_event_cannot_be_deleted(self):
        Event.objects.create(name='Ludoteca', organizer_location=self.organizer, venue_location=self.venue)
        for instance in (self.organizer, self.venue, self.organizer.creator):
            with self.subTest(instance=instance), self.assertRaises(ProtectedError):
                instance.delete()

    def test_admin_edits_organizer_and_venue(self):
        self.client.force_login(UserProfileFactory(user__is_staff=True, user__is_superuser=True).user)
        fields = self.client.get(reverse('admin:webapp_event_add')).context['adminform'].form.fields
        self.assertLessEqual({'organizer_location', 'venue_location', 'venue_name'}, set(fields))

    def test_only_unassigned_events_require_legacy_mapping(self):
        legacy = Event.objects.create(name='Edizione storica')
        Event.objects.create(name='Serata', organizer_location=self.organizer, venue_location=self.organizer)
        output = StringIO()
        call_command('audit_legacy_events', stdout=output)
        self.assertEqual([row['event_id'] for row in json.loads(output.getvalue())['events']], [legacy.pk])
