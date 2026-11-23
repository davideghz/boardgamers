from unittest.mock import Mock, patch

import requests
from django.test import SimpleTestCase, override_settings
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError

from boardGames.sentry import scrub_secret
from webapp.services.telegram import send_message
from webapp.tests.test_telegram_miniapp import BOT_TOKEN

URL = f'/bot{BOT_TOKEN}/sendMessage'


def unreachable():
    reason = NewConnectionError(None, '[Errno 101] Network is unreachable')
    return requests.ConnectionError(MaxRetryError(None, URL, reason))


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
@patch('webapp.services.telegram.time.sleep')
@patch('webapp.services.telegram.requests.post')
class SendMessageTest(SimpleTestCase):
    def test_retries_when_the_connection_was_never_opened(self, post, sleep):
        post.side_effect = [unreachable(), Mock(ok=True, text='ok')]

        with self.assertNoLogs('webapp.services.telegram', 'WARNING'):
            send_message(1, 'ciao')

        self.assertEqual(post.call_count, 2)

    def test_gives_up_after_one_retry_without_logging_the_token(self, post, sleep):
        post.side_effect = unreachable()

        with self.assertLogs('webapp.services.telegram', 'ERROR') as logs:
            send_message(1, 'ciao')

        self.assertEqual(post.call_count, 2)
        self.assertNotIn(BOT_TOKEN, logs.output[0])
        self.assertIn('Network is unreachable', logs.output[0])

    def test_does_not_retry_when_the_message_may_have_been_sent(self, post, sleep):
        for error in (requests.ReadTimeout(f'timeout {URL}'),
                      requests.ConnectionError(ProtocolError('Connection aborted.'))):
            with self.subTest(error=error):
                post.reset_mock()
                post.side_effect = error

                with self.assertLogs('webapp.services.telegram', 'ERROR') as logs:
                    send_message(1, 'ciao')

                self.assertEqual(post.call_count, 1)
                self.assertNotIn(BOT_TOKEN, logs.output[0])


class ScrubSecretTest(SimpleTestCase):
    def test_masks_the_secret_anywhere_in_the_event(self):
        event = {
            'logentry': {'message': f'failed {URL}', 'params': (URL, 3)},
            'breadcrumbs': {'values': [{'data': {'url': URL}}]},
            'level': 'error',
        }

        scrubbed = scrub_secret(event, BOT_TOKEN)

        self.assertNotIn(BOT_TOKEN, str(scrubbed))
        self.assertEqual(scrubbed['logentry']['params'], ('/bot[Filtered]/sendMessage', 3))
        self.assertEqual(scrubbed['level'], 'error')

    def test_leaves_the_event_alone_without_a_secret(self):
        self.assertEqual(scrub_secret({'a': 'b'}, ''), {'a': 'b'})
