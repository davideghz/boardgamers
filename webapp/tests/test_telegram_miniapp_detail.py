from django.test import TestCase, override_settings
from django.urls import reverse
from social_django.models import UserSocialAuth

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Event, GuestProfile, Player, TableLink
from webapp.services.tables import add_guest, join_table
from webapp.tests.test_telegram_miniapp import BOT_TOKEN, build_init_data
from webapp.tests.test_telegram_miniapp_bootstrap import make_table

TELEGRAM_ID = 42


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class MiniAppDetailTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.author = UserProfileFactory()
        self.table = make_table(location=self.location, author=self.author)
        UserSocialAuth.objects.create(
            user=self.profile.user, provider='telegram', uid=str(TELEGRAM_ID))

    def init_data(self, linked=True):
        return build_init_data(
            telegram_id=TELEGRAM_ID if linked else 999,
            start_param=self.location.slug)

    def detail(self, table=None, linked=True):
        url = reverse('telegram-miniapp-detail',
                      kwargs={'slug': (table or self.table).slug})
        return self.client.get(
            url, headers={'X-Telegram-Init-Data': self.init_data(linked)})

    def add_guest_request(self, guest_id, table=None):
        url = reverse('telegram-miniapp-guest-add',
                      kwargs={'slug': (table or self.table).slug})
        return self.client.post(
            url, data={'guest_id': guest_id}, content_type='application/json',
            headers={'X-Telegram-Init-Data': self.init_data()})

    def remove_guest_request(self, player_id, table=None):
        url = reverse('telegram-miniapp-guest-remove',
                      kwargs={'slug': (table or self.table).slug,
                              'player_id': player_id})
        return self.client.post(
            url, headers={'X-Telegram-Init-Data': self.init_data()})

    # ── Detail payload ────────────────────────────────────────────────────

    def test_detail_carries_what_the_screen_needs(self):
        self.table.game = GameFactory()
        self.table.description = 'Portate **snack**'
        self.table.save()
        TableLink.objects.create(table=self.table, label='Regolamento',
                                 url='https://example.com/rules.pdf')
        join_table(self.profile, self.table)

        body = self.detail().json()['table']

        self.assertEqual(body['slug'], self.table.slug)
        self.assertEqual(body['game'], self.table.game.name)
        self.assertTrue(body['is_joined'])
        self.assertEqual(body['time_label'], '20:30')
        self.assertEqual(body['end_time_label'], '22:30')
        self.assertEqual(body['links'],
                         [{'label': 'Regolamento', 'url': 'https://example.com/rules.pdf'}])
        self.assertIn('<strong>snack</strong>', body['description_html'])

    def test_description_is_sanitised(self):
        self.table.description = 'ciao <script>alert(1)</script> **grassetto**'
        self.table.save()

        body = self.detail().json()['table']

        self.assertNotIn('<script>', body['description_html'])
        self.assertIn('<strong>grassetto</strong>', body['description_html'])

    def test_link_without_label_falls_back_to_the_host(self):
        TableLink.objects.create(table=self.table, url='https://boardgamegeek.com/x')

        body = self.detail().json()['table']

        self.assertEqual(body['links'][0]['label'], 'boardgamegeek.com')

    def test_unlinked_viewer_gets_no_guest_options(self):
        body = self.detail(linked=False).json()['table']

        self.assertFalse(body['is_joined'])
        self.assertEqual(body['guests'], [])

    def test_event_tables_are_unreachable(self):
        event = Event.objects.create(name='Con')
        event_table = make_table(author=self.profile, event=event)

        self.assertEqual(self.detail(table=event_table).status_code, 404)

    # ── Guest options ─────────────────────────────────────────────────────

    def test_guests_offered_only_once_seated(self):
        GuestProfile.objects.create(owner=self.profile, name='Ospite')

        self.assertEqual(self.detail().json()['table']['guests'], [])

        join_table(self.profile, self.table)
        guests = self.detail().json()['table']['guests']

        self.assertEqual([g['name'] for g in guests], ['Ospite'])

    def test_guests_already_seated_are_not_offered_again(self):
        guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')
        join_table(self.profile, self.table)
        add_guest(self.profile, self.table, guest)

        self.assertEqual(self.detail().json()['table']['guests'], [])

    def test_can_remove_marks_only_actionable_rows(self):
        other = UserProfileFactory()
        join_table(other, self.table)
        their_guest = GuestProfile.objects.create(owner=other, name='Loro')
        add_guest(other, self.table, their_guest)
        join_table(self.profile, self.table)

        players = self.detail().json()['table']['players']
        removable = {p['name']: p['can_remove'] for p in players}

        # Not the guest's owner and not the table author: no remove control.
        self.assertFalse(any(removable.values()))

    # ── Adding guests ─────────────────────────────────────────────────────

    def test_add_guest_seats_them_and_returns_the_new_detail(self):
        guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')
        join_table(self.profile, self.table)

        response = self.add_guest_request(guest.id)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Player.objects.filter(
            table=self.table, guest_profile=guest).exists())
        body = response.json()['table']
        self.assertEqual(body['players_count'], 2)
        self.assertEqual(body['guests'], [])

    def test_cannot_seat_someone_elses_guest(self):
        other = UserProfileFactory()
        their_guest = GuestProfile.objects.create(owner=other, name='Loro')
        join_table(self.profile, self.table)

        response = self.add_guest_request(their_guest.id)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['error'], 'unknown_guest')
        self.assertFalse(Player.objects.filter(guest_profile=their_guest).exists())

    def test_cannot_add_a_guest_without_being_at_the_table(self):
        guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')

        response = self.add_guest_request(guest.id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'not_at_table')

    def test_garbage_body_is_a_clean_404(self):
        join_table(self.profile, self.table)
        url = reverse('telegram-miniapp-guest-add',
                      kwargs={'slug': self.table.slug})

        response = self.client.post(
            url, data='not json', content_type='application/json',
            headers={'X-Telegram-Init-Data': self.init_data()})

        self.assertEqual(response.status_code, 404)

    # ── Removing guests ───────────────────────────────────────────────────

    def test_owner_removes_their_guest(self):
        guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')
        join_table(self.profile, self.table)
        player = add_guest(self.profile, self.table, guest)

        response = self.remove_guest_request(player.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Player.objects.filter(id=player.id).exists())

    def test_cannot_remove_a_guest_you_do_not_own(self):
        other = UserProfileFactory()
        join_table(other, self.table)
        their_guest = GuestProfile.objects.create(owner=other, name='Loro')
        player = add_guest(other, self.table, their_guest)
        join_table(self.profile, self.table)

        response = self.remove_guest_request(player.id)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'forbidden')
        self.assertTrue(Player.objects.filter(id=player.id).exists())

    def test_removing_a_non_guest_player_is_not_possible(self):
        join_table(self.profile, self.table)
        me = Player.objects.get(table=self.table, user_profile=self.profile)

        response = self.remove_guest_request(me.id)

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Player.objects.filter(id=me.id).exists())
