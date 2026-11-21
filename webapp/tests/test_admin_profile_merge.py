from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, SuperUserFactory, UserFactory, UserProfileFactory
from webapp.models import FavoriteUser, LocationFollower, Player, UserProfile
from webapp.tests.test_telegram_miniapp_bootstrap import make_table


class AdminProfileMergeTests(TestCase):
    def setUp(self):
        self.keeper = UserProfileFactory(nickname='manuzana')
        self.duplicate = UserProfileFactory(nickname='manuzana-xuhhje')
        self.location = LocationFactory(creator=self.duplicate)
        self.url = reverse('admin:webapp_userprofile_merge')
        self.ids = {'a': self.keeper.pk, 'b': self.duplicate.pk}
        self.client.force_login(SuperUserFactory())

    def test_action_previews_and_confirmation_transfers_records(self):
        response = self.client.post(reverse('admin:webapp_userprofile_changelist'), {
            'action': 'merge_profiles_action',
            '_selected_action': list(self.ids.values()),
        })
        self.assertRedirects(response, f'{self.url}?a={self.keeper.pk}&b={self.duplicate.pk}')
        self.assertTrue(UserProfile.objects.filter(pk=self.duplicate.pk).exists())
        self.assertEqual(self.client.post(self.url, self.ids).status_code, 200)
        self.assertTrue(UserProfile.objects.filter(pk=self.duplicate.pk).exists())

        social = UserSocialAuth.objects.create(user=self.duplicate.user, provider='telegram', uid='42')
        self.location.managers.add(self.keeper, self.duplicate)
        for profile in (self.keeper, self.duplicate):
            LocationFollower.objects.create(user_profile=profile, location=self.location)
        FavoriteUser.objects.create(owner=self.duplicate, favorite=self.keeper)
        table = make_table(location=self.location, author=self.duplicate)
        player = Player.objects.create(user_profile=self.duplicate, table=table)

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertRedirects(response, reverse('admin:webapp_userprofile_change', args=[self.keeper.pk]))
        self.location.refresh_from_db()
        table.refresh_from_db()
        player.refresh_from_db()
        social.refresh_from_db()
        self.assertEqual(self.location.creator_id, self.keeper.pk)
        self.assertEqual(list(self.location.managers.all()), [self.keeper])
        self.assertEqual(table.author_id, self.keeper.pk)
        self.assertEqual(player.user_profile_id, self.keeper.pk)
        self.assertEqual(social.user_id, self.keeper.user_id)
        self.assertEqual(LocationFollower.objects.filter(location=self.location).count(), 1)
        self.assertFalse(FavoriteUser.objects.exists())
        self.assertFalse(User.objects.filter(pk=self.duplicate.user_id).exists())
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.slug, 'manuzana')

    def test_conflicting_shared_table_rolls_back(self):
        table = make_table(location=self.location, author=self.duplicate)
        for position, profile in enumerate((self.keeper, self.duplicate), start=1):
            Player.objects.create(user_profile=profile, table=table, position=position)

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertContains(response, f'#{table.pk}')
        self.assertEqual(Player.objects.filter(table=table).count(), 2)
        self.assertTrue(UserProfile.objects.filter(pk=self.duplicate.pk).exists())

    def test_non_superuser_cannot_preview_or_merge(self):
        self.client.force_login(UserFactory(is_staff=True))
        self.assertEqual(self.client.get(self.url, self.ids).status_code, 403)
        self.assertEqual(self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk}).status_code, 403)
