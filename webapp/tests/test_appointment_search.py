from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, LocationEvent, Table


class AppointmentSearchTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory(preferred_language='it')
        cls.genova = LocationFactory(name='Club Lanterna', city='Genova', creator=cls.owner)
        cls.torino = LocationFactory(name='Club Mole', city='Torino', creator=cls.owner)

    def setUp(self):
        self.enterContext(translation.override('it'))
        self.today = timezone.localdate()
        self.url = reverse('appointment-search')

    def add_table(self, title, offset=1, **fields):
        fields.setdefault('location', self.genova)
        return Table.objects.create(
            title=title, author=self.owner, date=self.today + timedelta(days=offset),
            time=time(20, 30), **fields,
        )

    def add_event(self, name, offsets, **fields):
        fields.setdefault('status', Event.PUBLISHED)
        fields.setdefault('city', 'Genova')
        event = Event.objects.create(name=name, creator=self.owner, **fields)
        for offset in offsets:
            EventDate.objects.create(
                event=event, date=self.today + timedelta(days=offset), opening_time=time(10),
            )
        return event

    def add_location_event(self, name, offset=1, **fields):
        fields.setdefault('status', LocationEvent.PUBLISHED)
        fields.setdefault('host_location', self.genova)
        return LocationEvent.objects.create(
            name=name, creator=self.owner, date=self.today + timedelta(days=offset),
            opening_time=time(19), closing_time=time(23), **fields,
        )

    def test_search_finds_table_by_game_and_event_by_description(self):
        game = GameFactory(name='Azul')
        table = self.add_table('Sfida a mosaici', game=game)
        event = self.add_event('Festival dei mosaici', [2], description='Dimostrazione di Azul')
        self.add_table('Partita a Carcassonne')
        self.add_event('Festival del fumetto', [2])

        response = self.client.get(self.url, {'q': 'azul'})

        self.assertContains(response, table.get_absolute_url())
        self.assertContains(response, event.get_absolute_url())
        self.assertEqual(response.context['items'], [('table', table), ('manifestation', event)])

    def test_search_excludes_unpublished_events_even_for_owner_and_program_tables(self):
        event = self.add_event('Festival pubblico', [1])
        self.add_event('Festival in revisione', [1], status=Event.DRAFT)
        self.add_event('Festival respinto', [1], status=Event.BLOCKED)
        self.add_event('Festival senza date', [])
        self.add_table('Tavolo del programma', event=event, location=None)
        table = self.add_table('Tavolo della sede')
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url)

        self.assertEqual(response.context['items'], [('manifestation', event), ('table', table)])

    def test_type_tabs_split_the_three_kinds_and_keep_only_public_results(self):
        festival = self.add_event('Festival pubblico', [1])
        event = self.add_location_event('Gioco libero')
        table = self.add_table('Tavolo pubblico')
        self.add_location_event('Bozza privata', status=LocationEvent.DRAFT)

        for search_type, expected in (
            ('all', [('manifestation', festival), ('event', event), ('table', table)]),
            ('events', [('event', event)]),
            ('tables', [('table', table)]),
            ('manifestations', [('manifestation', festival)]),
        ):
            with self.subTest(search_type=search_type):
                response = self.client.get(self.url, {'type': search_type})
                self.assertEqual(response.context['items'], expected)
        self.assertContains(response, 'Tutti')
        self.assertContains(response, 'In programma')
        self.assertContains(response, 'Vecchi')

    def test_past_orders_all_kinds_by_their_latest_matching_date_and_time(self):
        festival = self.add_event('Festival con una data futura', [-3, -1, 2])
        event = self.add_location_event('Gioco libero di ieri', offset=-1)
        table = self.add_table('Tavolo di ieri', offset=-1)
        self.add_location_event('Gioco libero di oggi', offset=0)

        response = self.client.get(self.url, {'when': 'past'})

        self.assertEqual(response.context['items'], [('table', table), ('event', event), ('manifestation', festival)])
        self.assertEqual(response.context['items'][-1][1].matching_date, self.today - timedelta(days=1))
        self.assertContains(response, '?when=past&amp;type=events')

    def test_today_uses_actual_event_dates_instead_of_the_span(self):
        self.add_event('Festival con una pausa', [-1, 1])
        event = self.add_event('Festival di oggi', [0, 2])
        table = self.add_table('Tavolo di oggi', offset=0)
        self.add_table('Tavolo di domani')

        response = self.client.get(self.url, {'when': 'today'})

        self.assertEqual(response.context['items'], [('manifestation', event), ('table', table)])

    def test_weekend_uses_saturday_and_sunday(self):
        monday = datetime(2030, 2, 4, 12, tzinfo=timezone.get_current_timezone())
        self.today = monday.date()
        with patch('django.utils.timezone.now', return_value=monday):
            self.add_event('Festival fuori dal weekend', [4, 7])
            event = self.add_event('Festival nel weekend', [5, 6])
            saturday = self.add_table('Tavolo di sabato', offset=5)
            sunday = self.add_table('Tavolo di domenica', offset=6)
            self.add_table('Tavolo di lunedì', offset=7)

            response = self.client.get(self.url, {'when': 'weekend'})

        self.assertEqual(response.context['items'], [('manifestation', event), ('table', saturday), ('table', sunday)])

    def test_range_filters_real_event_dates_and_counts_each_event_once(self):
        self.add_event('Festival con giorni vuoti nella ricerca', [1, 5])
        event = self.add_event('Festival con due giorni nella ricerca', [0, 2, 4, 6])
        response = self.client.get(self.url, {
            'type': 'events',
            'event_kind': 'manifestation',
            'when': 'range',
            'date_from': (self.today + timedelta(days=2)).isoformat(),
            'date_to': (self.today + timedelta(days=4)).isoformat(),
        })

        self.assertEqual(response.context['items'], [('manifestation', event)])
        self.assertEqual(response.context['items'][0][1].matching_date, self.today + timedelta(days=2))
        self.assertEqual(response.context['search_type'], 'manifestations')
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_search_uses_the_location_picker_instead_of_a_city_filter(self):
        genova_table = self.add_table('Tavolo genovese')
        torino_table = self.add_table('Tavolo torinese', location=self.torino)
        festival = self.add_event('Festival torinese', [2], city='Torino')

        response = self.client.get(self.url, {'city': 'Genova'})

        self.assertCountEqual(response.context['items'], [
            ('table', genova_table), ('table', torino_table), ('manifestation', festival),
        ])
        self.assertNotContains(response, 'name="city"')
        self.assertContains(response, 'Tutte le locations')
        self.assertTemplateUsed(response, 'partials/_location_filter_button.html')

        selected = self.client.get(self.url, {'location': self.torino.slug})
        self.assertEqual(selected.context['items'], [('table', torino_table)])
        self.assertContains(selected, 'aria-label="Rimuovi filtro"')

    def test_location_filter_does_not_treat_a_sponsor_as_venue(self):
        event = self.add_event('Festival sponsorizzato', [2])
        event.sponsor_locations.add(self.genova)
        table = self.add_table('Tavolo genovese')
        self.add_table('Tavolo torinese', location=self.torino)

        response = self.client.get(self.url, {'location': self.genova.slug})

        self.assertEqual(response.context['items'], [('table', table)])

    def test_all_and_type_filters_paginate_a_single_ordered_list(self):
        tables = [self.add_table(f'Mosaico {offset}', offset=offset) for offset in range(1, 18)]
        self.add_table('Gioco diverso', offset=18)
        festival = self.add_event('Festival Mosaico', [1, 2])
        event = self.add_location_event('Serata Mosaico')

        response = self.client.get(self.url, {'q': 'Mosaico'})
        self.assertEqual(len(response.context['items']), 15)
        self.assertEqual(response.context['items'][:3], [('manifestation', festival), ('event', event), ('table', tables[0])])
        self.assertEqual(response.context['page_obj'].paginator.count, 19)
        self.assertContains(response, '?q=Mosaico&amp;page=2')
        next_page = self.client.get(self.url, {'q': 'Mosaico', 'page': 2})
        self.assertEqual(next_page.context['items'], [('table', table) for table in tables[13:]])

        response = self.client.get(self.url, {'type': 'tables', 'q': 'Mosaico', 'page': 2})
        self.assertEqual(response.context['items'], [('table', table) for table in tables[15:]])
        self.assertEqual(response.context['page_obj'].paginator.count, 17)

    def test_location_homepage_option_does_not_hide_table_from_search(self):
        self.genova.show_tables_in_homepage = False
        self.genova.save(update_fields=['show_tables_in_homepage'])
        table = self.add_table('Tavolo visibile nella ricerca')

        home = self.client.get(reverse('home'))
        self.assertNotIn(table, home.context['future_tables'])
        response = self.client.get(self.url, {'type': 'tables', 'q': 'visibile nella ricerca'})
        self.assertEqual(response.context['items'], [('table', table)])

    def test_shared_search_keeps_filters_when_redirected_to_preferred_language(self):
        table = self.add_table('Sfida a mosaici', game=GameFactory(name='Azul'))
        self.add_table('Serata a Carcassonne')
        profile = UserProfileFactory(preferred_language='en')
        self.client.force_login(profile.user)

        response = self.client.get(self.url, {'type': 'tables', 'q': 'Azul', 'location': self.genova.slug}, follow=True)

        self.assertEqual(response.wsgi_request.LANGUAGE_CODE, 'en')
        self.assertEqual(response.context['selected_location'], self.genova.slug)
        self.assertEqual(response.context['items'], [('table', table)])
