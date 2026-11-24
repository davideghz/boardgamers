import re
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.test import RequestFactory, TestCase
from django.urls import reverse
from social_django.models import UserSocialAuth
from social_django.utils import load_backend, load_strategy

from webapp.factories import UserProfileFactory
from webapp.forms import UserRegistrationForm
from webapp.pipeline import associate_by_email, copy_email_from_google_if_missing
from webapp.models import PushSubscription
from webapp.services.email_change import read_token

PASSWORD = 'xK9#mQ2$vL7pZw'


class ChangeEmailTest(TestCase):
    def setUp(self):
        self.profile = self._profile('mario@example.com')
        self.user = self.profile.user
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')
        mail.outbox.clear()

    def _profile(self, email):
        user = User.objects.create_user(username=email, email=email, password=PASSWORD)
        return UserProfileFactory(user=user, nickname=email.split('@')[0])

    def _change(self, new_email):
        return self.client.post(reverse('change-email'), {'new_email': new_email, 'password': PASSWORD})

    def _link(self):
        return re.search(r'https?://[^/\s]+(/\S+)', mail.outbox[0].body).group(1)

    def test_email_is_unchanged_until_the_new_address_confirms(self):
        self._change('new@example.com')

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'mario@example.com')
        self.assertEqual([m.to for m in mail.outbox], [['new@example.com']])

    def test_link_changes_email_and_username(self):
        self._change('new@example.com')
        self.client.get(self._link())

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new@example.com')
        self.assertEqual(self.user.username, 'new@example.com')

    def test_link_verifies_an_unverified_profile(self):
        self.profile.is_email_verified = False
        self.profile.save(update_fields=['is_email_verified'])
        self._change('new@example.com')
        self.client.get(self._link())

        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_email_verified)

    def test_link_is_useless_to_anyone_else(self):
        self._change('new@example.com')
        link = self._link()

        self.client.logout()
        self.assertIn(reverse('login'), self.client.get(link)['Location'])
        other = self._profile('other@example.com')
        self.client.force_login(other.user, backend='django.contrib.auth.backends.ModelBackend')
        self.client.get(link)

        for user, email in ((self.user, 'mario@example.com'), (other.user, 'other@example.com')):
            user.refresh_from_db()
            self.assertEqual(user.email, email)

    def test_link_is_rejected_when_tampered_expired_or_superseded(self):
        self._change('new@example.com')
        link = self._link()
        self.client.get(link.rstrip('/') + 'x/')
        with mock.patch('django.core.signing.time.time', return_value=4102444800):
            # The session would expire too: check the token directly.
            self.assertIsNone(read_token(self.user, link.rstrip('/').rsplit('/', 1)[-1]))
        User.objects.filter(pk=self.user.pk).update(email='third@example.com')
        self.client.get(link)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'third@example.com')

    def test_link_is_rejected_when_the_address_was_taken_meanwhile(self):
        self._change('new@example.com')
        self._profile('NEW@example.com')
        self.client.get(self._link())

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'mario@example.com')

    def test_rejects_invalid_or_taken_addresses(self):
        self._profile('taken@example.com')
        for email in ('', 'nope', 'TAKEN@example.com', 'a@b.com\nBcc: c@d.com', 'mario@example.com'):
            with self.subTest(email=email):
                mail.outbox.clear()
                self._change(email)
                self.assertEqual(mail.outbox, [])

    def test_wrong_password_sends_nothing(self):
        self.client.post(reverse('change-email'), {'new_email': 'new@example.com', 'password': 'wrong'})
        self.assertEqual(mail.outbox, [])


class AssociateByEmailTest(TestCase):
    """An unverified account never proved it owns its email: the Google user did."""

    def setUp(self):
        user = User.objects.create_user('victim@example.com', 'victim@example.com', PASSWORD)
        self.profile = UserProfileFactory(user=user, nickname='victim', is_email_verified=False)
        self.user = user

    def _associate(self, email='Victim@example.com'):
        request = RequestFactory().get('/')
        SessionMiddleware(lambda r: None).process_request(request)
        strategy = load_strategy(request)
        backend = load_backend(strategy, 'google-oauth2', redirect_uri=None)
        return associate_by_email(backend=backend, details={'email': email}, user=None)

    def test_unverified_account_loses_every_previous_access(self):
        UserSocialAuth.objects.create(user=self.user, provider='telegram', uid='666')
        PushSubscription.objects.create(
            user_profile=self.profile, endpoint='https://push.example.com/1', p256dh='k', auth='a')
        self.client.force_login(self.user, backend='django.contrib.auth.backends.ModelBackend')

        result = self._associate()

        self.assertEqual(result['user'], self.user)
        self.user.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertFalse(self.user.has_usable_password())
        self.assertTrue(self.profile.is_email_verified)
        self.assertFalse(self.user.social_auth.exists())
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual(self.client.get(reverse('user-profile-edit')).status_code, 302)

    def test_verified_account_keeps_its_password(self):
        self.profile.is_email_verified = True
        self.profile.save(update_fields=['is_email_verified'])

        self.assertEqual(self._associate()['user'], self.user)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_unknown_email_and_logged_in_user_are_left_alone(self):
        self.assertIsNone(self._associate('nobody@example.com'))
        self.assertIsNone(associate_by_email(
            backend=None, details={'email': 'victim@example.com'}, user=self.user))

    def test_google_email_taken_with_another_case_is_not_copied(self):
        profile = UserProfileFactory(nickname='tg', user=User.objects.create_user('tg_user'))
        copy_email_from_google_if_missing(
            mock.Mock(), profile.user, {'email': 'VICTIM@example.com'})
        backend = mock.Mock()
        backend.name = 'google-oauth2'
        copy_email_from_google_if_missing(backend, profile.user, {'email': 'VICTIM@example.com'})

        profile.user.refresh_from_db()
        self.assertEqual(profile.user.email, '')


class SignupEmailCaseTest(TestCase):
    def test_rejects_registered_email_with_another_case(self):
        User.objects.create_user('mario@example.com', 'mario@example.com')
        form = UserRegistrationForm({'email': 'MARIO@example.com'})
        self.assertIn('email', form.errors)
