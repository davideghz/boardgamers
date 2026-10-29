import json

from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import PushSubscription


class PushSubscribeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.client.force_login(self.user_profile.user)
        self.url = reverse('push-subscribe')

    def subscribe(self, auth='auth-1'):
        body = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'key', 'auth': auth}}
        return self.client.post(self.url, json.dumps(body), content_type='application/json')

    def test_resubscribing_updates_the_existing_row(self):
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertEqual(self.subscribe(auth='auth-2').status_code, 200)
        sub = PushSubscription.objects.get(user_profile=self.user_profile)
        self.assertEqual(sub.auth, 'auth-2')

    def test_same_endpoint_cannot_be_stored_twice_for_a_user(self):
        self.subscribe()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PushSubscription.objects.create(
                user_profile=self.user_profile, endpoint='https://push.example/abc',
                p256dh='key', auth='auth-1')
