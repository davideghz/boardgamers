import hashlib
import hmac
import json
from datetime import timedelta
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.utils import timezone
from social_django.models import UserSocialAuth

from webapp.factories import UserProfileFactory
from webapp.services.telegram import (
    INIT_DATA_MAX_AGE,
    profile_from_init_data,
    validate_init_data,
)

BOT_TOKEN = '123456:TEST-BOT-TOKEN'
OTHER_BOT_TOKEN = '999999:ANOTHER-BOT-TOKEN'


def build_init_data(token=BOT_TOKEN, telegram_id=42, auth_date=None, **extra):
    """Sign an initData payload the way Telegram does, for use in tests.

    `auth_date` accepts a datetime or a raw string (to exercise malformed input).
    """
    if auth_date is None:
        auth_date = timezone.now()
    if not isinstance(auth_date, str):
        auth_date = str(int(auth_date.timestamp()))

    fields = {
        'user': json.dumps({'id': telegram_id, 'first_name': 'Dave', 'language_code': 'it'}),
        'auth_date': auth_date,
        'query_id': 'AAF_test',
    }
    fields.update(extra)

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields['hash'] = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    return urlencode(fields)


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class ValidateInitDataTest(TestCase):
    def test_valid_signature_returns_payload(self):
        data = validate_init_data(build_init_data())

        self.assertIsNotNone(data)
        self.assertEqual(data['user']['id'], 42)
        self.assertEqual(data['user']['first_name'], 'Dave')
        # `hash` must not leak into the payload handed to callers
        self.assertNotIn('hash', data)

    def test_tampered_field_is_rejected(self):
        raw = build_init_data(telegram_id=42)
        forged = raw.replace('Dave', 'Mall')

        self.assertNotEqual(raw, forged)
        self.assertIsNone(validate_init_data(forged))

    def test_signature_from_another_bot_is_rejected(self):
        self.assertIsNone(validate_init_data(build_init_data(token=OTHER_BOT_TOKEN)))

    def test_missing_hash_is_rejected(self):
        raw = urlencode({'user': json.dumps({'id': 42}), 'auth_date': '1700000000'})

        self.assertIsNone(validate_init_data(raw))

    def test_expired_auth_date_is_rejected(self):
        stale = timezone.now() - INIT_DATA_MAX_AGE - timedelta(minutes=1)

        self.assertIsNone(validate_init_data(build_init_data(auth_date=stale)))

    def test_auth_date_inside_the_window_is_accepted(self):
        recent = timezone.now() - INIT_DATA_MAX_AGE + timedelta(minutes=1)

        self.assertIsNotNone(validate_init_data(build_init_data(auth_date=recent)))

    def test_non_numeric_auth_date_is_rejected(self):
        self.assertIsNone(validate_init_data(build_init_data(auth_date='yesterday')))

    def test_malformed_user_json_is_rejected(self):
        self.assertIsNone(validate_init_data(build_init_data(user='not-json')))

    def test_empty_input_is_rejected(self):
        self.assertIsNone(validate_init_data(''))
        self.assertIsNone(validate_init_data(None))

    @override_settings(TELEGRAM_BOT_TOKEN='')
    def test_without_bot_token_nothing_validates(self):
        self.assertIsNone(validate_init_data(build_init_data()))


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class ProfileFromInitDataTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()

    def link_telegram(self, telegram_id):
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='telegram', uid=str(telegram_id)
        )

    def test_linked_account_resolves_to_profile(self):
        self.link_telegram(42)
        data = validate_init_data(build_init_data(telegram_id=42))

        self.assertEqual(profile_from_init_data(data), self.profile)

    def test_unlinked_telegram_user_returns_none(self):
        data = validate_init_data(build_init_data(telegram_id=42))

        self.assertIsNone(profile_from_init_data(data))

    def test_another_providers_uid_is_not_matched(self):
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='google-oauth2', uid='42'
        )
        data = validate_init_data(build_init_data(telegram_id=42))

        self.assertIsNone(profile_from_init_data(data))

    def test_payload_without_user_returns_none(self):
        self.assertIsNone(profile_from_init_data({'auth_date': '1700000000'}))
        self.assertIsNone(profile_from_init_data(None))
