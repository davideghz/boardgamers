"""SES does not escape template data: user-provided values must be escaped for
the HTML part and sent unchanged, under a *_text key, for the subject and text part."""

import datetime
import io
import json
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Notification, NotificationType, Table

TITLE = '<b>Dungeons</b> & Dragons'
ESCAPED_TITLE = '&lt;b&gt;Dungeons&lt;/b&gt; &amp; Dragons'


@override_settings(AWS_SES_REGION_NAME='eu', AWS_SES_ACCESS_KEY_ID='key', AWS_SES_SECRET_ACCESS_KEY='secret')
class SesEmailEscapingTest(TestCase):
    def setUp(self):
        self.table = Table.objects.create(
            title=TITLE, description='Prima riga\n<i>seconda</i>', author=UserProfileFactory(nickname='Marco'),
            location=LocationFactory(name='Bar <Joker>'), game=GameFactory(name='Risk & Co'),
            date=datetime.date(2026, 11, 20), time=datetime.time(20, 30),
        )
        self.recipient = UserProfileFactory()

    def send(self, notification_type, message=''):
        Notification.objects.create(
            recipient=self.recipient, table=self.table, location=self.table.location,
            notification_type=notification_type, message=message,
        )
        client = mock.Mock()
        client.send_bulk_email.return_value = {'BulkEmailEntryResults': []}
        with mock.patch('webapp.management.commands.send_queued_notifications.boto3.client', return_value=client):
            call_command('send_queued_notifications', stdout=io.StringIO())
        entry = client.send_bulk_email.call_args.kwargs['BulkEmailEntries'][0]
        return json.loads(entry['ReplacementEmailContent']['ReplacementTemplate']['ReplacementTemplateData'])

    def test_new_table(self):
        data = self.send(NotificationType.NEW_TABLE)
        self.assertEqual(data['title'], ESCAPED_TITLE)
        self.assertEqual(data['title_text'], TITLE)
        self.assertEqual(data['game'], 'Risk &amp; Co')
        self.assertEqual(data['game_text'], 'Risk & Co')
        self.assertEqual(data['location_name'], 'Bar &lt;Joker&gt;')
        self.assertEqual(data['location_name_text'], 'Bar <Joker>')
        self.assertEqual(data['creator_name_text'], 'Marco')
        self.assertEqual(data['description'], 'Prima riga<br>&lt;i&gt;seconda&lt;/i&gt;')
        self.assertEqual(data['description_text'], 'Prima riga\n<i>seconda</i>')

    def test_tables_added(self):
        data = self.send(NotificationType.TABLES_ADDED, message='20/11/2026, 27/11/2026')
        self.assertEqual(data['title'], ESCAPED_TITLE)
        self.assertEqual(data['title_text'], TITLE)
        self.assertEqual(data['game'], 'Risk &amp; Co')
        self.assertEqual(data['location_name_text'], 'Bar <Joker>')
        self.assertEqual(data['organizer_name_text'], 'Marco')
        self.assertIn('name_text', data)
