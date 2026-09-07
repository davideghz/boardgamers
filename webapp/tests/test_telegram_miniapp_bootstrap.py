import datetime

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, Player, Table
from webapp.tests.test_telegram_miniapp import BOT_TOKEN, build_init_data


def make_table(location=None, author=None, days_ahead=7, **kwargs):
    return Table.objects.create(
        title=kwargs.pop('title', 'Serata giochi'),
        location=location,
        author=author,
        date=timezone.localdate() + datetime.timedelta(days=days_ahead),
        time=kwargs.pop('time', datetime.time(20, 30)),
        **kwargs,
    )


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class BootstrapTest(TestCase):
    def setUp(self):
        self.url = reverse('telegram-miniapp-bootstrap')
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())

    def get(self, init_data, **extra):
        headers = {'X-Telegram-Init-Data': init_data} if init_data is not None else {}
        return self.client.get(self.url, headers=headers, **extra)

    def link_telegram(self, profile, telegram_id):
        UserSocialAuth.objects.create(
            user=profile.user, provider='telegram', uid=str(telegram_id))

    # ── Authentication ────────────────────────────────────────────────────

    def test_without_init_data_is_unauthorized(self):
        response = self.get(None)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error'], 'invalid_init_data')

    def test_forged_init_data_is_unauthorized(self):
        forged = build_init_data(token='000000:NOT-THE-BOT')

        self.assertEqual(self.get(forged).status_code, 401)

    def test_session_login_alone_grants_nothing(self):
        """The endpoint must not fall back to the Django session."""
        self.client.force_login(self.profile.user)

        self.assertEqual(self.get(None).status_code, 401)

    # ── Location resolution ───────────────────────────────────────────────

    def test_link_without_start_param_is_rejected(self):
        response = self.get(build_init_data())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'no_location')

    def test_unknown_location_is_reported(self):
        response = self.get(build_init_data(start_param='nope'))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error'], 'unknown_location')

    # ── Payload ───────────────────────────────────────────────────────────

    def test_unlinked_user_gets_the_read_only_payload(self):
        make_table(location=self.location, author=self.profile)

        body = self.get(build_init_data(start_param=self.location.slug)).json()

        self.assertFalse(body['linked'])
        self.assertIsNone(body['profile'])
        self.assertEqual(body['telegram_user']['first_name'], 'Dave')
        self.assertEqual(body['location']['name'], self.location.name)
        self.assertTrue(body['location']['web_url'].endswith(
            f"/locations/{self.location.slug}/"))
        self.assertEqual(len(body['tables']), 1)

    def test_linked_user_is_recognised(self):
        self.link_telegram(self.profile, 42)

        body = self.get(
            build_init_data(telegram_id=42, start_param=self.location.slug)).json()

        self.assertTrue(body['linked'])
        self.assertEqual(body['profile']['nickname'], self.profile.nickname)

    def test_is_joined_flags_the_viewers_own_tables(self):
        self.link_telegram(self.profile, 42)
        mine = make_table(location=self.location, author=self.profile, title='Mio')
        make_table(location=self.location, author=self.profile, title='Altro')
        Player.objects.create(table=mine, user_profile=self.profile)

        body = self.get(
            build_init_data(telegram_id=42, start_param=self.location.slug)).json()

        joined = {t['title']: t['is_joined'] for t in body['tables']}
        self.assertEqual(joined, {'Mio': True, 'Altro': False})

    # ── Which tables are listed ───────────────────────────────────────────

    def test_only_upcoming_tables_of_that_location(self):
        other_location = LocationFactory(creator=UserProfileFactory())
        make_table(location=self.location, author=self.profile, title='Futuro')
        make_table(location=self.location, author=self.profile, title='Passato',
                   days_ahead=-5)
        make_table(location=other_location, author=self.profile, title='Altrove')

        body = self.get(build_init_data(start_param=self.location.slug)).json()

        self.assertEqual([t['title'] for t in body['tables']], ['Futuro'])

    def test_event_tables_are_not_listed(self):
        event = Event.objects.create(name='Con')
        make_table(author=self.profile, event=event, title='Tavolo evento')
        make_table(location=self.location, author=self.profile, title='Tavolo location')

        body = self.get(build_init_data(start_param=self.location.slug)).json()

        self.assertEqual([t['title'] for t in body['tables']], ['Tavolo location'])

    def test_tables_are_ordered_by_date_then_time(self):
        make_table(location=self.location, author=self.profile,
                   title='C', days_ahead=9)
        make_table(location=self.location, author=self.profile,
                   title='A', days_ahead=3, time=datetime.time(15, 0))
        make_table(location=self.location, author=self.profile,
                   title='B', days_ahead=3, time=datetime.time(21, 0))

        body = self.get(build_init_data(start_param=self.location.slug)).json()

        self.assertEqual([t['title'] for t in body['tables']], ['A', 'B', 'C'])

    def test_seat_counts_include_guests_and_external_players(self):
        table = make_table(location=self.location, author=self.profile,
                           max_players=5, external_players=2)
        Player.objects.create(table=table, user_profile=self.profile)

        body = self.get(build_init_data(start_param=self.location.slug)).json()
        listed = body['tables'][0]

        self.assertEqual(listed['players_count'], 3)
        self.assertEqual(listed['seats_available'], 2)
        self.assertEqual(listed['players'], [self.profile.nickname])

    def test_unlimited_table_never_reports_zero_seats(self):
        make_table(location=self.location, author=self.profile,
                   max_players=1, external_players=8, unlimited_seats=True)

        body = self.get(build_init_data(start_param=self.location.slug)).json()

        self.assertTrue(body['tables'][0]['unlimited_seats'])
        self.assertEqual(body['tables'][0]['seats_available'], 0)


class MiniAppShellTest(TestCase):
    def test_shell_is_framable_by_telegram_web(self):
        """Telegram Web renders Mini Apps in an iframe; the project default of
        X-Frame-Options DENY would blank the page."""
        response = self.client.get(reverse('telegram-miniapp'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('X-Frame-Options', response.headers)

    def test_language_cookie_does_not_redirect_the_shell(self):
        """Telegram delivers initData in the URL fragment; a language redirect
        would put that at risk for no benefit, since the Mini App takes its
        language from initData rather than from a website cookie."""
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = 'en'

        response = self.client.get(reverse('telegram-miniapp'))

        self.assertEqual(response.status_code, 200)

    def test_shell_needs_no_login(self):
        response = self.client.get(reverse('telegram-miniapp'))

        self.assertTemplateUsed(response, 'telegram/miniapp.html')
