import re
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from webapp.models import Event, Location, MasterEvent, Table, UserProfile
from webapp.services.ui_personas import PERSONAS, seed_ui_personas

TITLE_RE = re.compile(r'<title>(.*?)</title>', re.S)

# Pages that render without a <title> today. A2 empties this list.
UNTITLED_PAGES = {'calendar', 'events', 'organized_events'}


class UiSmokeTest(TestCase):
    """The main pages render for every audience of the UI, each with a page title."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def _pages(self):
        data = self.data
        return {
            'home': reverse('home'),
            'locations': reverse('locations-index'),
            'negozio': reverse('location-detail', kwargs={'slug': data.negozio.slug}),
            'circolo': reverse('location-detail', kwargs={'slug': data.circolo.slug}),
            'associazione': reverse('location-detail', kwargs={'slug': data.associazione.slug}),
            'calendar': reverse('location-calendar', kwargs={'slug': data.associazione.slug}),
            'table': reverse('table-detail', kwargs={'slug': data.tables['upcoming'].slug}),
            'members_table': reverse('table-detail', kwargs={'slug': data.tables['members'].slug}),
            'event': reverse('event_detail', kwargs={'slug': data.event.slug}),
            'night': reverse('event_detail', kwargs={'slug': data.night.slug}),
            'manifestation': reverse('master-event-detail', kwargs={'slug': data.manifestation.slug}),
            'search': reverse('appointment-search'),
            'tables': reverse('table-index'),
            'events': reverse('event-index'),
            'manifestations': reverse('master-event-list'),
        }

    def _account_pages(self):
        return {
            'account': reverse('account-index'),
            'activities': reverse('account-activities'),
            'my_events': reverse('account-events'),
        }

    def _manage_pages(self):
        """Management pages, each with the only persona that may open it."""
        data = self.data
        return {
            'manage_negozio': ('manager', reverse('location-manage', kwargs={'slug': data.negozio.slug})),
            'manage_circolo': ('manager', reverse('location-manage', kwargs={'slug': data.circolo.slug})),
            'manage_associazione': (
                'manager', reverse('location-manage', kwargs={'slug': data.associazione.slug})),
            'organized_events': (
                'manager', reverse('location-manage-events', kwargs={'slug': data.associazione.slug})),
            'manage_event': ('manager', reverse('event-manage', kwargs={'slug': data.event.slug})),
            'manage_draft_event': ('manager', reverse('event-manage', kwargs={'slug': data.draft_event.slug})),
            'manage_manifestation': (
                'organizer', reverse('master-event-manage', kwargs={'slug': data.manifestation.slug})),
        }

    def _login(self, persona):
        if persona == 'anonymous':
            self.client.logout()
        else:
            self.client.force_login(self.data.profile(persona).user)

    def _assert_renders(self, page, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        if page in UNTITLED_PAGES:
            return
        match = TITLE_RE.search(response.content.decode())
        self.assertTrue(match and match.group(1).strip(), 'empty <title>')

    def test_public_pages_render_for_every_audience(self):
        for persona in ('anonymous', *PERSONAS):
            self._login(persona)
            for page, url in self._pages().items():
                with self.subTest(persona=persona, page=page):
                    self._assert_renders(page, url)

    def test_account_pages_render_for_signed_in_users(self):
        for persona in PERSONAS:
            self._login(persona)
            for page, url in self._account_pages().items():
                with self.subTest(persona=persona, page=page):
                    self._assert_renders(page, url)

    def test_account_pages_ask_anonymous_visitors_to_sign_in(self):
        for page, url in self._account_pages().items():
            with self.subTest(page=page):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response['Location'])

    def test_manage_pages_render_for_their_manager(self):
        for page, (owner, url) in self._manage_pages().items():
            self._login(owner)
            with self.subTest(persona=owner, page=page):
                self._assert_renders(page, url)

    def test_manage_pages_are_closed_to_everyone_else(self):
        for persona in ('anonymous', *PERSONAS):
            self._login(persona)
            for page, (owner, url) in self._manage_pages().items():
                if persona == owner:
                    continue
                with self.subTest(persona=persona, page=page):
                    response = self.client.get(url)
                    self.assertNotEqual(response.status_code, 200)


class SeedUiPersonasCommandTest(TestCase):
    def _seed(self, *args):
        call_command('seed_ui_personas', *args, stdout=StringIO())

    def _counts(self):
        return [model.objects.count() for model in (UserProfile, Location, Table, Event, MasterEvent)]

    @override_settings(DEBUG=False)
    def test_refuses_to_run_without_debug(self):
        with self.assertRaises(CommandError):
            self._seed()
        self.assertEqual(self._counts(), [0, 0, 0, 0, 0])

    @override_settings(DEBUG=True)
    def test_reset_recreates_the_data_without_duplicates(self):
        self._seed()
        counts = self._counts()
        with self.assertRaises(CommandError):
            self._seed()
        self._seed('--reset')
        self.assertEqual(self._counts(), counts)
