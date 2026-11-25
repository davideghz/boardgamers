import json
from datetime import date, time
from io import StringIO

from django.contrib.admin import AdminSite
from django.core.management import call_command
from django.db.models import ProtectedError
from django.test import RequestFactory, TestCase
from django.urls import reverse

from webapp.admin import EventAdmin
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

    def admin_event_data(self, response, name):
        data = {
            'name': name, 'layout_mode': Event.LayoutMode.EVENT, 'status': Event.DRAFT,
            'point': 'SRID=4326;POINT (0 0)',
        }
        for inline in response.context['inline_admin_formsets']:
            data.update({field.html_name: field.value() for field in inline.formset.management_form})
            for form in inline.formset.forms:
                data.update({field.html_name: field.value() for field in form if field.value() is not None})
        return data

    def test_admin_requires_an_organizer_when_creating_an_event(self):
        self.client.force_login(UserProfileFactory(user__is_staff=True, user__is_superuser=True).user)
        url = reverse('admin:webapp_event_add')
        response = self.client.get(url)
        fields = response.context['adminform'].form.fields
        self.assertLessEqual({'organizer_location', 'venue_location', 'venue_name'}, set(fields))
        self.assertTrue(fields['organizer_location'].required)

        data = {**self.admin_event_data(response, 'Draft in fiera'), 'venue_location': self.venue.pk}
        rejected = self.client.post(url, data)
        self.assertIn('organizer_location', rejected.context['adminform'].form.errors)
        self.assertFalse(Event.objects.exists())

        saved = self.client.post(url, {**data, 'organizer_location': self.organizer.pk})
        self.assertEqual(saved.status_code, 302)
        event = Event.objects.get()
        self.assertEqual((event.organizer_location, event.venue_location), (self.organizer, self.venue))

    def test_admin_can_edit_unmapped_events_but_cannot_clear_assigned_organizers(self):
        self.client.force_login(UserProfileFactory(user__is_staff=True, user__is_superuser=True).user)
        event = Event.objects.create(name='Historical event')
        url = reverse('admin:webapp_event_change', args=[event.pk])
        response = self.client.get(url)
        data = self.admin_event_data(response, 'Revised historical event')
        self.assertFalse(response.context['adminform'].form.fields['organizer_location'].required)
        saved = self.client.post(url, data)
        self.assertEqual(saved.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.name, data['name'])
        self.assertIsNone(event.organizer_location_id)

        self.assertEqual(self.client.post(url, {**data, 'organizer_location': self.organizer.pk}).status_code, 302)
        rejected = self.client.post(url, {**data, 'organizer_location': ''})
        self.assertIn('organizer_location', rejected.context['adminform'].form.errors)
        event.refresh_from_db()
        self.assertEqual(event.organizer_location_id, self.organizer.pk)

    def test_admin_save_preserves_an_organizer_assigned_during_editing(self):
        event = Event.objects.create(name='Historical event')
        Event.objects.filter(pk=event.pk).update(organizer_location=self.organizer)
        event.name = 'Revised historical event'

        EventAdmin(Event, AdminSite()).save_model(RequestFactory().post('/'), event, form=None, change=True)

        event.refresh_from_db()
        self.assertEqual(event.organizer_location_id, self.organizer.pk)
        self.assertEqual(event.name, 'Revised historical event')

    def test_only_unassigned_events_require_legacy_mapping(self):
        legacy = Event.objects.create(name='Edizione storica')
        Event.objects.create(name='Serata', organizer_location=self.organizer, venue_location=self.organizer)
        output = StringIO()
        call_command('audit_legacy_events', stdout=output)
        self.assertEqual([row['event_id'] for row in json.loads(output.getvalue())['events']], [legacy.pk])
