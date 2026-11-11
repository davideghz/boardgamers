import json
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory
from webapp.models import Game, LocationGame, LocationGameTag, Member
from webapp.services import bgg
from webapp.services.bgg import BGGCollectionError, fetch_bgg_collection, import_games_from_bgg


def _response(status, body=''):
    resp = MagicMock(status_code=status, content=body.encode())
    return resp


GAMES_XML = '''<?xml version="1.0" encoding="utf-8"?>
<items totalitems="3">
  <item objecttype="thing" objectid="13" subtype="boardgame">
    <name sortindex="1">Catan</name><yearpublished>1995</yearpublished>
    <thumbnail>//cf.geekdo-images.com/catan.jpg</thumbnail>
  </item>
  <item objecttype="thing" objectid="822" subtype="boardgame">
    <name sortindex="1">Carcassonne</name><yearpublished>2000</yearpublished>
  </item>
  <item objecttype="thing" objectid="13" subtype="boardgame">
    <name sortindex="1">Catan</name><yearpublished>1995</yearpublished>
  </item>
</items>'''

EXPANSIONS_XML = '''<?xml version="1.0" encoding="utf-8"?>
<items totalitems="1">
  <item objecttype="thing" objectid="325" subtype="boardgameexpansion">
    <name sortindex="1">Catan: Seafarers</name><yearpublished>1997</yearpublished>
  </item>
</items>'''

ERROR_XML = '''<?xml version="1.0" encoding="utf-8"?>
<errors><error><message>Invalid username specified</message></error></errors>'''


@patch('webapp.services.bgg.time.sleep')
@patch('webapp.services.bgg.requests.get')
class FetchCollectionTest(TestCase):
    def test_games_then_expansions_sorted_and_deduplicated(self, get, sleep):
        get.side_effect = [_response(200, GAMES_XML), _response(200, EXPANSIONS_XML)]
        items = fetch_bgg_collection('someone')
        self.assertEqual([(i['bgg_id'], i['is_expansion']) for i in items],
                         [('822', False), ('13', False), ('325', True)])
        self.assertEqual(items[1]['thumbnail'], 'https://cf.geekdo-images.com/catan.jpg')
        self.assertEqual(items[1]['year_published'], 1995)
        params = get.call_args_list[0].kwargs['params']
        self.assertEqual((params['own'], params['excludesubtype']), (1, 'boardgameexpansion'))

    def test_waits_while_bgg_prepares_the_collection(self, get, sleep):
        get.side_effect = [_response(202), _response(202), _response(200, GAMES_XML), _response(200, EXPANSIONS_XML)]
        self.assertEqual(len(fetch_bgg_collection('someone')), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_gives_up_past_the_time_budget(self, get, sleep):
        get.return_value = _response(202)
        with patch.object(bgg, 'COLLECTION_TIME_BUDGET', 0):
            with self.assertRaises(BGGCollectionError) as ctx:
                fetch_bgg_collection('someone')
        self.assertEqual(ctx.exception.code, BGGCollectionError.PENDING)

    def test_unknown_user(self, get, sleep):
        get.return_value = _response(200, ERROR_XML)
        with self.assertRaises(BGGCollectionError) as ctx:
            fetch_bgg_collection('nobody')
        self.assertEqual(ctx.exception.code, BGGCollectionError.NOT_FOUND)

    def test_bgg_down(self, get, sleep):
        get.return_value = _response(500)
        with self.assertRaises(BGGCollectionError) as ctx:
            fetch_bgg_collection('someone')
        self.assertEqual(ctx.exception.code, BGGCollectionError.UNAVAILABLE)


def _thing(bgg_id, name):
    return {
        'name': name, 'bgg_type': 'boardgame', 'is_expansion': False, 'mechanics': [], 'description': '',
        'bgg_code': str(bgg_id),
        'year_published': 2000, 'min_players': 2, 'max_players': 4, 'min_playtime': 30, 'max_playtime': 60,
        'weight': None, 'image_url': None,
    }


@patch('webapp.services.bgg.fetch_bgg_things')
class ImportGamesTest(TestCase):
    def test_reuses_known_games_and_fetches_only_the_others(self, fetch):
        by_code = GameFactory(name="Catan", bgg_code='13')
        by_name = GameFactory(name="Carcassonne", bgg_code=None)
        fetch.return_value = {'9209': _thing(9209, "Ticket to Ride")}
        games = import_games_from_bgg([
            {'bgg_id': '13', 'name': "Catan"},
            {'bgg_id': '822', 'name': "carcassonne"},
            {'bgg_id': '9209', 'name': "Ticket to Ride"},
            {'bgg_id': '1', 'name': "Unknown to BGG"},
        ])
        fetch.assert_called_once_with(['9209', '1'])
        self.assertEqual(games['13'], by_code)
        self.assertEqual(games['822'], by_name)
        self.assertEqual(games['9209'].bgg_code, '9209')
        self.assertTrue(games['9209'].bgg_imported)
        self.assertNotIn('1', games)

    def test_name_match_skips_games_with_another_bgg_code(self, fetch):
        GameFactory(name="Carcassonne", bgg_code='999')
        fetch.return_value = {'822': _thing(822, "Carcassonne")}
        games = import_games_from_bgg([{'bgg_id': '822', 'name': "Carcassonne"}])
        self.assertEqual(games['822'].bgg_code, '822')
        self.assertEqual(Game.objects.filter(name="Carcassonne").count(), 2)


EXPANSION_THING_XML = '''<?xml version="1.0" encoding="utf-8"?>
<items>
  <item type="boardgameexpansion" id="411435">
    <name type="primary" sortindex="1" value="Coffee Rush: Piece of Cake" />
    <description>Cakes!</description><yearpublished value="2024" />
    <minplayers value="2" /><maxplayers value="4" />
  </item>
</items>'''


@patch('webapp.services.bgg.requests.get')
class ImportExpansionTest(TestCase):
    def test_expansion_is_imported_and_flagged(self, get):
        get.return_value = _response(200, EXPANSION_THING_XML)
        game = bgg.import_game_from_bgg('411435')
        self.assertEqual(game.name, "Coffee Rush: Piece of Cake")
        self.assertTrue(game.is_expansion)
        self.assertIn('boardgameexpansion', get.call_args.kwargs['params']['type'])


class ImportViewsTest(TestCase):
    def setUp(self):
        translation.activate('en')
        self.addCleanup(translation.deactivate)
        self.owner = UserProfileFactory(preferred_language='en')
        self.location = LocationFactory(creator=self.owner)
        self.slug = {'slug': self.location.slug}
        self.preview_url = reverse('location-games-bgg-import', kwargs=self.slug)
        self.batch_url = reverse('location-games-bgg-import-batch', kwargs=self.slug)
        self.client.force_login(self.owner.user)

    def batch(self, items, **options):
        data = {'ownership': LocationGame.OWNED_BY_LOCATION, 'physical_location': LocationGame.AT_ASSOCIATION,
                'items': json.dumps(items), **options}
        return self.client.post(self.batch_url, data)

    def test_outsider_is_refused(self):
        self.client.force_login(UserProfileFactory(preferred_language='en').user)
        self.assertEqual(self.client.get(self.preview_url).status_code, 403)
        self.assertEqual(self.batch([{'bgg_id': '13', 'name': 'Catan'}]).status_code, 403)

    def test_form_without_username(self):
        response = self.client.get(self.preview_url)
        self.assertContains(response, "Load collection")
        self.assertNotContains(response, 'bgg-import-start')

    @patch('webapp.views.location_views.fetch_bgg_collection')
    def test_preview_marks_what_is_already_there(self, fetch):
        LocationGame.objects.create(location=self.location, game=GameFactory(name="Catan", bgg_code='13'))
        LocationGame.objects.create(location=self.location, game=GameFactory(name="Azul", bgg_code=None))
        GameFactory(name="Carcassonne", bgg_code='822')
        fetch.return_value = [
            {'bgg_id': '13', 'name': "Catan", 'year_published': 1995, 'thumbnail': '', 'is_expansion': False},
            {'bgg_id': '230802', 'name': "Azul", 'year_published': 2017, 'thumbnail': '', 'is_expansion': False},
            {'bgg_id': '822', 'name': "Carcassonne", 'year_published': 2000, 'thumbnail': '', 'is_expansion': False},
            {'bgg_id': '9209', 'name': "Ticket to Ride", 'year_published': 2004, 'thumbnail': '', 'is_expansion': False},
            {'bgg_id': '325', 'name': "Seafarers", 'year_published': 1997, 'thumbnail': '', 'is_expansion': True},
        ]
        response = self.client.get(self.preview_url, {'username': 'someone'})
        statuses = {i['bgg_id']: i['status'] for i in response.context['games'] + response.context['expansions']}
        self.assertEqual(statuses, {'13': 'in_library', '230802': 'in_library', '822': 'known',
                                    '9209': 'new', '325': 'new'})
        self.assertEqual(response.context['importable_count'], 2)
        self.assertContains(response, "Expansions")

    @patch('webapp.views.location_views.fetch_bgg_collection')
    def test_preview_errors(self, fetch):
        fetch.side_effect = BGGCollectionError(BGGCollectionError.NOT_FOUND)
        self.assertContains(self.client.get(self.preview_url, {'username': 'nobody'}),
                            "There is no BoardGameGeek user called")
        fetch.side_effect = BGGCollectionError(BGGCollectionError.PENDING)
        self.assertContains(self.client.get(self.preview_url, {'username': 'someone'}), "Try again")
        fetch.side_effect = None
        fetch.return_value = []
        self.assertContains(self.client.get(self.preview_url, {'username': 'someone'}), "collection is private")

    @patch('webapp.views.location_views.import_games_from_bgg')
    def test_batch_adds_with_the_options_and_skips_the_rest(self, import_games):
        catan, azul = GameFactory(name="Catan", bgg_code='13'), GameFactory(name="Azul", bgg_code='230802')
        existing = LocationGame.objects.create(location=self.location, game=azul)
        member = Member.objects.create(location=self.location, first_name="Ada", last_name="L")
        self.location.enable_membership = True
        self.location.save()
        LocationGameTag.objects.create(location=self.location, name="From BGG", order=3)
        import_games.return_value = {'13': catan, '230802': azul}

        response = self.batch(
            [{'bgg_id': '13', 'name': 'Catan'}, {'bgg_id': '230802', 'name': 'Azul'}, {'bgg_id': '1', 'name': 'X'}],
            tag_name='from bgg', ownership=LocationGame.OWNED_BY_MEMBER, owner_member=member.pk,
            physical_location=LocationGame.AT_HOME)
        self.assertEqual(response.json(), {'added': ['13'], 'skipped': ['230802'], 'failed': ['1']})

        entry = LocationGame.objects.get(location=self.location, game=catan)
        self.assertEqual((entry.ownership, entry.owner_member, entry.physical_location),
                         (LocationGame.OWNED_BY_MEMBER, member, LocationGame.AT_HOME))
        self.assertEqual([t.name for t in entry.tags.all()], ["From BGG"])  # existing tag, any case
        self.assertFalse(existing.tags.exists())  # games already in the library are not touched

    @patch('webapp.views.location_views.import_games_from_bgg')
    def test_batch_creates_a_new_tag(self, import_games):
        import_games.return_value = {'13': GameFactory(name="Catan", bgg_code='13')}
        self.batch([{'bgg_id': '13', 'name': 'Catan'}], tag_name='  Imported  ')
        tag = self.location.game_tags.get()
        self.assertEqual((tag.name, tag.order), ("Imported", 1))
        self.assertEqual(list(tag.games.all()), list(self.location.location_games.all()))

    @patch('webapp.views.location_views.import_games_from_bgg')
    def test_batch_rejects_bad_input(self, import_games):
        too_many = [{'bgg_id': str(i), 'name': 'X'} for i in range(11)]
        for items in ([], too_many, [{'bgg_id': 'abc'}], [{'name': 'no id'}]):
            self.assertEqual(self.batch(items).status_code, 400)
        self.assertEqual(self.client.post(self.batch_url, {'items': 'not json'}).status_code, 400)
        import_games.assert_not_called()

    @patch('webapp.views.location_views.import_games_from_bgg', side_effect=Exception('BGG down'))
    def test_batch_reports_bgg_failures(self, import_games):
        self.assertEqual(self.batch([{'bgg_id': '13', 'name': 'Catan'}]).status_code, 502)
        self.assertFalse(LocationGame.objects.exists())
