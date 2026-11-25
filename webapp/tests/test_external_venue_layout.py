from datetime import time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, PhysicalTable, PlayArea, Table


class ExternalVenueLayoutTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organizer = UserProfileFactory(preferred_language='it')
        cls.host = UserProfileFactory(preferred_language='it')
        cls.club = LocationFactory(name='Club', creator=cls.organizer)
        cls.fair = LocationFactory(name='Expo venue', creator=cls.host)
        cls.event = Event.objects.create(name='Draft expo event', organizer_location=cls.club, venue_location=cls.fair)
        cls.date = timezone.localdate() + timedelta(days=3)
        EventDate.objects.create(event=cls.event, date=cls.date, opening_time=time(18), closing_time=time(23))
        area = PlayArea.objects.create(name='Expo hall', location=cls.fair)
        cls.station = PhysicalTable.objects.create(name='Expo station', location=cls.fair, play_area=area)
        cls.private_station = PhysicalTable.objects.create(
            name='Staff station', location=cls.fair, play_area=area, is_visible=False,
        )

    def request_layout(self, action='request'):
        self.client.force_login(self.organizer.user)
        response = self.client.post(reverse('event-venue-layout-request', args=[self.event.slug]), {'action': action})
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()

    def decide(self, action):
        self.client.force_login(self.host.user)
        response = self.client.post(self.decision_url(), {'action': action})
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()

    def decision_url(self, location=None):
        return reverse('location-venue-layout-decision', args=[(location or self.fair).slug, self.event.pk])

    def choose_layout(self):
        self.client.force_login(self.organizer.user)
        return self.client.post(reverse('event-manage-data', args=[self.event.slug]), {
            'name': self.event.name, 'description': 'Games at the expo', 'venue_location': self.fair.pk,
            'layout_mode': Event.LayoutMode.VENUE, 'table_booking_enabled': 'on',
        })

    def test_only_the_current_host_can_approve_a_request(self):
        self.assertContains(self.choose_layout(), 'ottieni l’autorizzazione della sede esterna')
        self.request_layout()
        self.assertEqual(self.event.venue_layout_requested_from, self.fair)
        self.assertFalse(self.event.can_use_venue_layout)
        self.assertEqual(self.client.post(self.decision_url(), {'action': 'approve'}).status_code, 403)
        self.assertEqual(self.client.post(self.decision_url(self.club), {'action': 'approve'}).status_code, 404)
        self.client.force_login(self.host.user)
        inbox = reverse('location-venue-layout-requests', args=[self.fair.slug])
        other = Event.objects.create(name='Unshared draft', organizer_location=self.club, venue_location=self.fair)
        listing = self.client.get(inbox)
        self.assertContains(listing, self.event.name)
        self.assertNotContains(listing, other.name)
        self.assertEqual(self.client.get(reverse('event-manage', args=[self.event.slug])).status_code, 404)
        self.assertEqual(self.client.post(reverse('event-venue-layout-request', args=[self.event.slug]),
                                          {'action': 'cancel'}).status_code, 403)
        self.decide('approve')
        self.assertTrue(self.event.can_use_venue_layout)
        self.assertEqual(self.event.layout_mode, Event.LayoutMode.EVENT)
        self.assertFalse(other.can_use_venue_layout)

    def test_after_approval_organizer_can_assign_visible_venue_stations(self):
        self.request_layout()
        self.decide('approve')
        self.assertEqual(self.choose_layout().status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.layout_mode, Event.LayoutMode.VENUE)
        organizer_station_page = self.client.get(reverse('event-manage-stations', args=[self.event.slug]))
        self.assertContains(organizer_station_page, self.station.name)
        self.assertNotContains(organizer_station_page, self.private_station.name)
        create = reverse('event-table-create', args=[self.event.slug])
        form = self.client.get(create).context['form']
        self.assertQuerySetEqual(form.fields['physical_table'].queryset, [self.station])
        data = {'title': 'Expo game', 'event': self.event.pk, 'date': self.date.isoformat(), 'time': '20:00',
                'min_players': 2, 'max_players': 4, 'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0}
        denied = self.client.post(create, {**data, 'physical_table': self.private_station.pk})
        self.assertIn('physical_table', denied.context['form'].errors)
        self.assertEqual(self.client.post(create, {**data, 'physical_table': self.station.pk}).status_code, 302)
        table = self.event.tables.get()
        self.assertEqual((table.physical_table, table.play_area), (self.station, self.station.play_area))
        self.assertEqual(self.client.post(reverse('event-manage-stations', args=[self.event.slug]),
                                          {'name': 'Unused'}).status_code, 403)

    def test_host_can_revoke_only_after_the_future_assignment_is_cleared(self):
        self.request_layout()
        self.decide('approve')
        self.assertEqual(self.choose_layout().status_code, 302)
        table = Table.objects.create(event=self.event, date=self.date, physical_table=self.station, title='Expo game')
        self.decide('revoke')
        self.assertTrue(self.event.venue_layout_approved)
        self.assertEqual(self.event.layout_mode, Event.LayoutMode.VENUE)
        table.refresh_from_db()
        self.assertEqual(table.physical_table, self.station)

        table.physical_table = None
        table.play_area = None
        table.save(update_fields=['physical_table', 'play_area'])
        self.decide('revoke')
        self.assertFalse(self.event.can_use_venue_layout)
        self.assertEqual(self.event.layout_mode, Event.LayoutMode.EVENT)
        self.assertIsNone(self.event.venue_layout_requested_from)

    def test_submitting_twice_shows_the_current_state(self):
        self.request_layout()
        self.request_layout()
        self.assertEqual(self.event.venue_layout_requested_from, self.fair)
        self.decide('approve')
        self.decide('approve')
        self.decide('decline')
        self.assertTrue(self.event.venue_layout_approved)
        self.request_layout('cancel')
        self.assertTrue(self.event.venue_layout_approved)
        self.assertEqual(self.client.post(reverse('event-venue-layout-request', args=[self.event.slug]),
                                          {'action': 'other'}).status_code, 400)

    def test_superusers_manage_the_venue_layout_without_managing_the_venue(self):
        self.request_layout()
        self.decide('approve')
        self.choose_layout()
        self.client.force_login(UserProfileFactory(user__is_superuser=True).user)
        for part in ('areas', 'stations'):
            response = self.client.get(reverse(f'event-manage-{part}', args=[self.event.slug]), follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.request['PATH_INFO'], reverse(f'location-manage-{part}', args=[self.fair.slug]))
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(reverse('location-manage-areas', args=[self.fair.slug])).status_code, 403)

    def test_cancel_and_decline_remove_pending_requests(self):
        self.request_layout()
        self.request_layout('cancel')
        self.assertIsNone(self.event.venue_layout_requested_from)
        self.request_layout()
        self.decide('decline')
        self.assertIsNone(self.event.venue_layout_requested_from)
        self.assertFalse(self.event.venue_layout_approved)

    def test_changing_venue_or_organizer_clears_approval(self):
        self.request_layout()
        self.decide('approve')
        self.event.venue_location = self.club
        self.event.save(update_fields=['venue_location'])
        self.event.refresh_from_db()
        self.assertIsNone(self.event.venue_layout_requested_from)
        self.assertFalse(self.event.venue_layout_approved)
        self.event.venue_location = self.fair
        self.event.save(update_fields=['venue_location'])
        self.request_layout()
        self.decide('approve')
        self.event.organizer_location = LocationFactory(name='New organizer')
        self.event.save(update_fields=['organizer_location'])
        self.event.refresh_from_db()
        self.assertIsNone(self.event.venue_layout_requested_from)
        self.assertFalse(self.event.venue_layout_approved)

    def test_model_and_database_reject_approval_with_no_current_request(self):
        self.event.venue_layout_approved = True
        with self.assertRaises(ValidationError):
            self.event.save(update_fields=['venue_layout_approved'])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Event.objects.filter(pk=self.event.pk).update(
                venue_layout_requested_from=self.club, venue_layout_approved=True, layout_mode=Event.LayoutMode.VENUE,
            )
