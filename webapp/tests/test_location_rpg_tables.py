import datetime

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory, TableFactory


class LocationDetailHidesRolePlayingTablesTest(TestCase):
    def setUp(self):
        self.client = Client()
        author = UserProfileFactory()
        self.location = LocationFactory(creator=author)
        today = timezone.localdate()
        for date in (today + datetime.timedelta(days=3), today - datetime.timedelta(days=3)):
            for name in ("Gioco di ruolo", "gdr", "Role Games"):
                TableFactory(title=f"RPG {name} {date}", game=GameFactory(name=name),
                             location=self.location, author=author, date=date)
            TableFactory(title=f"Board night {date}", game=GameFactory(name="Terraforming Mars"),
                         location=self.location, author=author, date=date)
            TableFactory(title=f"No game {date}", game=None,
                         location=self.location, author=author, date=date)

    def test_role_playing_tables_are_hidden(self):
        response = self.client.get(reverse('location-detail', kwargs={'slug': self.location.slug}))
        future = list(response.context['future_tables'])
        past = list(response.context['past_tables'])
        self.assertEqual(len(future), 2)
        self.assertEqual(len(past), 2)
        for table in future + past:
            self.assertFalse(table.title.startswith("RPG"))
        self.assertEqual(response.context['tables_count'], 4)
