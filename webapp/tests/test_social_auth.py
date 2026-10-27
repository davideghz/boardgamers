from unittest import mock

from django.test import RequestFactory, TestCase, override_settings
from django.contrib.sessions.middleware import SessionMiddleware
from social_django.models import UserSocialAuth
from social_django.utils import load_backend, load_strategy

from webapp.factories import UserProfileFactory
from webapp.pipeline import save_language_from_state


@override_settings(SOCIAL_AUTH_GOOGLE_OAUTH2_KEY='test-key', SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET='test-secret')
class GoogleLoginStartTest(TestCase):
    def test_get_is_rejected(self):
        response = self.client.get('/login/google-oauth2/?lang=en')
        self.assertEqual(response.status_code, 405)

    def test_post_redirects_to_google_and_keeps_language(self):
        response = self.client.post('/login/google-oauth2/?lang=en')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith('https://accounts.google.com/'))
        self.assertEqual(self.client.session['social_auth_language'], 'en')

    def test_login_page_renders_a_post_form(self):
        response = self.client.get('/accounts/login/')
        self.assertContains(response, 'action="/login/google-oauth2/?lang=it"')
        self.assertContains(response, 'method="post"')


class GoogleLegacyUidMigrationTest(TestCase):
    """Accounts created before social-auth-core 6 have uid = email; they must keep working."""

    def setUp(self):
        self.profile = UserProfileFactory()
        self.user = self.profile.user
        # What the 0020 backfill migration leaves for a pre-6.0 Google association
        self.social = UserSocialAuth.objects.create(
            user=self.user, provider='google-oauth2', uid='player@example.com', id_key='email',
            extra_data={'access_token': 'old', 'token_type': 'Bearer'},
        )

    def run_pipeline_until_social_user(self):
        request = RequestFactory().get('/complete/google-oauth2/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = mock.Mock(is_authenticated=False)
        strategy = load_strategy(request)
        backend = load_backend(strategy, 'google-oauth2', redirect_uri=None)
        response = {'sub': '1234567890', 'email': 'player@example.com', 'email_verified': True,
                    'given_name': 'Pat', 'family_name': 'Player'}
        from social_core.pipeline.social_auth import social_details, social_uid, social_user
        kwargs = {'backend': backend, 'strategy': strategy, 'response': response, 'details': {}}
        kwargs.update(social_details(**kwargs))
        kwargs.update(social_uid(**kwargs))
        return social_user(**kwargs)

    def test_existing_email_association_is_found_and_rekeyed_to_sub(self):
        result = self.run_pipeline_until_social_user()

        self.assertEqual(result['user'], self.user)
        self.assertFalse(result['is_new'])
        self.social.refresh_from_db()
        self.assertEqual((self.social.uid, self.social.id_key), ('1234567890', 'sub'))
        self.assertEqual(UserSocialAuth.objects.filter(provider='google-oauth2').count(), 1)


class SaveLanguageFromStateTest(TestCase):
    def test_language_from_session_is_saved_on_profile(self):
        profile = UserProfileFactory(preferred_language='it')
        request = RequestFactory().get('/complete/google-oauth2/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.session['social_auth_language'] = 'en'
        strategy = load_strategy(request)

        save_language_from_state(strategy, backend=None, user=profile.user, response={})

        profile.refresh_from_db()
        self.assertEqual(profile.preferred_language, 'en')
        self.assertNotIn('social_auth_language', request.session)
