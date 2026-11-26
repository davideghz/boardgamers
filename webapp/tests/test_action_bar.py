from django.test import TestCase
from django.urls import reverse

from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian


class ActionBarTest(TestCase):
    """F3: on every detail page Edit, Manage and More (Duplicate, Share) sit in one bar, with
    only the actions the viewer may use."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def bar(self, url, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        html = self.client.get(url).content.decode()
        start = html.index('data-action-bar')
        self.assertEqual(html.count('data-action-bar'), 1)
        return html[start:html.index('\n</div>', start)]

    def assert_actions(self, url, persona, *, edit=None, manage=None, duplicate=None):
        bar = self.bar(url, persona)
        self.assertIn('onclick="bgShare(this)"', bar)  # everyone may share
        for expected in (edit, manage, duplicate):
            if expected:
                self.assertIn(f'href="{expected}"', bar)
        self.assertEqual(bar.count('href="'), len([x for x in (edit, manage, duplicate) if x]))

    def test_location(self):
        circolo = self.data.circolo
        url = reverse('location-detail', args=[circolo.slug])
        self.assert_actions(url, 'manager', edit=reverse('location-manage-data', args=[circolo.slug]),
                            manage=reverse('location-manage', args=[circolo.slug]))
        self.assert_actions(url, 'member')
        self.assert_actions(url + '?as=visitor', 'manager')  # the preview shows what visitors get

    def test_table(self):
        table = self.data.tables['upcoming']
        url = reverse('table-detail', args=[table.slug])
        self.assert_actions(url, 'manager',
                            edit=reverse('location-table-update', args=[table.location.slug, table.slug]),
                            manage=reverse('table-players', args=[table.slug]),
                            duplicate=reverse('table-duplicate', args=[table.slug]))
        self.assertIn('Duplica', self.bar(url, 'manager'))
        self.assert_actions(url, 'player')
        self.assert_actions(url, None)

    def test_event_and_its_table(self):
        event, table = self.data.event, self.data.tables['event']
        self.assert_actions(reverse('event_detail', args=[event.slug]), 'manager',
                            edit=reverse('event-manage-data', args=[event.slug]),
                            manage=reverse('event-manage', args=[event.slug]))
        self.assert_actions(reverse('event_detail', args=[event.slug]), 'player')
        url = reverse('event_table_detail', args=[event.slug, table.slug])
        self.assert_actions(url, 'manager',
                            edit=reverse('event-table-update', args=[event.slug, table.slug]),
                            manage=reverse('table-players', args=[table.slug]))
        self.assert_actions(url, 'member')

    def test_festival(self):
        master = self.data.manifestation
        url = reverse('master-event-detail', args=[master.slug])
        self.assert_actions(url, 'organizer', manage=reverse('master-event-manage', args=[master.slug]))
        self.assert_actions(url, 'player')
