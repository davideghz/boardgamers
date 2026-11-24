import datetime

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory, TableFactory
from webapp.models import GameOutcome, GuestProfile, Player, ResultMode


class LocationGameLeaderboardTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.alice = UserProfileFactory(nickname="Alice")
        self.bob = UserProfileFactory(nickname="Bob")
        self.guest = GuestProfile.objects.create(owner=self.alice, name="Carla")
        self.location = LocationFactory(creator=self.alice)
        self.other_location = LocationFactory(creator=self.alice)
        self.game = GameFactory(name="Azul")
        self.rpg = GameFactory(name="GDR")
        past = timezone.localdate() - datetime.timedelta(days=5)

        # Alice wins twice, Bob once; the guest plays three times without medals.
        for winner, other in ((self.alice, self.bob), (self.alice, self.bob), (self.bob, self.alice)):
            table = self._table(self.game, past)
            Player.objects.create(table=table, user_profile=winner, position=1)
            Player.objects.create(table=table, user_profile=other, position=2)
            Player.objects.create(table=table, guest_profile=self.guest, position=99)
        # Not counted: another location, a table without a leaderboard, a future table.
        Player.objects.create(table=self._table(self.game, past, location=self.other_location),
                              user_profile=self.bob, position=1)
        Player.objects.create(table=self._table(self.game, past, result_mode=ResultMode.NONE),
                              user_profile=self.bob, position=1)
        Player.objects.create(table=self._table(self.game, timezone.localdate() + datetime.timedelta(days=5)),
                              user_profile=self.bob, position=1)
        self._table(self.rpg, past)

    def _table(self, game, date, location=None, result_mode=ResultMode.FFA):
        return TableFactory(game=game, date=date, location=location or self.location,
                            author=self.alice, result_mode=result_mode)

    def test_played_games_page_links_to_each_game(self):
        response = self.client.get(reverse('location-played-games', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)
        games = list(response.context['played_games'])
        self.assertEqual(games, [self.game, self.rpg])
        self.assertEqual(games[0].play_count, 4)
        self.assertContains(response, reverse('location-game-leaderboard',
                                              kwargs={'slug': self.location.slug, 'game_slug': self.game.slug}))

    def test_game_leaderboard(self):
        response = self.client.get(reverse('location-game-leaderboard',
                                           kwargs={'slug': self.location.slug, 'game_slug': self.game.slug}))
        self.assertEqual(response.status_code, 200)
        rows = response.context['leaderboard']
        self.assertEqual([(r['user'] or r['guest']).pk for r in rows], [self.alice.pk, self.bob.pk, self.guest.pk])
        self.assertEqual((rows[0]['first_place'], rows[0]['second_place'], rows[0]['play_count']), (2, 1, 3))
        self.assertEqual((rows[1]['first_place'], rows[1]['second_place'], rows[1]['play_count']), (1, 2, 3))
        self.assertEqual((rows[2]['first_place'], rows[2]['play_count']), (0, 3))
        self.assertContains(response, "Carla")

    def test_unplayed_game_is_404(self):
        game = GameFactory(name="Never played")
        response = self.client.get(reverse('location-game-leaderboard',
                                           kwargs={'slug': self.location.slug, 'game_slug': game.slug}))
        self.assertEqual(response.status_code, 404)

    def test_played_games_search(self):
        response = self.client.get(reverse('location-played-games', args=[self.location.slug]), {'q': 'azu'})
        self.assertEqual(list(response.context['played_games']), [self.game])

    def test_location_page_links_to_leaderboards(self):
        response = self.client.get(reverse('location-detail', kwargs={'slug': self.location.slug}))
        self.assertContains(response, reverse('location-played-games', kwargs={'slug': self.location.slug}))
        self.assertContains(response, reverse('location-game-leaderboard',
                                              kwargs={'slug': self.location.slug, 'game_slug': self.game.slug}))

    def leaderboard(self, game=None):
        response = self.client.get(reverse('location-game-leaderboard', args=[self.location.slug, (game or self.game).slug]))
        return response.context['leaderboard']

    def test_hidden_statistics_are_not_public(self):
        games_url = reverse('location-played-games', args=[self.location.slug])
        leaderboard_url = reverse('location-game-leaderboard', args=[self.location.slug, self.game.slug])
        for most_played, top_gamers, games_status, leaderboard_status in (
                (True, True, 200, 200), (True, False, 200, 404), (False, True, 404, 404), (False, False, 404, 404)):
            with self.subTest(most_played=most_played, top_gamers=top_gamers):
                self.location.show_most_played_games = most_played
                self.location.show_top_gamers = top_gamers
                self.location.save()
                self.assertEqual(self.client.get(leaderboard_url).status_code, leaderboard_status)
                response = self.client.get(games_url)
                self.assertEqual(response.status_code, games_status)
                if games_status == 200:
                    self.assertEqual(leaderboard_url in response.content.decode(), top_gamers)
                detail = self.client.get(reverse('location-detail', args=[self.location.slug])).content.decode()
                self.assertEqual(leaderboard_url in detail, most_played and top_gamers)
                self.assertEqual(games_url + '"' in detail, most_played)

    def test_played_games_are_paginated(self):
        past = timezone.localdate() - datetime.timedelta(days=5)
        for i in range(45):
            self._table(GameFactory(name=f"Game {i:02d}"), past)
        url = reverse('location-played-games', args=[self.location.slug])
        response = self.client.get(url, {'q': 'Game'})
        self.assertEqual(len(response.context['played_games']), 40)
        self.assertContains(response, 'q=Game&amp;page=2')
        self.assertEqual(len(self.client.get(url, {'q': 'Game', 'page': 2}).context['played_games']), 5)

    def test_todays_tables_are_not_played_yet(self):
        game = GameFactory(name="Today")
        Player.objects.create(table=self._table(game, timezone.localdate()), user_profile=self.bob, position=1)
        url = reverse('location-game-leaderboard', args=[self.location.slug, game.slug])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_tables_without_a_result_do_not_count(self):
        game = GameFactory(name="No results")
        past = timezone.localdate() - datetime.timedelta(days=5)
        Player.objects.create(table=self._table(game, past), user_profile=self.bob)
        self.assertEqual(self.leaderboard(game), [])
        lost = self._table(game, past, result_mode=ResultMode.COOP)
        lost.game_outcome = GameOutcome.LOST
        lost.save()
        Player.objects.create(table=lost, user_profile=self.alice)
        rows = self.leaderboard(game)
        self.assertEqual([(r['user'], r['play_count'], r['first_place']) for r in rows], [(self.alice, 1, 0)])

    def test_equal_players_share_the_rank_in_a_stable_order(self):
        game = GameFactory(name="Ties")
        table = self._table(game, timezone.localdate() - datetime.timedelta(days=5))
        Player.objects.create(table=table, user_profile=self.bob, position=1)
        Player.objects.create(table=table, user_profile=self.alice, position=1)
        Player.objects.create(table=table, guest_profile=self.guest, position=3)
        self.assertEqual([(r['name'], r['rank']) for r in self.leaderboard(game)], [('Alice', 1), ('Bob', 1), ('Carla', 3)])

    def test_winners_on_the_location_page_match_the_leaderboard(self):
        game = GameFactory(name="Guest wins")
        past = timezone.localdate() - datetime.timedelta(days=5)
        Player.objects.create(table=self._table(game, past), guest_profile=self.guest, position=1)
        response = self.client.get(reverse('location-detail', args=[self.location.slug]))
        winners = {g.name: g.top_winners for g in response.context['popular_games']}
        self.assertEqual(winners["Guest wins"], ["Carla"])
        self.assertEqual(winners["Azul"], ["Alice"])
        self.assertEqual(winners["GDR"], [])
