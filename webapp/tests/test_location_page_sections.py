from django.test import TestCase, Client
from django.urls import reverse
from django.utils import translation

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory
from webapp.models import LocationGame

# Pages render in Italian, the default language.
with translation.override('it'):
    MOST_PLAYED = translation.gettext("Most played games")
    TOP_GAMERS = translation.gettext("Top gamers")


class LocationPageSectionsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.detail_url = reverse('location-detail', kwargs={'slug': self.location.slug})
        self.manage_url = reverse('location-manage-data', kwargs={'slug': self.location.slug})

    def _location_data(self, **overrides):
        return {
            'name': self.location.name,
            'description': 'Description',
            'address': 'Address',
            'city': 'City',
            'latitude': '45.0',
            'longitude': '9.0',
            'leaderboard_edit_days': 2,
            **overrides,
        }

    def test_sections_shown_by_default(self):
        self.assertTrue(self.location.show_most_played_games)
        self.assertTrue(self.location.show_top_gamers)
        response = self.client.get(self.detail_url)
        self.assertContains(response, MOST_PLAYED)
        self.assertContains(response, TOP_GAMERS)

    def test_hidden_sections(self):
        self.location.show_most_played_games = False
        self.location.show_top_gamers = False
        self.location.save()
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, MOST_PLAYED)
        self.assertNotContains(response, TOP_GAMERS)
        self.assertEqual(response.context['popular_games'], [])
        self.assertEqual(response.context['player_stats'], [])

    def test_hidden_most_played_games_keeps_library_link(self):
        LocationGame.objects.create(location=self.location, game=GameFactory())
        self.location.show_most_played_games = False
        self.location.save()
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, MOST_PLAYED)
        self.assertContains(response, reverse('location-games', kwargs={'slug': self.location.slug}))

    def test_manager_can_toggle_sections(self):
        self.client.force_login(self.owner.user)
        self.client.post(self.manage_url, self._location_data())
        self.location.refresh_from_db()
        self.assertFalse(self.location.show_most_played_games)
        self.assertFalse(self.location.show_top_gamers)

        self.client.post(self.manage_url, self._location_data(show_most_played_games='on', show_top_gamers='on'))
        self.location.refresh_from_db()
        self.assertTrue(self.location.show_most_played_games)
        self.assertTrue(self.location.show_top_gamers)
