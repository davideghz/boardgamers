from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory
from webapp.models import LocationGame


class PublicGamesToggleTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.game = GameFactory(name="Terraforming Mars")
        LocationGame.objects.create(location=self.location, game=self.game, notes="Secret shelf")
        self.detail_url = reverse('location-detail', kwargs={'slug': self.location.slug})
        self.games_url = reverse('location-games', kwargs={'slug': self.location.slug})
        self.toggle_url = reverse('location-toggle-public-games', kwargs={'slug': self.location.slug})

    def test_off_by_default_and_hidden(self):
        self.assertFalse(self.location.enable_public_games)
        self.assertEqual(self.client.get(self.games_url).status_code, 404)
        self.assertNotContains(self.client.get(self.detail_url), self.games_url)

    def test_manager_can_turn_it_on_and_off(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.toggle_url, {'enabled': 'on'})
        self.location.refresh_from_db()
        self.assertTrue(self.location.enable_public_games)

        self.client.logout()
        self.assertContains(self.client.get(self.detail_url), self.games_url)
        response = self.client.get(self.games_url)
        self.assertContains(response, "Terraforming Mars")
        self.assertNotContains(response, "Secret shelf")

        self.client.force_login(self.manager.user)
        self.client.post(self.toggle_url, {})
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_public_games)

    def test_outsider_cannot_toggle(self):
        self.client.force_login(self.outsider.user)
        response = self.client.post(self.toggle_url, {'enabled': 'on'})
        self.assertEqual(response.status_code, 403)
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_public_games)

    def test_manage_page_shows_toggle(self):
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('location-manage-games', kwargs={'slug': self.location.slug}))
        self.assertContains(response, self.toggle_url)
