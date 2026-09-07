from django.test import TestCase, override_settings
from django.urls import reverse
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.services.telegram import miniapp_language
from webapp.tests.test_telegram_miniapp import BOT_TOKEN, build_init_data
from webapp.tests.test_telegram_miniapp_bootstrap import make_table

TELEGRAM_ID = 42


class MiniAppLanguageTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()

    def test_a_linked_accounts_own_preference_wins(self):
        self.profile.preferred_language = 'en'
        self.profile.save(update_fields=['preferred_language'])

        self.assertEqual(
            miniapp_language(self.profile, {'language_code': 'it'}), 'en')

    def test_falls_back_to_the_telegram_client_language(self):
        self.assertEqual(miniapp_language(None, {'language_code': 'it'}), 'it')

    def test_regional_tags_are_reduced_to_the_base_language(self):
        self.assertEqual(miniapp_language(None, {'language_code': 'en-GB'}), 'en')

    def test_unsupported_languages_defer_to_django(self):
        self.assertIsNone(miniapp_language(None, {'language_code': 'de'}))
        self.assertIsNone(miniapp_language(None, {}))
        self.assertIsNone(miniapp_language(None, None))


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class BootstrapLanguageTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        make_table(location=self.location, author=self.profile)
        self.url = reverse('telegram-miniapp-bootstrap')

    def bootstrap(self, language_code='it'):
        return self.client.get(self.url, headers={
            'X-Telegram-Init-Data': build_init_data(
                telegram_id=TELEGRAM_ID,
                start_param=self.location.slug,
                user='{"id": %d, "first_name": "Dave", "language_code": "%s"}'
                     % (TELEGRAM_ID, language_code),
            )}).json()

    def test_an_italian_client_gets_italian_labels(self):
        body = self.bootstrap('it')

        self.assertEqual(body['strings']['join'], 'Partecipa')
        self.assertEqual(body['strings']['leave'], 'Esci')
        self.assertEqual(body['strings']['no_seats'], 'Completo')

    def test_an_english_client_gets_english_labels(self):
        body = self.bootstrap('en')

        self.assertEqual(body['strings']['join'], 'Join')
        self.assertEqual(body['strings']['leave'], 'Leave')

    def test_day_labels_follow_the_same_language(self):
        italian = self.bootstrap('it')['tables'][0]['day_label']
        english = self.bootstrap('en')['tables'][0]['day_label']

        self.assertNotEqual(italian, english)
        self.assertRegex(italian, r'(?i)(lun|mar|mer|gio|ven|sab|dom)')

    def test_a_linked_profile_overrides_the_client_language(self):
        self.profile.preferred_language = 'en'
        self.profile.save(update_fields=['preferred_language'])
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='telegram', uid=str(TELEGRAM_ID))

        body = self.bootstrap('it')

        self.assertTrue(body['linked'])
        self.assertEqual(body['strings']['join'], 'Join')

    def test_refusal_messages_are_translated_too(self):
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='telegram', uid=str(TELEGRAM_ID))
        table = make_table(location=self.location, author=self.profile,
                           max_players=2, external_players=2)

        response = self.client.post(
            reverse('telegram-miniapp-join', kwargs={'slug': table.slug}),
            headers={'X-Telegram-Init-Data': build_init_data(
                telegram_id=TELEGRAM_ID, start_param=self.location.slug)})

        self.assertEqual(response.json()['error'], 'table_full')
        self.assertEqual(response.json()['detail'], 'Tavolo completo')
