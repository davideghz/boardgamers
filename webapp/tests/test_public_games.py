from django.test import TestCase, Client
from django.urls import reverse
from django.utils.html import escape

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

    def test_on_by_default(self):
        self.assertTrue(self.location.enable_public_games)
        self.assertContains(self.client.get(self.detail_url), self.games_url)
        response = self.client.get(self.games_url)
        self.assertContains(response, "Terraforming Mars")
        self.assertNotContains(response, "Secret shelf")

    def test_manager_can_turn_it_off_and_on(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.toggle_url, {})
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_public_games)

        self.client.logout()
        self.assertEqual(self.client.get(self.games_url).status_code, 404)
        self.assertNotContains(self.client.get(self.detail_url), self.games_url)

        self.client.force_login(self.manager.user)
        self.client.post(self.toggle_url, {'enabled': 'on'})
        self.location.refresh_from_db()
        self.assertTrue(self.location.enable_public_games)

    def test_empty_library_hides_link_and_invites_managers(self):
        self.location.location_games.all().delete()
        manage_url = reverse('location-manage-games', kwargs={'slug': self.location.slug})
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, self.games_url)
        self.assertNotContains(response, manage_url)

        self.client.force_login(self.manager.user)
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, self.games_url)
        self.assertContains(response, manage_url)

    def test_outsider_cannot_toggle(self):
        self.client.force_login(self.outsider.user)
        response = self.client.post(self.toggle_url, {})
        self.assertEqual(response.status_code, 403)
        self.location.refresh_from_db()
        self.assertTrue(self.location.enable_public_games)

    def test_manage_page_shows_toggle(self):
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('location-manage-games', kwargs={'slug': self.location.slug}))
        self.assertContains(response, self.toggle_url)

    def test_game_detail_uses_general_list_for_direct_visit_or_hidden_library(self):
        game_url = reverse('game-detail', args=[self.game.slug])
        general_list = f'href="{reverse("game-list")}"'
        self.assertContains(self.client.get(game_url), general_list)

        self.location.enable_public_games = False
        self.location.save(update_fields=['enable_public_games'])
        response = self.client.get(game_url, {'from_location': self.location.slug})
        self.assertContains(response, general_list)
        self.assertNotContains(response, f'href="{self.games_url}"')


class PublicGamesPaginationTest(TestCase):
    def setUp(self):
        self.location = LocationFactory()
        for i in range(20):
            LocationGame.objects.create(location=self.location, game=GameFactory(name=f"Game {i:02d}"))
        LocationGame.objects.create(location=self.location, game=GameFactory(name="Wingspan"))
        self.games_url = reverse('location-games', kwargs={'slug': self.location.slug})

    def test_sixteen_games_per_page(self):
        response = self.client.get(self.games_url)
        self.assertEqual(len(response.context['location_games']), 16)
        self.assertEqual(response.context['total_count'], 21)
        self.assertTrue(response.context['is_paginated'])
        response = self.client.get(self.games_url, {'page': 2})
        self.assertEqual(len(response.context['location_games']), 5)
        self.assertContains(response, "Wingspan")

    def test_search_covers_all_pages(self):
        response = self.client.get(self.games_url, {'q': 'wing'})
        self.assertEqual([lg.game.name for lg in response.context['location_games']], ["Wingspan"])
        self.assertEqual(response.context['total_count'], 21)
        self.assertFalse(response.context['is_paginated'])

    def test_game_detail_links_back_to_library_search_and_page(self):
        query = {'q': 'Game', 'page': 2}
        response = self.client.get(self.games_url, query)
        game = response.context['location_games'][0].game
        game_url = reverse('game-detail', args=[game.slug], query={'from_location': self.location.slug, **query})
        self.assertContains(response, f'href="{escape(game_url)}"')

        back_url = reverse('location-games', args=[self.location.slug], query=query)
        detail = self.client.get(game_url)
        self.assertContains(detail, f'href="{escape(back_url)}"')
        self.assertEqual(self.client.get(back_url).context['page_obj'].number, 2)
