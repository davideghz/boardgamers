from django.test import TestCase, override_settings
from django.urls import reverse
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, Location, Member, Membership, Player
from webapp.tests.test_telegram_miniapp import BOT_TOKEN, build_init_data
from webapp.tests.test_telegram_miniapp_bootstrap import make_table

TELEGRAM_ID = 42


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class TableActionEndpointTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.table = make_table(location=self.location, author=UserProfileFactory())
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='telegram', uid=str(TELEGRAM_ID))

    def post(self, name, table=None, init_data=None):
        url = reverse(name, kwargs={'slug': (table or self.table).slug})
        if init_data is None:
            init_data = build_init_data(
                telegram_id=TELEGRAM_ID, start_param=self.location.slug)
        return self.client.post(url, headers={'X-Telegram-Init-Data': init_data})

    def is_player(self, table=None):
        return Player.objects.filter(
            table=table or self.table, user_profile=self.profile).exists()

    # ── Happy path ────────────────────────────────────────────────────────

    def test_join_seats_the_player_and_returns_the_new_state(self):
        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.is_player())
        table = response.json()['table']
        self.assertTrue(table['is_joined'])
        self.assertEqual(table['players_count'], 1)
        self.assertEqual(table['players'], [self.profile.nickname])

    def test_leave_removes_the_player_and_returns_the_new_state(self):
        Player.objects.create(table=self.table, user_profile=self.profile)

        response = self.post('telegram-miniapp-leave')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.is_player())
        table = response.json()['table']
        self.assertFalse(table['is_joined'])
        self.assertEqual(table['players_count'], 0)

    def test_join_reports_no_warnings(self):
        """The only warning join_table can raise is the overlapping-event-table
        one, and event tables are unreachable here — so `warnings` is always
        empty for now. The field is kept so the contract survives phase 4."""
        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.json()['warnings'], [])

    # ── Authentication ────────────────────────────────────────────────────

    def test_forged_init_data_is_unauthorized(self):
        response = self.post(
            'telegram-miniapp-join', init_data=build_init_data(token='0:NOPE'))

        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.is_player())

    def test_unlinked_telegram_account_cannot_join(self):
        UserSocialAuth.objects.all().delete()

        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['error'], 'not_linked')
        self.assertFalse(self.is_player())

    def test_get_is_not_allowed(self):
        url = reverse('telegram-miniapp-join', kwargs={'slug': self.table.slug})

        response = self.client.get(url, headers={
            'X-Telegram-Init-Data': build_init_data(telegram_id=TELEGRAM_ID)})

        self.assertEqual(response.status_code, 405)

    # ── Refusals ──────────────────────────────────────────────────────────

    def test_joining_twice_is_a_conflict(self):
        Player.objects.create(table=self.table, user_profile=self.profile)

        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'already_joined')
        self.assertTrue(response.json()['detail'])

    def test_full_table_is_refused(self):
        self.table.max_players = 2
        self.table.external_players = 2
        self.table.save()

        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'table_full')
        self.assertFalse(self.is_player())

    def test_members_only_location_is_enforced(self):
        self.location.table_join_permission = Location.PERM_MEMBERS_ONLY
        self.location.save()

        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'members_only')

    def test_active_member_may_join_a_members_only_location(self):
        self.location.table_join_permission = Location.PERM_MEMBERS_ONLY
        self.location.save()
        member = Member.objects.create(
            location=self.location, user_profile=self.profile,
            first_name='A', last_name='B')
        Membership.objects.create(member=member, status=Membership.ACTIVE)

        response = self.post('telegram-miniapp-join')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.is_player())

    def test_leaving_a_table_you_are_not_at_is_a_conflict(self):
        response = self.post('telegram-miniapp-leave')

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'not_at_table')

    def test_closed_table_is_refused(self):
        past = make_table(location=self.location, author=self.profile, days_ahead=-5)

        response = self.post('telegram-miniapp-join', table=past)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'table_closed')

    # ── Reachability ──────────────────────────────────────────────────────

    def test_event_tables_are_unreachable(self):
        """They are never listed here and have their own sign-up flow on the
        website; a crafted request must not be able to book one."""
        event = Event.objects.create(name='Con')
        event_table = make_table(author=self.profile, event=event)

        response = self.post('telegram-miniapp-join', table=event_table)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.is_player(event_table))

    def test_unknown_slug_is_reported_as_json(self):
        url = reverse('telegram-miniapp-join', kwargs={'slug': 'does-not-exist'})

        response = self.client.post(url, headers={
            'X-Telegram-Init-Data': build_init_data(telegram_id=TELEGRAM_ID)})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error'], 'unknown_table')
