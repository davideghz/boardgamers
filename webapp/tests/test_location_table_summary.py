import datetime

from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Player


class LocationTableSummaryTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.date = datetime.date.today() + datetime.timedelta(days=1)
        self.url = reverse('location-manage-table-summary', kwargs={'slug': self.location.slug})
        self.client.force_login(self.owner.user)

    def _table(self, title, **kwargs):
        return TableFactory(title=title, author=self.owner, location=self.location, date=self.date, **kwargs)

    def _message(self, **params):
        params.setdefault('date_from', self.date.isoformat())
        params.setdefault('date_to', self.date.isoformat())
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        return response.context['message_text']

    def test_unlimited_table_shows_players_count_not_seats(self):
        table = self._table('Free play', unlimited_seats=True, max_players=2)
        Player.objects.create(user_profile=self.owner, table=table)
        table.external_players = 2
        table.save()

        message = self._message(show_full='on')

        # 3 players on a 2-seat cap: still listed as available, without x/y seats
        # (the profile language is Italian)
        self.assertIn('• *Free play*: 3 giocatori', message)
        self.assertNotIn('/2 posti', message)
        self.assertNotIn('Tavoli pieni', message)

    def test_limited_table_shows_seats(self):
        self._table('Catan', max_players=4)

        self.assertIn('• *Catan*: 0/4 posti', self._message())

    def test_table_links_are_optional(self):
        table = self._table('Catan')
        table_url = 'http://testserver' + table.get_absolute_url()

        self.assertNotIn(table_url, self._message())
        self.assertIn(table_url, self._message(show_links='on'))
