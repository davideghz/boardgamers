from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, GameFactory


class LocalGameSearchTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(UserProfileFactory().user)
        self.url = reverse('bgg-search')

    def test_prefix_matches_come_first(self):
        GameFactory(name="Azul: Summer Pavilion")
        GameFactory(name="Bazul")
        GameFactory(name="Azul")
        names = [g['name'] for g in self.client.get(self.url, {'q': 'azul'}).json()['local']]
        self.assertEqual(names, ["Azul", "Azul: Summer Pavilion", "Bazul"])

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url, {'q': 'azul'}).status_code, 401)


@patch('webapp.api.views.fetch_bgg_classifications')
@patch('webapp.api.views.search_bgg')
class ExternalGameSearchTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(UserProfileFactory().user)
        self.url = reverse('bgg-search-external')

    def test_known_games_come_with_their_id_and_expansions_are_dropped(self, search_bgg, classify):
        catan = GameFactory(name="Catan", bgg_code='13', min_players=3, max_players=4)
        search_bgg.return_value = [
            {'bgg_id': '13', 'name': "I Coloni di Catan", 'year_published': 1995},
            {'bgg_id': '325', 'name': "Catan: Seafarers", 'year_published': 1997},
            {'bgg_id': '27710', 'name': "Catan Dice Game", 'year_published': 2007},
        ]
        classify.return_value = {
            '325': {'is_expansion': True, 'name': "Catan: Seafarers", 'year_published': 1997},
            '27710': {'is_expansion': False, 'name': "Catan Dice Game", 'year_published': 2007},
        }

        results = self.client.get(self.url, {'q': 'coloni di catan'}).json()['bgg']

        self.assertEqual([r['bgg_id'] for r in results], ['13', '27710'])
        self.assertEqual(results[0]['id'], catan.id)
        self.assertEqual(results[0]['name'], "Catan")
        self.assertNotIn('id', results[1])
        classify.assert_called_once_with(['325', '27710'])

    def test_bgg_failure_is_reported(self, search_bgg, classify):
        search_bgg.side_effect = Exception("timeout")
        data = self.client.get(self.url, {'q': 'catan'}).json()
        self.assertEqual(data, {'bgg': [], 'error': 'unavailable'})
