import datetime

from django.test import TestCase
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import (
    Comment, CommentType, GuestProfile, Location, Member, Membership, Player, Table,
)
from webapp.services.tables import (
    TableActionError, add_guest, join_table, leave_table, remove_guest,
)


def make_table(location=None, author=None, days_ahead=7, **kwargs):
    """A table whose status is derived from its date — Table.save() recomputes
    it, so a past date is the only way to obtain a CLOSED table."""
    return Table.objects.create(
        title=kwargs.pop('title', 'Serata giochi'),
        location=location,
        author=author,
        date=timezone.localdate() + datetime.timedelta(days=days_ahead),
        time=datetime.time(20, 30),
        **kwargs,
    )


def system_comments(table):
    return list(
        Comment.objects
        .filter(table=table, comment_type=CommentType.SYSTEM)
        .values_list('content', flat=True)
    )


class JoinTableTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.table = make_table(location=self.location, author=UserProfileFactory())

    def test_join_creates_player_and_system_comment(self):
        result = join_table(self.profile, self.table)

        self.assertTrue(
            Player.objects.filter(table=self.table, user_profile=self.profile).exists())
        self.assertEqual(result.player.user_profile, self.profile)
        self.assertEqual(result.warnings, [])
        self.assertIn(f"PLAYER_IN:{self.profile.nickname}", system_comments(self.table))

    def test_unverified_email_is_refused(self):
        self.profile.is_email_verified = False
        self.profile.save(update_fields=['is_email_verified'])

        with self.assertRaises(TableActionError) as ctx:
            join_table(self.profile, self.table)

        self.assertEqual(ctx.exception.code, 'email_not_verified')
        self.assertFalse(Player.objects.filter(table=self.table).exists())

    def test_closed_table_is_refused(self):
        past = make_table(location=self.location, author=self.profile, days_ahead=-5)
        self.assertEqual(past.status, Table.CLOSED)

        with self.assertRaises(TableActionError) as ctx:
            join_table(self.profile, past)

        self.assertEqual(ctx.exception.code, 'table_closed')

    def test_joining_twice_is_refused_as_a_warning(self):
        join_table(self.profile, self.table)

        with self.assertRaises(TableActionError) as ctx:
            join_table(self.profile, self.table)

        self.assertEqual(ctx.exception.code, 'already_joined')
        self.assertEqual(ctx.exception.level, 'warning')
        self.assertEqual(Player.objects.filter(table=self.table).count(), 1)

    def test_full_table_is_refused(self):
        self.table.max_players = 2
        self.table.external_players = 2
        self.table.save()

        with self.assertRaises(TableActionError) as ctx:
            join_table(self.profile, self.table)

        self.assertEqual(ctx.exception.code, 'table_full')

    def test_unlimited_seats_table_never_fills_up(self):
        self.table.max_players = 2
        self.table.external_players = 5
        self.table.unlimited_seats = True
        self.table.save()

        join_table(self.profile, self.table)

        self.assertTrue(
            Player.objects.filter(table=self.table, user_profile=self.profile).exists())

    def test_overlapping_event_table_returns_a_warning(self):
        from webapp.models import Event

        event = Event.objects.create(name='Con')
        # A table belongs to either a location or an event, never both
        # (DB constraint `table_location_xor_event`).
        first = make_table(author=self.profile, event=event)
        second = make_table(author=self.profile, event=event)
        join_table(self.profile, first)

        result = join_table(self.profile, second)

        self.assertEqual([w.code for w in result.warnings], ['overlapping_table'])


class MembersOnlyJoinTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.location = LocationFactory(
            creator=self.owner, table_join_permission=Location.PERM_MEMBERS_ONLY)
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=self.owner)

    def make_active_member(self, profile):
        member = Member.objects.create(
            location=self.location, user_profile=profile,
            first_name='A', last_name='B',
        )
        Membership.objects.create(member=member, status=Membership.ACTIVE)

    def test_non_member_is_refused(self):
        with self.assertRaises(TableActionError) as ctx:
            join_table(self.outsider, self.table)

        self.assertEqual(ctx.exception.code, 'members_only')

    def test_pending_membership_is_not_enough(self):
        member = Member.objects.create(
            location=self.location, user_profile=self.outsider,
            first_name='A', last_name='B',
        )
        Membership.objects.create(member=member, status=Membership.PENDING)

        with self.assertRaises(TableActionError):
            join_table(self.outsider, self.table)

    def test_active_member_can_join(self):
        self.make_active_member(self.outsider)

        join_table(self.outsider, self.table)

        self.assertTrue(Player.objects.filter(
            table=self.table, user_profile=self.outsider).exists())

    def test_owner_and_manager_bypass_the_restriction(self):
        join_table(self.owner, self.table)
        join_table(self.manager, self.table)

        self.assertEqual(Player.objects.filter(table=self.table).count(), 2)

    def test_superuser_bypasses_the_restriction(self):
        self.outsider.user.is_superuser = True
        self.outsider.user.save(update_fields=['is_superuser'])

        join_table(self.outsider, self.table)

        self.assertTrue(Player.objects.filter(
            table=self.table, user_profile=self.outsider).exists())


class LeaveTableTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.table = make_table(location=self.location, author=self.profile)
        join_table(self.profile, self.table)

    def test_leaving_removes_the_player_and_logs_it(self):
        leave_table(self.profile, self.table)

        self.assertFalse(Player.objects.filter(
            table=self.table, user_profile=self.profile).exists())
        self.assertIn(f"PLAYER_OUT:{self.profile.nickname}", system_comments(self.table))

    def test_leaving_takes_own_guests_along(self):
        guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')
        add_guest(self.profile, self.table, guest)

        leave_table(self.profile, self.table)

        self.assertFalse(Player.objects.filter(table=self.table).exists())
        self.assertIn("GUEST_REMOVED:Ospite", system_comments(self.table))

    def test_leaving_a_closed_table_is_refused(self):
        past = make_table(location=self.location, author=self.profile, days_ahead=-5)
        Player.objects.create(table=past, user_profile=self.profile)

        with self.assertRaises(TableActionError) as ctx:
            leave_table(self.profile, past)

        self.assertEqual(ctx.exception.code, 'table_closed')

    def test_leaving_a_table_you_are_not_at_is_refused(self):
        stranger = UserProfileFactory()

        with self.assertRaises(TableActionError) as ctx:
            leave_table(stranger, self.table)

        self.assertEqual(ctx.exception.code, 'not_at_table')


class GuestTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.table = make_table(location=self.location, author=self.profile)
        join_table(self.profile, self.table)
        self.guest = GuestProfile.objects.create(owner=self.profile, name='Ospite')

    def test_add_guest_creates_player_and_comment(self):
        add_guest(self.profile, self.table, self.guest)

        self.assertTrue(Player.objects.filter(
            table=self.table, guest_profile=self.guest).exists())
        self.assertIn("GUEST_ADDED:Ospite", system_comments(self.table))

    def test_only_players_can_add_guests(self):
        stranger = UserProfileFactory()
        their_guest = GuestProfile.objects.create(owner=stranger, name='Altro')

        with self.assertRaises(TableActionError) as ctx:
            add_guest(stranger, self.table, their_guest)

        self.assertEqual(ctx.exception.code, 'not_at_table')

    def test_adding_the_same_guest_twice_is_refused_as_a_warning(self):
        add_guest(self.profile, self.table, self.guest)

        with self.assertRaises(TableActionError) as ctx:
            add_guest(self.profile, self.table, self.guest)

        self.assertEqual(ctx.exception.code, 'guest_already_added')
        self.assertEqual(ctx.exception.level, 'warning')

    def test_guest_refused_when_the_table_is_full(self):
        self.table.max_players = 1
        self.table.save()

        with self.assertRaises(TableActionError) as ctx:
            add_guest(self.profile, self.table, self.guest)

        self.assertEqual(ctx.exception.code, 'table_full')

    def test_guest_on_unlimited_table_still_hits_the_seat_check(self):
        """Documents a known inconsistency carried over from the original view:
        join_table exempts unlimited tables from the capacity check, add_guest
        does not."""
        self.table.max_players = 1
        self.table.unlimited_seats = True
        self.table.save()

        with self.assertRaises(TableActionError) as ctx:
            add_guest(self.profile, self.table, self.guest)

        self.assertEqual(ctx.exception.code, 'table_full')

    def test_owner_can_remove_their_guest(self):
        player = add_guest(self.profile, self.table, self.guest)

        remove_guest(self.profile, self.table, player)

        self.assertFalse(Player.objects.filter(id=player.id).exists())
        self.assertIn("GUEST_REMOVED:Ospite", system_comments(self.table))

    def test_table_author_can_remove_someone_elses_guest(self):
        other = UserProfileFactory()
        join_table(other, self.table)
        their_guest = GuestProfile.objects.create(owner=other, name='Altro')
        player = add_guest(other, self.table, their_guest)

        remove_guest(self.table.author, self.table, player)

        self.assertFalse(Player.objects.filter(id=player.id).exists())

    def test_stranger_cannot_remove_a_guest(self):
        player = add_guest(self.profile, self.table, self.guest)
        stranger = UserProfileFactory()

        with self.assertRaises(TableActionError) as ctx:
            remove_guest(stranger, self.table, player)

        self.assertEqual(ctx.exception.code, 'forbidden')
        self.assertTrue(Player.objects.filter(id=player.id).exists())
