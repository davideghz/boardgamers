from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import SESSION_KEY
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import override
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, SuperUserFactory, UserFactory, UserProfileFactory
from webapp.models import FavoriteUser, LocationFollower, Player, UserProfile
from webapp.tests.test_telegram_miniapp_bootstrap import make_table


class AdminProfileMergeTests(TestCase):
    def setUp(self):
        self.enterContext(override('it'))
        self.keeper = UserProfileFactory(nickname='manuzana')
        self.keeper.user.set_password('keeper-password')
        self.keeper.user.save(update_fields=['password'])
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

    def test_imports_email_username_and_verification_without_copying_password(self):
        keeper_user, duplicate_user = self.keeper.user, self.duplicate.user
        keeper_user.email = ''
        keeper_user.save(update_fields=['email'])
        email = duplicate_user.email
        duplicate_user.username = email
        duplicate_user.set_password('duplicate-password')
        duplicate_user.save(update_fields=['username', 'password'])
        self.duplicate.is_email_verified = False
        self.duplicate.save(update_fields=['is_email_verified'])

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertRedirects(response, reverse('admin:webapp_userprofile_change', args=[self.keeper.pk]))
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.user.email, email)
        self.assertEqual(self.keeper.user.username, email)
        self.assertFalse(self.keeper.is_email_verified)
        self.assertFalse(self.keeper.user.check_password('duplicate-password'))
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': email, 'password': 'keeper-password'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.keeper.user_id))

    def test_keeps_existing_email_username_and_verification(self):
        self.keeper.is_email_verified = False
        self.keeper.save(update_fields=['is_email_verified'])
        original = self.keeper.user

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertRedirects(response, reverse('admin:webapp_userprofile_change', args=[self.keeper.pk]))
        self.keeper.refresh_from_db()
        self.assertEqual(self.keeper.user.email, original.email)
        self.assertEqual(self.keeper.user.username, original.username)
        self.assertFalse(self.keeper.is_email_verified)

    def test_social_only_keeper_can_set_first_password_after_merge(self):
        user = self.keeper.user
        user.email = ''
        user.set_unusable_password()
        user.save(update_fields=['email', 'password'])
        UserSocialAuth.objects.create(user=user, provider='telegram', uid='42')
        email = self.duplicate.user.email

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertRedirects(response, reverse('admin:webapp_userprofile_change', args=[self.keeper.pk]))
        user.refresh_from_db()
        self.assertEqual(user.email, email)
        self.assertFalse(user.has_usable_password())
        self.client.logout()
        self.client.post(reverse('custom_password_reset'), {'email': email})
        self.assertEqual(mail.outbox, [])

        self.client.force_login(user)
        password = 'new-keeper-password!'
        response = self.client.post(reverse('password_change'), {
            'new_password1': password, 'new_password2': password,
        })
        self.assertRedirects(response, reverse('password_change_done'), fetch_redirect_response=False)
        self.client.logout()
        response = self.client.post(reverse('login'), {'username': email, 'password': password})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.client.logout()
        response = self.client.post(reverse('custom_password_reset'), {'email': email})
        self.assertRedirects(response, reverse('password_reset_done'))
        self.assertEqual([message.to for message in mail.outbox], [[email]])

    def test_preview_warns_about_shared_provider_and_merge_keeps_one_login(self):
        kept = UserSocialAuth.objects.create(user=self.keeper.user, provider='telegram', uid='keeper-telegram')
        dropped = UserSocialAuth.objects.create(user=self.duplicate.user, provider='telegram', uid='duplicate-telegram')
        transferred = UserSocialAuth.objects.create(user=self.duplicate.user, provider='google-oauth2', uid='duplicate-google')
        preview = self.client.get(self.url, self.ids)
        for text in (
            'Unisci account', 'Password utilizzabile', 'Ultimo accesso', 'Tavoli creati',
            'Associazioni create', 'keeper-telegram', 'duplicate-telegram', 'duplicate-google',
            'Entrambi gli account hanno accessi con questi provider: telegram',
        ):
            self.assertContains(preview, text)

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertRedirects(response, reverse('admin:webapp_userprofile_change', args=[self.keeper.pk]))
        self.assertCountEqual(
            UserSocialAuth.objects.filter(user_id=self.keeper.user_id).values_list('pk', flat=True),
            [kept.pk, transferred.pk],
        )
        self.assertFalse(UserSocialAuth.objects.filter(pk=dropped.pk).exists())

    def test_preview_warns_about_importing_an_unverified_email(self):
        warning = f'L’email {self.duplicate.user.email} non è verificata'
        self.duplicate.is_email_verified = False
        self.duplicate.save(update_fields=['is_email_verified'])
        # Both accounts have an email: nothing is imported.
        self.assertNotContains(self.client.get(self.url, self.ids), warning)

        User.objects.filter(pk=self.keeper.user_id).update(email='')
        self.assertContains(self.client.get(self.url, self.ids), warning)

        self.duplicate.is_email_verified = True
        self.duplicate.save(update_fields=['is_email_verified'])
        self.assertNotContains(self.client.get(self.url, self.ids), warning)

    def test_missing_login_method_rolls_back_email_and_profile_transfer(self):
        user = self.keeper.user
        user.email = ''
        user.set_unusable_password()
        user.save(update_fields=['email', 'password'])
        self.duplicate.is_email_verified = False
        self.duplicate.save(update_fields=['is_email_verified'])
        self.duplicate.user.set_password('duplicate-password')
        self.duplicate.user.save(update_fields=['password'])

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertContains(response, 'deve avere un’email e almeno un metodo di accesso')
        self.keeper.refresh_from_db()
        self.location.refresh_from_db()
        self.assertEqual(self.keeper.user.email, '')
        self.assertTrue(self.keeper.is_email_verified)
        self.assertEqual(self.location.creator_id, self.duplicate.pk)
        self.assertTrue(User.objects.filter(pk=self.duplicate.user_id).exists())

    def test_missing_email_rolls_back_social_transfer(self):
        User.objects.filter(pk__in=[self.keeper.user_id, self.duplicate.user_id]).update(email='')
        social = UserSocialAuth.objects.create(user=self.duplicate.user, provider='telegram', uid='42')

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertContains(response, 'deve avere un’email e almeno un metodo di accesso')
        social.refresh_from_db()
        self.assertEqual(social.user_id, self.duplicate.user_id)

    def test_third_account_email_or_username_blocks_merge(self):
        User.objects.filter(pk=self.keeper.user_id).update(email='')
        User.objects.filter(pk=self.duplicate.user_id).update(username='duplicate-username')
        email = self.duplicate.user.email
        third = UserFactory(username='third-account', email=email.upper())

        for field in ('email', 'username'):
            with self.subTest(field=field):
                response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
                self.assertContains(response, 'è già in uso su un altro account')
                self.assertTrue(User.objects.filter(pk=self.duplicate.user_id).exists())
                self.assertTrue(User.objects.filter(pk=self.keeper.user_id, email='').exists())
            if field == 'email':
                third.email, third.username = '', email
                third.save(update_fields=['email', 'username'])

    def test_admin_log_entry_blocks_deletion_of_former_staff_account(self):
        entry = LogEntry.objects.create(user_id=self.duplicate.user_id, action_flag=CHANGE)

        response = self.client.post(self.url, {**self.ids, 'keep': self.keeper.pk})
        self.assertContains(response, 'Il duplicato ha ancora dati collegati')
        self.assertTrue(LogEntry.objects.filter(pk=entry.pk).exists())
        self.location.refresh_from_db()
        self.assertEqual(self.location.creator_id, self.duplicate.pk)
