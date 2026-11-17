from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext

from webapp.factories import GameFactory, LocationFactory, TableFactory, UserProfileFactory
from webapp.models import LocationGame, LocationGameTag
from webapp.services.games import merge_games


class LocationGameWithdrawalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory()
        cls.location = LocationFactory(creator=cls.manager)
        cls.entry = LocationGame.objects.create(
            location=cls.location, game=GameFactory(name='Azul'), notes='Shelf A',
        )
        cls.tag = LocationGameTag.objects.create(location=cls.location, name='Family')
        cls.entry.tags.add(cls.tag)

    def setUp(self):
        self.client.force_login(self.manager.user)
        self.manage_url = self.url('location-manage-games')
        self.detail_url = self.game_url('location-game-detail')
        self.archive_url = self.game_url('location-game-archive')
        self.today = timezone.localdate()
        self.withdrawal = {
            'action': 'archive', 'withdrawn_on': self.today.isoformat(),
            'withdrawal_reason': LocationGame.WithdrawalReason.SOLD, 'withdrawal_note': 'Sold at the club fair',
        }

    def url(self, name, **kwargs):
        return reverse(name, kwargs={'slug': self.location.slug, **kwargs})

    def game_url(self, name):
        return self.url(name, game_uuid=self.entry.uuid)

    def test_withdrawal_moves_entry_to_archive_without_affecting_games_elsewhere(self):
        table = TableFactory(location=self.location, author=self.manager, game=self.entry.game)
        other_location = LocationFactory()
        LocationGame.objects.create(location=other_location, game=self.entry.game)
        registry_game_url = reverse('game-detail', kwargs={'slug': self.entry.game.slug})
        public_url = self.url('location-games')
        self.assertContains(self.client.get(self.detail_url), self.archive_url)
        form_page = self.client.get(self.archive_url)
        self.assertContains(form_page, f'value="{self.today.isoformat()}"')
        self.assertRedirects(self.client.post(self.archive_url, self.withdrawal), self.detail_url)

        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on, self.today)
        self.assertEqual(self.entry.withdrawal_reason, LocationGame.WithdrawalReason.SOLD)
        self.assertEqual(self.entry.withdrawal_note, 'Sold at the club fair')
        self.assertEqual(self.entry.notes, 'Shelf A')
        self.assertEqual(list(self.entry.tags.all()), [self.tag])
        self.assertNotContains(self.client.get(self.manage_url), self.detail_url)
        self.assertContains(self.client.get(self.manage_url, {'status': 'archived'}), self.detail_url)
        self.assertContains(self.client.get(self.detail_url), 'Sold at the club fair')
        self.assertNotContains(self.client.get(self.url('location-games-csv')), 'Azul')

        self.client.logout()
        catalog = self.client.get(public_url, {'q': 'Azul'})
        self.assertNotContains(catalog, registry_game_url)
        self.assertEqual(catalog.context['total_count'], 0)
        self.assertNotContains(self.client.get(self.url('location-detail')), public_url)
        self.assertContains(self.client.get(reverse('location-games', args=[other_location.slug])), registry_game_url)
        self.assertEqual(self.client.get(registry_game_url).status_code, 200)
        table.refresh_from_db()
        self.assertEqual(table.game_id, self.entry.game_id)

    def test_withdrawal_requires_valid_reason_and_nonfuture_date(self):
        invalid = {**self.withdrawal, 'withdrawal_reason': '',
                   'withdrawn_on': (self.today + timedelta(days=1)).isoformat()}
        form = self.client.post(self.archive_url, invalid).context['form']
        self.assertIn('withdrawal_reason', form.errors)
        self.assertIn('withdrawn_on', form.errors)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)

    def test_archived_entry_is_restored_explicitly(self):
        self.client.post(self.archive_url, self.withdrawal)
        form_data = {
            'game': self.entry.game_id, 'ownership': LocationGame.OWNED_BY_LOCATION,
            'physical_location': LocationGame.AT_ASSOCIATION,
        }
        response = self.client.post(self.url('location-add-game'), form_data)
        self.assertContains(response, gettext('Open archived entry'))
        self.assertContains(response, self.detail_url)
        self.assertEqual(self.location.location_games.count(), 1)

        self.assertRedirects(self.client.post(self.archive_url, {'action': 'restore'}), self.detail_url)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)
        self.assertIsNone(self.entry.withdrawn_on)
        self.assertEqual((self.entry.withdrawal_reason, self.entry.withdrawal_note), ('', ''))
        self.assertContains(self.client.get(self.manage_url), self.detail_url)
        self.assertContains(self.client.get(self.url('location-games-csv')), 'Azul')

    def test_legacy_archived_entry_can_be_restored(self):
        LocationGame.objects.filter(pk=self.entry.pk).update(is_archived=True)
        self.assertContains(self.client.get(self.detail_url), gettext('This game was archived without a date or reason.'))
        self.assertRedirects(self.client.post(self.archive_url, {'action': 'restore'}), self.detail_url)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)

    def test_outsiders_cannot_access_or_change_withdrawal_details(self):
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(self.manage_url, {'status': 'archived'}).status_code, 403)
        self.assertEqual(self.client.get(self.archive_url).status_code, 403)
        self.assertEqual(self.client.post(self.archive_url, self.withdrawal).status_code, 403)

    def test_merging_with_an_active_entry_keeps_the_title_in_the_current_catalog(self):
        self.client.post(self.archive_url, self.withdrawal)
        active = LocationGame.objects.create(
            location=self.location, game=GameFactory(), physical_location=LocationGame.AT_HOME,
        )
        merge_games(self.entry.game, active.game, {})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)
        self.assertIsNone(self.entry.withdrawn_on)
        self.assertEqual(self.entry.withdrawal_reason, '')
        self.assertEqual(self.entry.physical_location, LocationGame.AT_HOME)
        self.assertEqual(self.location.location_games.count(), 1)
