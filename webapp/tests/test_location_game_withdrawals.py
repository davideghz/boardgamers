from datetime import timedelta

from django.test import Client, TestCase
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

    def restore_entry(self):
        confirmation = self.client.get(self.archive_url, {'action': 'restore'})
        return self.client.post(self.archive_url, {
            'action': 'restore', 'confirmed': 'yes',
            'withdrawal_version': confirmation.context['withdrawal_version'],
        })

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

        self.assertRedirects(self.restore_entry(), self.detail_url)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on, self.today)
        self.assertEqual(self.entry.withdrawal_reason, self.withdrawal['withdrawal_reason'])
        self.assertEqual(self.entry.withdrawal_note, self.withdrawal['withdrawal_note'])
        detail = self.client.get(self.detail_url)
        self.assertContains(detail, gettext('Last recorded withdrawal'))
        self.assertContains(detail, self.withdrawal['withdrawal_note'])
        self.assertContains(self.client.get(self.manage_url), self.detail_url)
        self.assertContains(self.client.get(self.url('location-games-csv')), 'Azul')

    def test_legacy_archived_entry_can_be_restored(self):
        LocationGame.objects.filter(pk=self.entry.pk).update(is_archived=True)
        self.assertContains(self.client.get(self.detail_url), gettext('This game was archived without a date or reason.'))
        self.assertRedirects(self.restore_entry(), self.detail_url)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)

    def test_outsiders_cannot_access_or_change_withdrawal_details(self):
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(self.manage_url, {'status': 'archived'}).status_code, 403)
        self.assertEqual(self.client.get(self.archive_url).status_code, 403)
        self.assertEqual(self.client.post(self.archive_url, self.withdrawal).status_code, 403)
        for action in ('update', 'restore'):
            self.assertEqual(self.client.get(self.archive_url, {'action': action}).status_code, 403)
            self.assertEqual(self.client.post(self.archive_url, {'action': action}).status_code, 403)

    def test_withdrawal_can_be_edited_while_the_game_stays_archived(self):
        self.client.post(self.archive_url, self.withdrawal)
        response = self.client.get(self.archive_url, {'action': 'update'})
        self.assertEqual(response.context['form']['withdrawn_on'].value(), self.today)
        self.assertEqual(response.context['form']['withdrawal_reason'].value(), self.withdrawal['withdrawal_reason'])
        self.assertContains(response, self.withdrawal['withdrawal_note'])
        correction = {
            'action': 'update', 'withdrawn_on': (self.today - timedelta(days=3)).isoformat(),
            'withdrawal_reason': LocationGame.WithdrawalReason.LOST, 'withdrawal_note': 'Missing after game night',
            'withdrawal_version': response.context['withdrawal_version'],
        }
        self.assertRedirects(self.client.post(self.archive_url, correction), self.detail_url)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on.isoformat(), correction['withdrawn_on'])
        self.assertEqual(self.entry.withdrawal_reason, correction['withdrawal_reason'])
        self.assertEqual(self.entry.withdrawal_note, correction['withdrawal_note'])
        self.assertEqual(list(self.entry.tags.all()), [self.tag])
        self.assertNotContains(self.client.get(self.url('location-games')), 'Azul')

    def test_invalid_correction_keeps_the_recorded_withdrawal(self):
        self.client.post(self.archive_url, self.withdrawal)
        response = self.client.get(self.archive_url, {'action': 'update'})
        correction = {
            **self.withdrawal, 'action': 'update',
            'withdrawn_on': (self.today + timedelta(days=1)).isoformat(), 'withdrawal_reason': '',
            'withdrawal_note': 'Unsaved correction', 'withdrawal_version': response.context['withdrawal_version'],
        }
        response = self.client.post(self.archive_url, correction)
        self.assertIn('withdrawn_on', response.context['form'].errors)
        self.assertIn('withdrawal_reason', response.context['form'].errors)
        self.assertContains(response, 'Unsaved correction')
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawal_note, self.withdrawal['withdrawal_note'])
        self.assertEqual(self.entry.withdrawn_on, self.today)

    def test_restore_requires_confirmation_and_cancel_leaves_the_entry_archived(self):
        self.client.post(self.archive_url, self.withdrawal)
        response = self.client.get(self.archive_url, {'action': 'restore'})
        self.assertContains(response, gettext('Confirm restore'))
        self.assertContains(response, self.withdrawal['withdrawal_note'])
        self.assertContains(response, f'href="{self.detail_url}"')
        self.client.get(self.detail_url)
        unconfirmed = self.client.post(self.archive_url, {'action': 'restore'})
        self.assertContains(unconfirmed, gettext('Confirm restore'))
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawal_note, self.withdrawal['withdrawal_note'])

    def test_a_new_withdrawal_replaces_the_last_recorded_details(self):
        self.client.post(self.archive_url, self.withdrawal)
        self.restore_entry()
        form = self.client.get(self.archive_url).context['form']
        self.assertIsNone(form['withdrawal_note'].value())
        replacement = {**self.withdrawal, 'withdrawal_reason': LocationGame.WithdrawalReason.DESTROYED,
                       'withdrawal_note': '', 'withdrawn_on': (self.today - timedelta(days=1)).isoformat()}
        self.client.post(self.archive_url, replacement)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on.isoformat(), replacement['withdrawn_on'])
        self.assertEqual(self.entry.withdrawal_reason, LocationGame.WithdrawalReason.DESTROYED)
        self.assertEqual(self.entry.withdrawal_note, '')

    def test_stale_edit_and_restore_cannot_overwrite_a_corrected_withdrawal(self):
        self.client.post(self.archive_url, self.withdrawal)
        response = self.client.get(self.archive_url, {'action': 'update'})
        correction = {**self.withdrawal, 'action': 'update', 'withdrawal_note': 'Corrected note',
                      'withdrawal_version': response.context['withdrawal_version']}
        self.client.post(self.archive_url, correction)
        for data in (dict(correction, withdrawal_note='Stale note'), {
            'action': 'restore', 'confirmed': 'yes', 'withdrawal_version': correction['withdrawal_version'],
        }):
            self.assertRedirects(self.client.post(self.archive_url, data), self.detail_url)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawal_note, 'Corrected note')

    def test_edit_after_restore_cannot_archive_the_game_again(self):
        self.client.post(self.archive_url, self.withdrawal)
        response = self.client.get(self.archive_url, {'action': 'update'})
        self.restore_entry()
        self.client.post(self.archive_url, {**self.withdrawal, 'action': 'update',
                                          'withdrawal_version': response.context['withdrawal_version']})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)

    def test_restore_and_edit_require_csrf_and_the_correct_location(self):
        self.client.post(self.archive_url, self.withdrawal)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.manager.user)
        self.assertEqual(csrf_client.post(self.archive_url, {'action': 'restore', 'confirmed': 'yes'}).status_code, 403)
        self.assertEqual(csrf_client.post(self.archive_url, {'action': 'update'}).status_code, 403)
        other_location = LocationFactory(creator=self.manager)
        foreign_url = reverse('location-game-archive', args=[other_location.slug, self.entry.uuid])
        self.assertEqual(self.client.get(foreign_url, {'action': 'update'}).status_code, 404)
        self.assertEqual(self.client.post(foreign_url, {'action': 'restore', 'confirmed': 'yes'}).status_code, 404)

    def test_merging_with_an_active_entry_keeps_the_title_in_the_current_catalog(self):
        self.client.post(self.archive_url, self.withdrawal)
        active = LocationGame.objects.create(
            location=self.location, game=GameFactory(), physical_location=LocationGame.AT_HOME,
        )
        merge_games(self.entry.game, active.game, {})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on, self.today)
        self.assertEqual(self.entry.withdrawal_reason, self.withdrawal['withdrawal_reason'])
        self.assertEqual(self.entry.physical_location, LocationGame.AT_HOME)
        self.assertEqual(self.location.location_games.count(), 1)

    def test_merging_active_entries_preserves_the_latest_withdrawal(self):
        self.client.post(self.archive_url, {**self.withdrawal, 'withdrawn_on': (self.today - timedelta(days=3)).isoformat()})
        self.restore_entry()
        duplicate = LocationGame.objects.create(
            location=self.location, game=GameFactory(), withdrawn_on=self.today,
            withdrawal_reason=LocationGame.WithdrawalReason.LOST, withdrawal_note='Latest withdrawal',
        )
        merge_games(self.entry.game, duplicate.game, {})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_archived)
        self.assertEqual(self.entry.withdrawn_on, self.today)
        self.assertEqual(self.entry.withdrawal_note, 'Latest withdrawal')

    def test_merging_an_archived_duplicate_keeps_its_latest_withdrawal(self):
        for is_archived in (False, True):
            with self.subTest(kept_is_archived=is_archived):
                LocationGame.objects.filter(pk=self.entry.pk).update(
                    is_archived=is_archived, withdrawn_on=self.today - timedelta(days=3),
                    withdrawal_reason=LocationGame.WithdrawalReason.SOLD, withdrawal_note='Older withdrawal',
                )
                duplicate = LocationGame.objects.create(
                    location=self.location, game=GameFactory(), is_archived=True, withdrawn_on=self.today,
                    withdrawal_reason=LocationGame.WithdrawalReason.LOST, withdrawal_note='Latest withdrawal',
                )
                merge_games(self.entry.game, duplicate.game, {})
                self.entry.refresh_from_db()
                self.assertEqual(self.entry.is_archived, is_archived)
                self.assertEqual(self.entry.withdrawn_on, self.today)
                self.assertEqual(self.entry.withdrawal_reason, LocationGame.WithdrawalReason.LOST)
                self.assertEqual(self.entry.withdrawal_note, 'Latest withdrawal')
