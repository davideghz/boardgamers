from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from webapp.factories import LocationFactory, UserProfileFactory


class AddressPromptTest(TestCase):
    """The "set your address" prompt follows the coordinates the nearby search
    uses: Google may not return a city for an address it located."""

    def setUp(self):
        # The home page shows the locations section, and the prompt, only when there are locations.
        LocationFactory(creator=UserProfileFactory())

    def _get(self, url_name, **profile_fields):
        profile = UserProfileFactory(preferred_language='en', **profile_fields)
        self.client.force_login(profile.user)
        with translation.override('en'):
            return self.client.get(reverse(url_name))

    def test_located_profile_without_city_is_not_asked_for_an_address(self):
        for url_name in ('home', 'locations-index'):
            with self.subTest(url_name):
                response = self._get(url_name, address='Via Roma 1, Vigonza', city='',
                                     latitude='45.44', longitude='11.98')

                self.assertNotContains(response, 'Set your address')
                self.assertContains(response, '<strong>Via Roma 1, Vigonza</strong>', html=True)

    def test_located_profile_shows_the_city(self):
        response = self._get('home', address='Via Roma 1, Padova', city='Padova',
                             latitude='45.40', longitude='11.87')

        self.assertNotContains(response, 'Set your address')
        self.assertContains(response, '<strong>Padova</strong>', html=True)

    def test_profile_without_coordinates_is_asked_for_an_address(self):
        for url_name in ('home', 'locations-index'):
            with self.subTest(url_name):
                response = self._get(url_name, address='', city='Padova', latitude=None, longitude=None)

                self.assertContains(response, 'Set your address')
