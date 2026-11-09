import datetime

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory, TableFactory
from webapp.models import GuestProfile, Player, ResultMode


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

        # Alice wins twice, Bob once; the guest plays twice without medals.
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

    def test_played_games_page_lists_games_without_rpg(self):
        response = self.client.get(reverse('location-played-games', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)
        games = list(response.context['played_games'])
        self.assertEqual(games, [self.game])
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

    def test_unplayed_or_rpg_game_is_404(self):
        for game in (self.rpg, GameFactory(name="Never played")):
            response = self.client.get(reverse('location-game-leaderboard',
                                               kwargs={'slug': self.location.slug, 'game_slug': game.slug}))
            self.assertEqual(response.status_code, 404)

    def test_location_page_links_to_leaderboards(self):
        response = self.client.get(reverse('location-detail', kwargs={'slug': self.location.slug}))
        self.assertContains(response, reverse('location-played-games', kwargs={'slug': self.location.slug}))
        self.assertContains(response, reverse('location-game-leaderboard',
                                              kwargs={'slug': self.location.slug, 'game_slug': self.game.slug}))
