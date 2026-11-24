from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory, TableFactory
from webapp.models import LocationGame

# Pages render in Italian, the default language.
with translation.override('it'):
    MOST_PLAYED = translation.gettext("Most played games")
    TOP_GAMERS = translation.gettext("Top gamers")
    TOTAL_GAMERS = translation.gettext("Total gamers")
    TOTAL_TABLES = translation.gettext("Total tables")


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
        self.assertTrue(self.location.show_stats)
        self.assertTrue(self.location.show_top_gamers)
        response = self.client.get(self.detail_url)
        self.assertContains(response, MOST_PLAYED)
        self.assertContains(response, TOTAL_GAMERS)
        self.assertContains(response, TOTAL_TABLES)
        self.assertContains(response, TOP_GAMERS)

    def test_hidden_stats_keep_tables_and_other_sections_visible(self):
        today = timezone.localdate()
        TableFactory(location=self.location, author=self.owner, date=today - timedelta(days=1),
                     title='Past table for stats')
        TableFactory(location=self.location, author=self.owner, date=today + timedelta(days=1),
                     title='Upcoming table for stats')
        response = self.client.get(self.detail_url)
        self.assertEqual(response.context['total_gamers_count'], 1)
        self.assertEqual(response.context['tables_count'], 2)

        self.location.show_stats = False
        self.location.save(update_fields=['show_stats'])
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, TOTAL_GAMERS)
        self.assertNotContains(response, TOTAL_TABLES)
        self.assertNotIn('total_gamers_count', response.context)
        self.assertNotIn('tables_count', response.context)
        self.assertContains(response, 'Past table for stats')
        self.assertContains(response, 'Upcoming table for stats')
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

    def test_owner_and_manager_can_toggle_stats(self):
        manager = UserProfileFactory()
        self.location.managers.add(manager)
        data = self._location_data(show_most_played_games='on', show_top_gamers='on')

        for profile in (self.owner, manager):
            with self.subTest(profile=profile):
                self.client.force_login(profile.user)
                self.assertContains(self.client.get(self.manage_url), 'name="show_stats"')
                self.assertRedirects(self.client.post(self.manage_url, data), self.detail_url)
                self.location.refresh_from_db()
                self.assertFalse(self.location.show_stats)
                self.assertTrue(self.location.show_most_played_games)
                self.assertTrue(self.location.show_top_gamers)

                response = self.client.post(self.manage_url, {**data, 'show_stats': 'on'})
                self.assertRedirects(response, self.detail_url)
                self.location.refresh_from_db()
                self.assertTrue(self.location.show_stats)

    def test_other_user_cannot_toggle_stats(self):
        self.client.force_login(UserProfileFactory().user)
        response = self.client.post(self.manage_url, self._location_data())
        self.assertEqual(response.status_code, 403)
        self.location.refresh_from_db()
        self.assertTrue(self.location.show_stats)
