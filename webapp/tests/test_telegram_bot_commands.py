import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import TelegramGroupConfig
from webapp.services.telegram import miniapp_link
from webapp.tests.test_telegram_miniapp_bootstrap import make_table

CHAT_ID = -100123

BOT = dict(TELEGRAM_BOT_USERNAME='board_gamers_bot',
           TELEGRAM_MINIAPP_SHORT_NAME='join',
           TELEGRAM_WEBHOOK_SECRET='')


@override_settings(**BOT)
class MiniAppLinkTest(TestCase):
    def test_link_carries_the_location_in_startapp(self):
        location = LocationFactory(creator=UserProfileFactory())

        self.assertEqual(
            miniapp_link(location),
            f"https://t.me/board_gamers_bot/join?startapp={location.slug}")

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_link_is_empty_when_the_bot_is_not_configured(self):
        location = LocationFactory(creator=UserProfileFactory())

        self.assertEqual(miniapp_link(location), '')


@override_settings(**BOT)
class BotCommandTest(TestCase):
    def setUp(self):
        self.location = LocationFactory(creator=UserProfileFactory())
        self.config = TelegramGroupConfig.objects.create(
            location=self.location, chat_id=CHAT_ID, chat_title='Gruppo')

    def send(self, text, chat_id=CHAT_ID):
        """Post a Telegram update to the webhook, capturing what the bot replies."""
        payload = {'message': {'chat': {'id': chat_id, 'title': 'Gruppo'},
                               'text': text}}
        with patch('webapp.api.telegram_views.send_message') as send:
            response = self.client.post(
                reverse('telegram-webhook'),
                data=json.dumps(payload),
                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return send

    def buttons(self, send):
        markup = send.call_args.kwargs.get('reply_markup') or {}
        return [b for row in markup.get('inline_keyboard', []) for b in row]

    # ── /join ─────────────────────────────────────────────────────────────

    def test_join_posts_a_button_to_this_locations_mini_app(self):
        send = self.send('/join')

        buttons = self.buttons(send)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0]['url'], miniapp_link(self.location))
        self.assertIn(self.location.name, send.call_args.args[1])

    def test_join_strips_the_bot_suffix_telegram_adds_in_groups(self):
        send = self.send('/join@board_gamers_bot')

        self.assertEqual(self.buttons(send)[0]['url'], miniapp_link(self.location))

    def test_join_in_an_unconfigured_group_explains_itself(self):
        send = self.send('/join', chat_id=-999)

        self.assertEqual(self.buttons(send), [])
        self.assertIn('non è ancora configurato', send.call_args.args[1])

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_join_without_a_configured_mini_app_says_so(self):
        send = self.send('/join')

        self.assertEqual(self.buttons(send), [])
        self.assertIn('Mini App non è configurata', send.call_args.args[1])

    # ── /tables ───────────────────────────────────────────────────────────

    def test_tables_leads_with_the_mini_app_button(self):
        make_table(location=self.location, author=UserProfileFactory())

        send = self.send('/tables')

        buttons = self.buttons(send)
        self.assertEqual(buttons[0]['url'], miniapp_link(self.location))

    def test_tables_without_tables_still_offers_the_mini_app(self):
        send = self.send('/tables')

        self.assertIn('Nessun tavolo aperto', send.call_args.args[1])
        self.assertEqual(self.buttons(send)[0]['url'], miniapp_link(self.location))

    def test_tables_offers_creating_one(self):
        make_table(location=self.location, author=UserProfileFactory())

        send = self.send('/tables')

        labels = [b['text'] for b in self.buttons(send)]
        self.assertIn('➕ Crea un tavolo', labels)

    def test_empty_listing_offers_creating_one(self):
        send = self.send('/tables')

        labels = [b['text'] for b in self.buttons(send)]
        self.assertIn('➕ Crea un tavolo', labels)

    def test_inactive_config_is_ignored(self):
        self.config.active = False
        self.config.save()

        send = self.send('/join')

        self.assertIn('non è ancora configurato', send.call_args.args[1])

    # ── Dispatch ──────────────────────────────────────────────────────────

    def test_unknown_command_is_ignored(self):
        send = self.send('/somethingelse')

        send.assert_not_called()

    def test_plain_chatter_is_ignored(self):
        send = self.send('ci vediamo giovedì')

        send.assert_not_called()


@override_settings(**BOT)
class ManagePageLinkTest(TestCase):
    """The link is only useful if a manager can find and copy it."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)

    def test_manager_sees_the_booking_link(self):
        self.client.force_login(self.owner.user)

        response = self.client.get(
            reverse('location-manage-telegram', kwargs={'slug': self.location.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, miniapp_link(self.location))

    @override_settings(TELEGRAM_BOT_USERNAME='')
    def test_link_section_is_hidden_when_the_bot_is_not_configured(self):
        self.client.force_login(self.owner.user)

        response = self.client.get(
            reverse('location-manage-telegram', kwargs={'slug': self.location.slug}))

        self.assertNotContains(response, 'startapp=')
