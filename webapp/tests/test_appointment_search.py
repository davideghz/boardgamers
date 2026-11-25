from datetime import date, time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override

from webapp.factories import GameFactory, LocationFactory
from webapp.models import Event, EventDate, MasterEvent, MasterEventDate, Table


class AppointmentSearchTest(TestCase):
    def setUp(self):
        self.club = LocationFactory(name='Magno Gato')
        self.venue = LocationFactory(name='Fiera di Vicenza')
        self.first = timezone.localdate() + timedelta(days=3)
        self.last = self.first + timedelta(days=2)
        self.master = MasterEvent.objects.create(name='Festival', venue_location=self.venue, status=Event.PUBLISHED)
        self.event = Event.objects.create(name='Ludoteca', organizer_location=self.club, venue_location=self.venue,
                                          master_event=self.master, status=Event.PUBLISHED)
        for day in (self.first, self.last):
            MasterEventDate.objects.create(master_event=self.master, date=day, opening_time=time(9))
            EventDate.objects.create(event=self.event, date=day, opening_time=time(10))
        self.table = Table.objects.create(
            title='Finale', event=self.event, date=self.last, time=time(11), game=GameFactory(name='Azul'),
        )
        self.url = reverse('appointment-search')

    def results(self, params=None):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response.context['items']

    def test_distinguishes_organizer_from_venue_and_preserves_provenance(self):
        params = {'q': 'Festival', 'location': self.venue.slug, 'organizer': self.club.slug}
        self.assertEqual(self.results(params), [
            ('manifestation', self.master), ('event', self.event), ('table', self.table),
        ])
        self.assertEqual(self.results({**params, 'location': self.club.slug}), [])
        self.assertContains(self.client.get(self.url, params), self.table.get_absolute_url())
        self.assertEqual(self.results({**params, 'type': 'manifestations'}), [('manifestation', self.master)])

    def test_filters_actual_days_and_hides_drafts_and_disabled_program(self):
        day = self.first + timedelta(days=1)
        self.assertEqual(self.results({'when': 'range', 'date_from': day, 'date_to': day}), [])
        items = self.results({'when': 'range', 'date_from': self.last, 'date_to': self.last})
        self.assertEqual([item.matching_date for _, item in items], [self.last] * 3)
        self.event.table_booking_enabled = False
        self.event.save()
        self.assertNotIn(('table', self.table), self.results())
        self.event.status = Event.DRAFT
        self.event.save()
        self.assertEqual(self.results(), [('manifestation', self.master)])

    def test_combined_results_page_and_invalid_date_range(self):
        for i in range(16):
            Table.objects.create(title=f'Serata {i}', location=self.club, date=self.last, time=time(23))
        first_page = self.client.get(self.url, {'location': self.club.slug, 'page': 1})
        second_page = self.client.get(self.url, {'location': self.club.slug, 'page': 2})
        self.assertTrue(first_page.context['is_paginated'])
        self.assertEqual(len(second_page.context['items']), 1)
        self.assertTrue(set(first_page.context['items']).isdisjoint(second_page.context['items']))
        self.assertContains(first_page, f'location={self.club.slug}&amp;page=2')
        self.assertEqual(len(self.results({'page': 2})), 4)
        invalid = self.client.get(self.url, {'when': 'range', 'date_from': self.last, 'date_to': self.first})
        self.assertTrue(invalid.context['date_error'])

    def test_registered_venue_and_organizer_apply_to_the_right_results(self):
        standalone = Table.objects.create(title='Serata soci', location=self.club, date=self.last, time=time(12))
        self.assertEqual(self.results({'location': self.club.slug}), [('table', standalone)])
        self.assertNotIn(('table', standalone), self.results({'organizer': self.club.slug}))
        self.assertIn(('table', self.table), self.results({'location': self.venue.slug}))
        self.assertEqual(self.results({'q': 'azul'}), [('table', self.table)])

    def test_manifestation_organizer_filter_matches_only_its_event_days(self):
        self.event.dates.filter(date=self.first).delete()
        filters = {'type': 'manifestations', 'organizer': self.club.slug, 'when': 'range'}
        self.assertEqual(self.results({**filters, 'date_from': self.first, 'date_to': self.first}), [])
        self.assertEqual(self.results({**filters, 'date_from': self.last, 'date_to': self.last}), [
            ('manifestation', self.master),
        ])

    def test_public_child_does_not_disclose_its_draft_manifestation(self):
        self.master.status = Event.DRAFT
        self.master.save(update_fields=['status'])
        self.assertEqual(self.results({'q': self.master.name}), [])
        response = self.client.get(self.url)
        self.assertContains(response, self.event.name)
        self.assertContains(response, self.table.title)
        self.assertNotContains(response, self.master.name)

    def test_past_uses_most_recent_actual_day_and_today_and_weekend_are_inclusive(self):
        saturday = date(2020, 11, 28)
        friday = saturday - timedelta(days=1)
        sunday = saturday + timedelta(days=1)
        for day in (friday, saturday, sunday):
            MasterEventDate.objects.create(master_event=self.master, date=day, opening_time=time(8))
            EventDate.objects.create(event=self.event, date=day, opening_time=time(8))
        with patch('webapp.views.appointment_search.timezone.localdate', return_value=sunday):
            past, = self.results({'type': 'events', 'when': 'past'})
            today, = self.results({'type': 'events', 'when': 'today'})
            weekend, = self.results({'type': 'events', 'when': 'weekend'})
        self.assertEqual(past[1].matching_date, saturday)
        self.assertEqual(today[1].matching_date, sunday)
        self.assertEqual(weekend[1].matching_date, saturday)

    def test_tabs_reset_page_and_keep_filters(self):
        response = self.client.get(self.url, {'type': 'events', 'q': 'Ludoteca', 'page': 2})
        self.assertContains(response, f'href="{self.url}?q=Ludoteca"')
        self.assertContains(response, f'href="{self.url}?type=tables&amp;q=Ludoteca"')
        response = self.client.get(self.url, {'type': 'events'})
        self.assertContains(response, f'href="{self.url}"')

    def test_search_filters_are_translated_in_italian(self):
        with override('it'):
            response = self.client.get(reverse('appointment-search'), HTTP_ACCEPT_LANGUAGE='it')
        self.assertContains(response, 'Tipo di risultato')
        self.assertContains(response, 'Intervallo di date')
