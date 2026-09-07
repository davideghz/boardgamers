"""Who may add or remove *other people* at a table.

One rule, `can_manage_roster`, reached from three places: the website's player
management page, the guest controls on the table page, and the Telegram Mini
App. These tests pin it at each entry point, because the previous split
(author-or-superuser in the views, author-or-owner in the templates) let the
website offer managers a button that then refused them.
"""

from django.test import TestCase, override_settings
from django.urls import reverse
from social_django.models import UserSocialAuth

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, GuestProfile, Player
from webapp.services.tables import (
    TableActionError, add_guest, can_manage_roster, join_table, remove_guest,
)
from webapp.tests.test_telegram_miniapp import BOT_TOKEN, build_init_data
from webapp.tests.test_telegram_miniapp_bootstrap import make_table


class CanManageRosterTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.author = UserProfileFactory()
        self.stranger = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=self.author)

    def test_author_and_location_staff_qualify(self):
        self.assertTrue(can_manage_roster(self.author, self.table))
        self.assertTrue(can_manage_roster(self.owner, self.table))
        self.assertTrue(can_manage_roster(self.manager, self.table))

    def test_superuser_qualifies(self):
        self.stranger.user.is_superuser = True
        self.stranger.user.save(update_fields=['is_superuser'])

        self.assertTrue(can_manage_roster(self.stranger, self.table))

    def test_a_plain_player_does_not(self):
        join_table(self.stranger, self.table)

        self.assertFalse(can_manage_roster(self.stranger, self.table))

    def test_anonymous_does_not(self):
        self.assertFalse(can_manage_roster(None, self.table))

    def test_managers_of_another_location_do_not(self):
        elsewhere = LocationFactory(creator=self.stranger)
        elsewhere.managers.add(self.stranger)

        self.assertFalse(can_manage_roster(self.stranger, self.table))

    def test_event_staff_qualify_on_event_tables(self):
        event = Event.objects.create(name='Con', creator=self.owner)
        event_table = make_table(author=self.author, event=event)

        self.assertTrue(can_manage_roster(self.owner, event_table))
        self.assertFalse(can_manage_roster(self.manager, event_table))


class GuestRemovalTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.guest_owner = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=UserProfileFactory())

        join_table(self.guest_owner, self.table)
        guest = GuestProfile.objects.create(owner=self.guest_owner, name='Ospite')
        self.guest_player = add_guest(self.guest_owner, self.table, guest)

    def test_location_manager_may_remove_someone_elses_guest(self):
        remove_guest(self.manager, self.table, self.guest_player)

        self.assertFalse(Player.objects.filter(id=self.guest_player.id).exists())

    def test_location_owner_may_remove_someone_elses_guest(self):
        remove_guest(self.owner, self.table, self.guest_player)

        self.assertFalse(Player.objects.filter(id=self.guest_player.id).exists())

    def test_another_player_still_may_not(self):
        other = UserProfileFactory()
        join_table(other, self.table)

        with self.assertRaises(TableActionError) as ctx:
            remove_guest(other, self.table, self.guest_player)

        self.assertEqual(ctx.exception.code, 'forbidden')
        self.assertTrue(Player.objects.filter(id=self.guest_player.id).exists())


class WebRosterPagesTest(TestCase):
    """The detail page has offered managers an "Invite/Remove Gamers" button for
    a while; the views behind it used to bounce them."""

    def setUp(self):
        self.manager = UserProfileFactory()
        self.stranger = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=UserProfileFactory())
        self.newcomer = UserProfileFactory()

    def test_manager_can_open_the_player_management_page(self):
        self.client.force_login(self.manager.user)

        response = self.client.get(
            reverse('table-players', kwargs={'slug': self.table.slug}))

        self.assertEqual(response.status_code, 200)

    def test_stranger_is_still_bounced(self):
        self.client.force_login(self.stranger.user)

        response = self.client.get(
            reverse('table-players', kwargs={'slug': self.table.slug}))

        self.assertRedirects(
            response, reverse('table-detail', kwargs={'slug': self.table.slug}))

    def test_manager_can_add_a_player(self):
        self.client.force_login(self.manager.user)

        self.client.post(
            reverse('table-add-player', kwargs={'slug': self.table.slug}),
            data={'player': self.newcomer.id})

        self.assertTrue(Player.objects.filter(
            table=self.table, user_profile=self.newcomer).exists())

    def test_manager_can_remove_a_player(self):
        join_table(self.newcomer, self.table)
        player = Player.objects.get(table=self.table, user_profile=self.newcomer)
        self.client.force_login(self.manager.user)

        self.client.post(reverse('remove-player', kwargs={
            'slug': self.table.slug, 'player_id': player.id}))

        self.assertFalse(Player.objects.filter(id=player.id).exists())

    def test_stranger_cannot_add_a_player(self):
        self.client.force_login(self.stranger.user)

        self.client.post(
            reverse('table-add-player', kwargs={'slug': self.table.slug}),
            data={'player': self.newcomer.id})

        self.assertFalse(Player.objects.filter(
            table=self.table, user_profile=self.newcomer).exists())

    def test_manager_sees_the_guest_remove_control(self):
        guest_owner = UserProfileFactory()
        join_table(guest_owner, self.table)
        guest = GuestProfile.objects.create(owner=guest_owner, name='Ospite')
        guest_player = add_guest(guest_owner, self.table, guest)
        self.client.force_login(self.manager.user)

        response = self.client.get(
            reverse('table-detail', kwargs={'slug': self.table.slug}))

        self.assertContains(response, reverse('table-remove-guest', kwargs={
            'slug': self.table.slug, 'player_id': guest_player.id}))

    def test_uninvolved_player_does_not_see_it(self):
        guest_owner = UserProfileFactory()
        join_table(guest_owner, self.table)
        guest = GuestProfile.objects.create(owner=guest_owner, name='Ospite')
        guest_player = add_guest(guest_owner, self.table, guest)
        join_table(self.stranger, self.table)
        self.client.force_login(self.stranger.user)

        response = self.client.get(
            reverse('table-detail', kwargs={'slug': self.table.slug}))

        self.assertNotContains(response, reverse('table-remove-guest', kwargs={
            'slug': self.table.slug, 'player_id': guest_player.id}))


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN)
class MiniAppRosterFlagTest(TestCase):
    def setUp(self):
        self.manager = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=UserProfileFactory())
        UserSocialAuth.objects.create(
            user=self.manager.user, provider='telegram', uid='42')

        guest_owner = UserProfileFactory()
        join_table(guest_owner, self.table)
        guest = GuestProfile.objects.create(owner=guest_owner, name='Ospite')
        self.guest_player = add_guest(guest_owner, self.table, guest)

    def test_manager_gets_the_remove_control(self):
        response = self.client.get(
            reverse('telegram-miniapp-detail', kwargs={'slug': self.table.slug}),
            headers={'X-Telegram-Init-Data': build_init_data(
                telegram_id=42, start_param=self.location.slug)})

        rows = {p['id']: p['can_remove'] for p in response.json()['table']['players']}
        self.assertTrue(rows[self.guest_player.id])
