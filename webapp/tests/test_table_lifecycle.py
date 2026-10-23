import datetime
import importlib
import io
from zoneinfo import ZoneInfo

from django.apps import apps as django_apps
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.forms import LocationManageDataForm
from webapp.models import Event, Location, Notification, Player, ResultMode, Table
from webapp.services.tables import (
    can_edit_leaderboard, leaderboard_available, reopen_location_leaderboards,
)


class LifecyclePhaseTest(SimpleTestCase):
    """Phase boundaries: live for 12h after start, then editable until the leaderboard window ends."""

    def setUp(self):
        self.start = datetime.datetime(2026, 10, 1, 20, 30, tzinfo=ZoneInfo(settings.TIME_ZONE))

    def make_table(self, **kwargs):
        return Table(date=datetime.date(2026, 10, 1), time=datetime.time(20, 30), **kwargs)

    def phase_at(self, table, delta):
        return table.lifecycle_phase(at=self.start + delta)

    def test_default_window_is_two_days(self):
        table = self.make_table()  # no location: the event default
        cases = [
            (-datetime.timedelta(minutes=1), Table.PHASE_UPCOMING),
            (datetime.timedelta(0), Table.PHASE_LIVE),
            (datetime.timedelta(hours=12) - datetime.timedelta(minutes=1), Table.PHASE_LIVE),
            (datetime.timedelta(hours=12), Table.PHASE_RECENTLY_ENDED),
            (datetime.timedelta(days=2) - datetime.timedelta(minutes=1), Table.PHASE_RECENTLY_ENDED),
            (datetime.timedelta(days=2), Table.PHASE_ARCHIVED),
        ]
        for delta, phase in cases:
            with self.subTest(delta=delta):
                self.assertEqual(self.phase_at(table, delta), phase)

    def test_location_window(self):
        table = self.make_table(location=Location(id=1, leaderboard_edit_days=10))
        self.assertEqual(self.phase_at(table, datetime.timedelta(days=10) - datetime.timedelta(minutes=1)),
                         Table.PHASE_RECENTLY_ENDED)
        self.assertEqual(self.phase_at(table, datetime.timedelta(days=10)), Table.PHASE_ARCHIVED)


class LeaderboardEditWindowTest(TestCase):
    def setUp(self):
        self.player = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.game = GameFactory()

    def make_past_table(self, days_ago, **kwargs):
        kwargs.setdefault('location', self.location)
        table = Table.objects.create(
            title='Serata giochi',
            author=UserProfileFactory(),
            game=self.game,
            date=timezone.localdate() - datetime.timedelta(days=days_ago),
            time=datetime.time(20, 30),
            **kwargs,
        )
        Player.objects.create(table=table, user_profile=self.player)
        return table

    def test_default_window_locks_after_two_days(self):
        self.assertTrue(can_edit_leaderboard(self.player, self.make_past_table(1)))
        table = self.make_past_table(3)
        self.assertEqual(table.leaderboard_status, Table.LEADERBOARD_NOT_EDITABLE)
        self.assertFalse(can_edit_leaderboard(self.player, table))

    def test_location_window_keeps_it_open_longer(self):
        self.location.leaderboard_edit_days = 10
        self.location.save()
        self.assertTrue(can_edit_leaderboard(self.player, self.make_past_table(8)))
        self.assertFalse(can_edit_leaderboard(self.player, self.make_past_table(11)))

    def test_lengthening_reopens_tables_silently(self):
        inside = self.make_past_table(5)
        outside = self.make_past_table(12)
        self.assertEqual(inside.leaderboard_status, Table.LEADERBOARD_NOT_EDITABLE)

        self.location.leaderboard_edit_days = 10
        self.location.save()
        self.assertEqual(reopen_location_leaderboards(self.location), 1)

        inside.refresh_from_db()
        outside.refresh_from_db()
        self.assertEqual(inside.leaderboard_status, Table.LEADERBOARD_EDITABLE)
        self.assertEqual(outside.leaderboard_status, Table.LEADERBOARD_NOT_EDITABLE)
        self.assertFalse(Notification.objects.filter(table=inside).exists())

    def test_form_bounds(self):
        for days, valid in ((1, False), (2, True), (30, True), (31, False)):
            with self.subTest(days=days):
                form = LocationManageDataForm(instance=self.location, data={'leaderboard_edit_days': days})
                form.is_valid()
                self.assertEqual('leaderboard_edit_days' not in form.errors, valid)


class EventLeaderboardSwitchTest(TestCase):
    def setUp(self):
        self.player = UserProfileFactory()
        self.superuser = UserProfileFactory()
        self.superuser.user.is_superuser = True
        self.superuser.user.save()
        self.event = Event.objects.create(name='Con', status=Event.APPROVED)
        self.table = Table.objects.create(
            title='Torneo', event=self.event, author=UserProfileFactory(), game=GameFactory(),
            date=timezone.localdate(), time=datetime.time(0, 0),
        )
        Player.objects.create(table=self.table, user_profile=self.player)
        self.url = reverse('event_table_detail', kwargs={'event_slug': self.event.slug, 'table_slug': self.table.slug})

    def test_on_by_default(self):
        self.assertTrue(self.event.leaderboard_enabled)
        self.assertTrue(can_edit_leaderboard(self.player, self.table))
        self.client.force_login(self.player.user)
        self.assertContains(self.client.get(self.url), 'id="leaderboardSection"')

    def test_off_hides_and_locks_it_for_everyone(self):
        self.event.leaderboard_enabled = False
        self.event.save()
        self.table.refresh_from_db()

        self.assertFalse(leaderboard_available(self.table))
        self.assertFalse(can_edit_leaderboard(self.player, self.table))
        self.assertFalse(can_edit_leaderboard(self.superuser, self.table))
        self.client.force_login(self.player.user)
        self.assertNotContains(self.client.get(self.url), 'id="leaderboardSection"')


class SwitchToTwoDayDefaultTest(TestCase):
    """Deploying the 2-day default must not notify the tables opened under the old 7-day window."""

    def setUp(self):
        self.location = LocationFactory(creator=UserProfileFactory())
        self.player = UserProfileFactory()
        self.game = GameFactory(default_result_mode=ResultMode.FFA)  # a game whose leaderboard notifies

    def make_table(self, days_ago):
        table = Table.objects.create(
            title='Serata', location=self.location, author=UserProfileFactory(), game=self.game,
            date=timezone.localdate() - datetime.timedelta(days=days_ago), time=datetime.time(20, 30),
        )
        Player.objects.create(table=table, user_profile=self.player)
        # As left by the 7-day window, bypassing save().
        Table.objects.filter(pk=table.pk).update(leaderboard_status=Table.LEADERBOARD_EDITABLE)
        return table

    def test_without_the_migration_the_cron_would_notify(self):
        self.make_table(5)
        call_command('update_table_status', stdout=io.StringIO())
        self.assertTrue(Notification.objects.filter(recipient=self.player).exists())

    def test_migration_locks_without_notifications_and_cron_stays_quiet(self):
        migration = importlib.import_module('webapp.migrations.0076_lock_leaderboards_past_default_window')
        old = self.make_table(5)
        recent = self.make_table(1)

        migration.lock_silently(django_apps, None)
        call_command('update_table_status', stdout=io.StringIO())

        old.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual(old.leaderboard_status, Table.LEADERBOARD_NOT_EDITABLE)
        self.assertEqual(recent.leaderboard_status, Table.LEADERBOARD_EDITABLE)
        self.assertFalse(Notification.objects.filter(recipient=self.player).exists())
