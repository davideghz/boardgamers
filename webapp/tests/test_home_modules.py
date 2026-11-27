import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.models import Event, EventDate, Table
from webapp.services.manager_todo import (
    DRAFT_EVENTS, EVENTS_WITHOUT_TABLES, LAYOUT_REQUESTS, MEMBERSHIP_REQUESTS, manager_todo,
)
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian

MODULES = ['home-todo', 'home-next', 'home-my-locations', 'home-start']


class HomeModulesTest(TestCase):
    """The signed-in home: which modules each persona gets, in which order."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(reverse('home'))

    def modules(self, response):
        html = response.content.decode()
        found = [(html.index(f'id="{module}"'), module) for module in MODULES if f'id="{module}"' in html]
        return [module for _position, module in sorted(found)]

    def test_modules_per_persona(self):
        expected = {
            'manager': ['home-todo', 'home-next', 'home-my-locations'],
            'member': ['home-next', 'home-my-locations'],
            'player': ['home-next', 'home-my-locations'],
            'newcomer': ['home-start'],
            'organizer': ['home-next'],  # the festival they run
        }
        for persona, modules in expected.items():
            with self.subTest(persona):
                self.assertEqual(self.modules(self.get(persona)), modules)

    def test_visitors_keep_the_presentation(self):
        response = self.get()
        self.assertEqual(self.modules(response), [])
        self.assertContains(response, italian('Bring your club here'))

    def test_manager_to_do(self):
        keys = [(item.key, item.location.name, item.count) for item in self.get('manager').context['todo_items']]
        # The two fair events take table bookings and have no table yet; the association's
        # weekly evenings run without tables on purpose, so they are not listed.
        self.assertEqual(keys, [(MEMBERSHIP_REQUESTS, 'Circolo Demo', 1), (DRAFT_EVENTS, 'Associazione Demo', 1),
                                (EVENTS_WITHOUT_TABLES, 'Associazione Demo', 1),
                                (EVENTS_WITHOUT_TABLES, 'Negozio Demo', 1)])

    def test_next_activities_are_the_users_with_their_state(self):
        response = self.get('member')
        titles = [activity['title'] for activity in response.context['next_activities']]
        self.assertEqual(sorted(titles), ['Serata Demo', 'Tavolo per soci'])
        self.assertContains(response, italian('Your next activities'))

    def test_my_locations_show_a_pending_membership(self):
        roles = dict((location.name, role) for location, role in self.get('player').context['quick_locations'])
        self.assertEqual(roles['Circolo Demo'], 'pending')
        self.assertEqual(roles['Negozio Demo'], None)

    def test_getting_started_follows_the_data_and_goes_away(self):
        steps = {key: done for key, done, _url in self.get('newcomer').context['getting_started']}
        self.assertEqual(steps, {'city': True, 'follow': False, 'join': False})

        newcomer = self.data.newcomer
        newcomer.followed_locations.create(location=self.data.negozio)
        self.data.tables['upcoming'].players.add(newcomer)
        self.assertIsNone(self.get('newcomer').context['getting_started'])


class ManagerTodoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def test_events_without_tables_count_only_when_booking_is_on(self):
        location = self.data.associazione
        night = self.data.night

        def without_tables():
            return next((item.count for item in manager_todo({location.pk}) if item.key == EVENTS_WITHOUT_TABLES), 0)

        before = without_tables()  # the fair event; the evenings take no bookings
        night.table_booking_enabled = True
        night.save(update_fields=['table_booking_enabled'])
        self.assertEqual(without_tables(), before + 1)

        Table.objects.create(title='Tavolo', event=night, date=night.dates.first().date, time=datetime.time(21))
        self.assertEqual(without_tables(), before)

    def test_layout_requests_and_links(self):
        venue = self.data.negozio
        event = Event.objects.create(
            name='Richiesta', creator=self.data.manager, status=Event.DRAFT,
            organizer_location=self.data.associazione, venue_location=venue,
            venue_layout_requested_from=venue)
        EventDate.objects.create(event=event, date=timezone.localdate() + datetime.timedelta(days=5))
        items = {item.key: item for item in manager_todo({venue.pk})}
        self.assertEqual(items[LAYOUT_REQUESTS].count, 1)
        self.assertEqual(items[LAYOUT_REQUESTS].url, reverse('location-venue-layout-requests', args=[venue.slug]))

    def test_nothing_to_do_without_locations(self):
        self.assertEqual(manager_todo(set()), [])


class HomeDiscoverCardsTest(TestCase):
    """Events and festivals on the home share one card: cover, type, city, name, days."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def section(self, html, heading):
        start = html.index(f'>{heading}</h2>')
        return html[start:html.index('</section>', start)]

    def test_festivals_use_the_event_card(self):
        from django.utils.formats import date_format
        from django.utils.translation import override, pgettext

        html = self.client.get(reverse('home')).content.decode()
        with override('it'):
            events, festivals = italian('Upcoming events'), italian('Festivals')
            festival_type = pgettext('appointment type', 'Festival')
            festival = self.data.manifestation
            days = f"{date_format(festival.start_date, 'j M')} – {date_format(festival.end_date, 'j M Y')}"
        events, festivals = self.section(html, events), self.section(html, festivals)
        card = 'class="group flex flex-col h-full rounded-xl border border-divider'
        self.assertIn(card, events)
        self.assertIn(card, festivals)
        self.assertIn(f'href="{festival.get_absolute_url()}"', festivals)
        self.assertIn(f'src="{festival.cover_url}"', festivals)
        self.assertIn(festival_type, festivals)
        self.assertIn(days, festivals)
