import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Player, Table
from webapp.services.tables import can_edit_leaderboard


class LifecyclePhaseTest(SimpleTestCase):
    """Phase boundaries: live for 12h after start, leaderboard editable for 7 days."""

    def setUp(self):
        self.table = Table(date=datetime.date(2026, 10, 1), time=datetime.time(20, 30))
        self.start = datetime.datetime(2026, 10, 1, 20, 30, tzinfo=ZoneInfo(settings.TIME_ZONE))

    def phase_at(self, delta):
        return self.table.lifecycle_phase(at=self.start + delta)

    def test_phases(self):
        cases = [
            (-datetime.timedelta(minutes=1), Table.PHASE_UPCOMING),
            (datetime.timedelta(0), Table.PHASE_LIVE),
            (datetime.timedelta(hours=12) - datetime.timedelta(minutes=1), Table.PHASE_LIVE),
            (datetime.timedelta(hours=12), Table.PHASE_RECENTLY_ENDED),
            (datetime.timedelta(days=7) - datetime.timedelta(minutes=1), Table.PHASE_RECENTLY_ENDED),
            (datetime.timedelta(days=7), Table.PHASE_ARCHIVED),
        ]
        for delta, phase in cases:
            with self.subTest(delta=delta):
                self.assertEqual(self.phase_at(delta), phase)

    def test_leaderboard_editable_until_seven_days(self):
        self.assertEqual(
            self.table.computed_leaderboard_status(at=self.start + datetime.timedelta(days=6)),
            Table.LEADERBOARD_EDITABLE,
        )
        self.assertEqual(
            self.table.computed_leaderboard_status(at=self.start + datetime.timedelta(days=7)),
            Table.LEADERBOARD_NOT_EDITABLE,
        )


class LeaderboardEditWindowTest(TestCase):
    def setUp(self):
        self.player = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.game = GameFactory()

    def make_past_table(self, days_ago):
        table = Table.objects.create(
            title='Serata giochi',
            location=self.location,
            author=UserProfileFactory(),
            game=self.game,
            date=timezone.localdate() - datetime.timedelta(days=days_ago),
            time=datetime.time(20, 30),
        )
        Player.objects.create(table=table, user_profile=self.player)
        return table

    def test_player_can_edit_five_days_after(self):
        table = self.make_past_table(5)
        self.assertEqual(table.leaderboard_status, Table.LEADERBOARD_EDITABLE)
        self.assertTrue(can_edit_leaderboard(self.player, table))

    def test_player_cannot_edit_after_a_week(self):
        table = self.make_past_table(8)
        self.assertEqual(table.leaderboard_status, Table.LEADERBOARD_NOT_EDITABLE)
        self.assertFalse(can_edit_leaderboard(self.player, table))
