from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.tests.test_location_table_access import italian


class LocationIndexSearchTest(TestCase):
    """E4: find a location by name or city without scrolling the list or using the map."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory()
        cls.vicenza = LocationFactory(name='Magno Gato', city='Vicenza', creator=cls.owner)
        cls.padova = LocationFactory(name='Dadi e Draghi', city='Padova')
        cls.url = reverse('locations-index')

    def locations(self, params=None):
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response, set(response.context['nearby_locations'])

    def test_by_name_or_city(self):
        self.assertEqual(self.locations({'q': 'magno'})[1], {self.vicenza})
        self.assertEqual(self.locations({'q': 'PADOVA'})[1], {self.padova})
        response, found = self.locations({'q': 'Treviso'})
        self.assertEqual(found, set())
        self.assertContains(response, italian('No locations match your search.'))

    def test_null_characters_are_dropped(self):
        response, found = self.locations({'q': 'Mag\x00no'})
        self.assertEqual(found, {self.vicenza})
        self.assertEqual(response.context['q'], 'Magno')

    def test_header_count_chip_and_view(self):
        response, _ = self.locations({'q': 'Vicenza', 'view': 'map'})
        self.assertTrue(response.context['has_filters'])
        self.assertEqual(response.context['reset_url'], f'{self.url}?view=map')  # Clear all keeps the view
        self.assertContains(response, 'value="Vicenza"')
        self.assertRegex(response.content.decode(), r'>1</span>\s*</h1>')  # the count in the header
        self.assertContains(response, 'id="locations-view-field" value="map"')

    def test_your_locations_step_aside_while_searching(self):
        self.client.force_login(self.owner.user)
        self.assertTrue(self.locations()[0].context['my_locations'])
        self.assertEqual(self.locations({'q': 'Padova'})[0].context['my_locations'], [])


class LocationIndexNearAndNetworkTest(TestCase):
    """Where to play: "Near" (address, where I am now, anywhere) and the national network, as
    filter chips, for each persona."""

    @classmethod
    def setUpTestData(cls):
        from webapp.services.ui_personas import seed_ui_personas
        cls.data = seed_ui_personas()
        cls.url = reverse('locations-index')

    def get(self, persona=None, **params):
        self.client.logout() if persona is None else self.client.force_login(self.data.profile(persona).user)
        return self.client.get(self.url, params)

    def names(self, response):
        return [location.name for location in response.context['nearby_locations']]

    def test_near_by_persona(self):
        visitor = self.get()
        self.assertEqual(visitor.context['near'], 'anywhere')  # no address, no position yet
        self.assertEqual(self.names(visitor), sorted(self.names(visitor)))  # by name, not at random
        self.assertContains(visitor, italian('Anywhere, by name'))
        self.assertNotContains(visitor, italian('Set your address'))
        for persona in ('newcomer', 'player', 'member', 'manager', 'organizer'):  # all live in Milano
            with self.subTest(persona):
                response = self.get(persona)
                self.assertEqual(response.context['near'], 'address')
                self.assertContains(response, italian('My address (%(place)s)') % {'place': 'Milano'})
                self.assertEqual(response.context['nearby_locations'][0].distance.m, 0)

    def test_without_an_address_the_menu_asks_for_it(self):
        newcomer = self.data.newcomer
        newcomer.latitude = newcomer.longitude = None
        newcomer.save(update_fields=['latitude', 'longitude'])
        response = self.get('newcomer')
        self.assertEqual(response.context['near'], 'anywhere')
        self.assertContains(response, f'href="{reverse("user-profile-edit")}"')

    def test_where_i_am_now_stays_in_the_session_rounded_and_out_of_the_url(self):
        response = self.client.post(reverse('locations-near'), {
            'lat': '45.46421', 'lng': '9.18951', 'q': 'Demo', 'network': 'rete-ludica-demo', 'view': 'map',
            'next': 'https://example.com/'})
        self.assertRedirects(response, f'{self.url}?q=Demo&network=rete-ludica-demo&view=map&near=here',
                             fetch_redirect_response=False)
        self.assertEqual(self.client.session['locations_near_point'], [45.46, 9.19])
        response = self.client.get(self.url)  # remembered for the visit: the default now
        self.assertEqual(response.context['near'], 'here')
        self.assertContains(response, italian('Near you'))
        self.assertContains(response, '<input type="hidden" name="lat">')  # the page doesn't repeat it
        self.assertEqual(self.client.get(self.url, {'near': 'anywhere'}).context['near'], 'anywhere')

        for bad in ({'lat': '91', 'lng': '9'}, {'lat': 'x', 'lng': '9'}, {}):
            with self.subTest(bad):
                self.client.session.flush()
                response = self.client.post(reverse('locations-near'), bad)
                self.assertNotIn('near=here', response.url)
        self.assertEqual(self.client.get(reverse('locations-near')).status_code, 405)

    def test_network_chip_lists_the_active_networks_and_filters(self):
        response = self.get('player')
        self.assertContains(response, 'popovertarget="locations-network-menu"')
        for name in ('Federazione Demo', 'Rete Ludica Demo'):
            self.assertContains(response, name)
        response = self.get('player', network='rete-ludica-demo', near='anywhere', view='map')
        self.assertEqual(self.names(response), ['Associazione Demo', 'Circolo Demo'])
        self.assertEqual(response.context['my_locations'], [])
        self.assertEqual(response.context['reset_url'], f'{self.url}?view=map&near=anywhere')  # keeps both
