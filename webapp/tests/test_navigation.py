import re

from django.test import TestCase
from django.urls import reverse

from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian


class NavigationTest(TestCase):
    """One navigation partial for the sidebar and the mobile drawer (E1)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, url, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(url)

    def menus(self, response):
        html = response.content.decode()
        label = f'aria-label="{italian("Main menu")}"'
        return [html[start:html.index('</nav>', start)] for start in [m.start() for m in re.finditer(re.escape(label), html)]]

    def test_the_same_menu_in_the_sidebar_and_the_drawer(self):
        menus = self.menus(self.get(reverse('home'), 'member'))
        self.assertEqual(len(menus), 2)
        self.assertEqual(menus[0], menus[1])

    def test_entries(self):
        menu = self.menus(self.get(reverse('home'), 'member'))[0]
        for url in (reverse('home'), reverse('account-activities'), reverse('appointment-search'),
                    reverse('locations-index'), reverse('game-list'), reverse('about')):
            self.assertIn(f'href="{url}"', menu)
        # Kinds of activity and creation leave the menu (E3 presets, F1 "+ Create")
        for url in (reverse('event-index'), reverse('master-event-list'), reverse('table-index'),
                    reverse('location-create'), reverse('account-tables')):
            self.assertNotIn(f'href="{url}"', menu)

    def test_main_button_by_profile(self):
        find = f'{reverse("appointment-search")}?type=tables'
        create = f'{reverse("locations-index")}?new_table=1'
        for persona, expected in ((None, find), ('newcomer', find), ('player', create), ('member', create),
                                  ('manager', create)):
            with self.subTest(persona or 'anonymous'):
                response = self.get(reverse('about'), persona)
                self.assertContains(response, f'id="sidebar-cta" href="{expected}"')

    def test_current_page(self):
        cases = {
            reverse('appointment-search'): reverse('appointment-search'),
            reverse('location-detail', args=[self.data.circolo.slug]): reverse('locations-index'),
            reverse('home'): reverse('home'),
        }
        for url, current in cases.items():
            with self.subTest(url):
                menu = self.menus(self.get(url, 'member'))[0]
                self.assertEqual(re.findall(r'href="([^"]+)" data-label="[^"]*" aria-current="page"', menu), [current])

    def test_the_closed_drawer_is_out_of_the_tab_order(self):
        response = self.get(reverse('home'))
        self.assertContains(response, '<div id="mobile-drawer" inert')
        self.assertContains(response, 'aria-controls="mobile-drawer" aria-expanded="false"')
