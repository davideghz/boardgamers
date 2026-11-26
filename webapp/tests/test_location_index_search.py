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
        self.assertEqual(response.context['active_filters'], [('«Vicenza»', f'{self.url}?view=map')])
        self.assertContains(response, 'value="Vicenza"')
        self.assertRegex(response.content.decode(), r'>1</span>\s*</h1>')  # the count in the header
        self.assertContains(response, 'id="locations-view-field" value="map"')

    def test_your_locations_step_aside_while_searching(self):
        self.client.force_login(self.owner.user)
        self.assertTrue(self.locations()[0].context['user_created_locations'])
        self.assertIsNone(self.locations({'q': 'Padova'})[0].context['user_created_locations'])
