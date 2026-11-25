from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, Location, Member, Membership
from webapp.services.images import COVER_MAX_SIDE


class OrganizedEventFlowTest(TestCase):
    def setUp(self):
        self.manager = UserProfileFactory()
        self.club = LocationFactory(name='Magno Gato', creator=self.manager)
        self.fair = LocationFactory(name='Fiera di Vicenza')
        self.day = timezone.localdate() + timedelta(days=3)
        self.create_url = reverse('location-event-create', args=[self.club.slug])
        self.data = {'name': 'Ludoteca in fiera', 'description': 'Tre serate',
                     'venue_location': self.fair.pk, 'date': self.day.isoformat(),
                     'opening_time': '18:00', 'closing_time': '01:00'}

    def test_from_location_to_published_multiday_event(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(self.create_url)
        self.assertContains(response, 'id_cover-preview')
        self.assertContains(response, 'aspect-ratio="1.7777777777777777"')
        self.client.post(self.create_url, {**self.data, 'organizer_location': self.fair.pk})
        event = Event.objects.get(name=self.data['name'])
        self.assertEqual((event.organizer_location, event.venue_location), (self.club, self.fair))
        self.assertEqual(event.dates.get().closing_time, time(1))
        manage = self.client.get(reverse('event-manage', args=[event.slug]))
        self.assertContains(manage, reverse('location-detail', args=[self.club.slug]))
        self.assertContains(manage, reverse('location-detail', args=[self.fair.slug]))
        self.assertContains(self.client.get(reverse('location-manage-events', args=[self.club.slug])), event.name)
        self.client.post(reverse('event-manage-dates', args=[event.slug]), {
            'date': self.day + timedelta(days=2), 'opening_time': '10:00', 'closing_time': '18:00'})
        self.client.post(reverse('event-manage-publish', args=[event.slug]))
        event.refresh_from_db()
        self.assertTrue(event.is_published)
        self.assertEqual(event.dates.count(), 2)
        self.client.logout()
        detail = self.client.get(event.get_absolute_url())
        self.assertContains(detail, self.club.name)
        self.assertContains(detail, self.fair.name)
        self.assertContains(self.client.get(reverse('location-detail', args=[self.club.slug])), event.name)
        self.assertNotContains(self.client.get(reverse('location-detail', args=[self.fair.slug])), event.name)

    def test_member_can_propose_and_cannot_edit_or_publish(self):
        profile = UserProfileFactory()
        Membership.objects.create(member=Member.objects.create(location=self.club, user_profile=profile),
                                  status=Membership.ACTIVE)
        self.client.force_login(profile.user)
        entry = reverse('event-create')
        self.assertNotContains(self.client.get(entry), self.create_url)
        self.assertEqual(self.client.post(entry, self.data).status_code, 405)
        self.assertEqual(self.client.post(self.create_url, self.data).status_code, 403)
        self.assertFalse(Event.objects.exists())
        self.club.event_creation_permission = Location.PERM_MEMBERS_ONLY
        self.club.save(update_fields=['event_creation_permission'])
        self.assertContains(self.client.get(entry), self.create_url)
        self.client.post(self.create_url, self.data)
        event = Event.objects.get(creator=profile)
        self.assertEqual(event.status, Event.DRAFT)
        self.assertEqual(self.client.post(reverse('event-manage-publish', args=[event.slug])).status_code, 403)
        self.assertEqual(self.client.get(reverse('event-manage-data', args=[event.slug])).status_code, 403)

    def test_manual_public_venue_requires_coordinates_and_hours(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.create_url, {**self.data, 'venue_location': '', 'opening_time': ''})
        event = Event.objects.get()
        self.assertEqual(len(event.missing_publish_requirements()), 2)
        self.assertEqual(self.client.get(reverse('event-manage-data', args=[event.slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse('event-manage-managers', args=[event.slug])).status_code, 404)

    def test_cover_editor_knows_the_maximum_side(self):
        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(self.create_url), f'data-crop-max-side="{COVER_MAX_SIDE}"')

    def test_registered_venue_picker_preserves_initial_and_invalid_choices(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(self.create_url)
        self.assertContains(response, 'data-venue-fields="manual" hidden disabled')
        self.assertContains(response, f'name="venue_location" value="{self.club.pk}"')
        self.assertNotContains(response, '<select name="venue_location"')

        response = self.client.post(self.create_url, {
            **self.data, 'venue_mode': 'registered', 'venue_location': '',
        })
        self.assertIn('venue_location', response.context['form'].errors)
        self.assertContains(response, 'data-venue-fields="manual" hidden disabled')
        self.assertFalse(Event.objects.exists())

        self.client.post(self.create_url, {
            **self.data, 'venue_mode': 'registered', 'venue_name': 'Unused name', 'latitude': 'invalid',
        })
        event = Event.objects.get()
        self.assertEqual(event.venue_location, self.fair)
        self.assertEqual(event.venue_name, '')
        self.assertIsNone(event.latitude)

    def test_switching_to_a_manual_venue_selects_the_event_layout(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.create_url, {**self.data, 'venue_location': self.club.pk})
        event = Event.objects.get()
        self.assertEqual(event.layout_mode, Event.LayoutMode.VENUE)

        edit = reverse('event-manage-data', args=[event.slug])
        self.client.post(edit, {
            **self.data, 'venue_mode': 'manual', 'venue_name': 'Sala Civica',
            'address': 'Via Roma 1', 'latitude': '45.54', 'longitude': '11.52',
        })
        event.refresh_from_db()
        self.assertIsNone(event.venue_location)
        self.assertEqual(event.venue_name, 'Sala Civica')
        self.assertEqual(event.layout_mode, Event.LayoutMode.EVENT)
        self.assertContains(self.client.get(edit), 'data-venue-fields="registered" hidden disabled')

    def test_switching_to_a_registered_venue_clears_the_manual_one(self):
        event = Event.objects.create(name='Fair', organizer_location=self.club, venue_name='Sala Civica',
                                     address='Via Roma 1', city='Vicenza', latitude=45.54, longitude=11.52)
        self.assertNotEqual(event.point.coords, (0, 0))
        self.client.force_login(self.manager.user)
        self.client.post(reverse('event-manage-data', args=[event.slug]), {
            **self.data, 'venue_mode': 'registered', 'venue_location': self.fair.pk,
        })
        event.refresh_from_db()
        self.assertEqual(event.venue_location, self.fair)
        self.assertEqual(event.venue_name, '')
        for name in ('address', 'city', 'latitude', 'longitude'):
            self.assertIsNone(getattr(event, name), name)
        self.assertEqual(event.point.coords, (0, 0))

    def test_coordinates_from_a_map_are_rounded(self):
        self.client.force_login(self.manager.user)
        venue = {'venue_location': '', 'venue_name': 'Sala Civica', 'address': 'Via Roma 1'}
        self.client.post(self.create_url, {
            **self.data, **venue, 'latitude': '45.464212345678901', 'longitude': '9.1899999999999995'})
        event = Event.objects.get()
        self.assertEqual((event.latitude, event.longitude), ('45.46421235', '9.19000000'))
        for value in ('90.5', 'NaN', 'Infinity', '1e30', 'abc'):
            with self.subTest(value=value):
                response = self.client.post(self.create_url, {**self.data, **venue, 'latitude': value})
                self.assertIn('latitude', response.context['form'].errors)
        self.assertEqual(Event.objects.count(), 1)

    def test_managers_can_create_events_reserved_to_members(self):
        self.club.event_creation_permission = Location.PERM_MEMBERS_ONLY
        self.club.save(update_fields=['event_creation_permission'])
        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(reverse('event-create')), self.create_url)
        self.assertEqual(self.client.get(self.create_url).status_code, 200)

    def test_manual_venue_can_publish_and_remains_complete_on_edit(self):
        self.client.force_login(self.manager.user)
        venue_data = {'venue_location': '', 'venue_name': 'Sala Civica', 'address': 'Via Roma 1',
                      'city': 'Vicenza', 'latitude': '45.54', 'longitude': '11.52'}
        self.client.post(self.create_url, {**self.data, **venue_data})
        event = Event.objects.get()
        self.client.post(reverse('event-manage-publish', args=[event.slug]))
        event.refresh_from_db()
        self.assertTrue(event.is_published)
        self.assertContains(self.client.get(event.get_absolute_url()), 'Sala Civica')
        response = self.client.post(reverse('event-manage-data', args=[event.slug]), {
            'name': event.name, 'description': event.description, **venue_data, 'latitude': '',
        })
        self.assertIn('latitude', response.context['form'].errors)
        event.refresh_from_db()
        self.assertEqual(event.latitude, '45.54')
