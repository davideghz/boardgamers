import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Game, LocationGame, LocationGameTag
from webapp.views.location_views import BGG_IMPORT_BATCH_SIZE


class LocationGameCSVImportTest(TestCase):
    def setUp(self):
        translation.activate('it')
        self.addCleanup(translation.deactivate)
        self.owner = UserProfileFactory(preferred_language='it')
        self.destination = LocationFactory(creator=self.owner)
        self.client.force_login(self.owner.user)

    def url(self, name, location=None):
        return reverse(name, args=[(location or self.destination).slug])

    def upload(self, content):
        return self.client.post(self.url('location-games-csv-import'), {
            'csv_file': SimpleUploadedFile('games.csv', content, content_type='text/csv'),
        })

    def batch(self, items, **options):
        return self.client.post(self.url('location-games-csv-import-batch'), {
            'items': json.dumps(items), 'ownership': LocationGame.OWNED_BY_LOCATION,
            'physical_location': LocationGame.AT_ASSOCIATION, **options,
        })

    @patch('webapp.services.bgg.requests.get')
    def test_export_from_one_library_can_be_imported_into_another(self, get_bgg):
        source = LocationFactory(creator=self.owner)
        codes = {str(i) for i in range(100, 112)}
        for code in sorted(codes):
            game = GameFactory(name=f'Gioco «{code}», edizione italiana', bgg_code=code, is_expansion=code == '111')
            LocationGame.objects.create(location=source, game=game, notes='Prima riga\n"Seconda riga"')
        LocationGame.objects.create(location=source, game=GameFactory(name='Prototipo'))
        LocationGame.objects.create(
            location=source, game=GameFactory(name='Ritirato', bgg_code='999'), is_archived=True,
        )

        manage = self.client.get(self.url('location-manage-games'))
        self.assertContains(manage, self.url('location-games-csv-import'))
        export = self.client.get(self.url('location-games-csv', source))
        self.assertContains(export, 'ID BGG')
        self.assertTrue(export.content.startswith(b'\xef\xbb\xbf'))
        preview = self.upload(export.content)
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, self.url('location-games-csv-import-batch'))
        self.assertContains(preview, 'ID BGG mancante nelle righe')
        self.assertEqual(preview.context['importable_count'], len(codes))
        self.assertEqual([item['bgg_id'] for item in preview.context['expansions']], ['111'])
        self.assertFalse(self.destination.location_games.exists())

        items = [{'bgg_id': item['bgg_id']} for item in preview.context['games'] + preview.context['expansions']]
        for offset in range(0, len(items), BGG_IMPORT_BATCH_SIZE):
            batch = items[offset:offset + BGG_IMPORT_BATCH_SIZE]
            added = [item['bgg_id'] for item in batch]
            response = self.batch(batch, tag_name='Da CSV', physical_location=LocationGame.AT_HOME)
            self.assertEqual(response.json(), {'added': added, 'skipped': [], 'archived': [], 'failed': []})
            retry = self.batch(batch, tag_name='Retry')
            self.assertEqual(retry.json(), {'added': [], 'skipped': added, 'archived': [], 'failed': []})

        entries = self.destination.location_games.all()
        self.assertEqual(set(entries.values_list('game__bgg_code', flat=True)), codes)
        self.assertEqual(set(entries.values_list('physical_location', 'notes')), {(LocationGame.AT_HOME, '')})
        self.assertEqual(list(self.destination.game_tags.values_list('name', flat=True)), ['Da CSV'])
        tag = LocationGameTag.objects.get(location=self.destination, name='Da CSV')
        self.assertEqual(tag.games.count(), len(codes))
        get_bgg.assert_not_called()

    @patch('webapp.services.bgg.requests.get')
    def test_uses_only_bgg_id_even_when_a_title_matches_an_uncoded_game(self, get_bgg):
        local_game = GameFactory(name='Carcassonne')
        LocationGame.objects.create(location=self.destination, game=local_game)
        preview = self.upload(b'Game,BGG ID\nCarcassonne,822\nSconosciuto,54321\nNon e un gioco,98765\n')
        self.assertEqual(preview.context['importable_count'], 3)
        get_bgg.assert_not_called()

        get_bgg.return_value.status_code = 200
        get_bgg.return_value.content = b'''<items>
            <item id="822" type="boardgameexpansion"><name type="primary" value="Carcassonne"/></item>
            <item id="98765" type="videogame"><name type="primary" value="Video Game"/></item>
        </items>'''
        response = self.batch([
            {'bgg_id': '822', 'name': local_game.name}, {'bgg_id': '54321'}, {'bgg_id': '98765'},
        ])
        self.assertEqual(response.json(), {'added': ['822'], 'skipped': [], 'archived': [], 'failed': ['54321', '98765']})
        self.assertEqual(get_bgg.call_args.kwargs['params']['id'], '822,54321,98765')
        imported = self.destination.location_games.get(game__bgg_code='822').game
        self.assertTrue(imported.is_expansion)
        self.assertNotEqual(imported.pk, local_game.pk)
        self.assertFalse(Game.objects.filter(bgg_code__in=['54321', '98765']).exists())

    def test_preview_marks_present_and_withdrawn_ids_and_batch_skips_them(self):
        GameFactory(name='Older duplicate', bgg_code='13')
        LocationGame.objects.create(location=self.destination, game=GameFactory(name='Catan', bgg_code='13'))
        LocationGame.objects.create(
            location=self.destination, game=GameFactory(name='Azul', bgg_code='230802'), is_archived=True,
        )
        preview = self.upload(b'BGG ID\n13\n230802\n')
        self.assertEqual([item['status'] for item in preview.context['games']], ['in_library', 'archived'])
        self.assertEqual(preview.context['importable_count'], 0)
        response = self.batch([{'bgg_id': '13'}, {'bgg_id': '230802'}])
        self.assertEqual(response.json(), {'added': [], 'skipped': ['13'], 'archived': ['230802'], 'failed': []})
        self.assertEqual(self.destination.location_games.count(), 2)

    def test_handles_semicolons_duplicate_ids_and_reports_invalid_rows(self):
        response = self.upload(
            b'\xef\xbb\xbf"Gioco";"ID BGG";"Note"\r\n'
            b'"Titolo; uno";00013;"a\r\nb"\r\nDoppione;13;\r\nVuoto;;\r\nErrato;abc;\r\nZero;0;\r\n',
        )
        self.assertEqual([(i['bgg_id'], i['name']) for i in response.context['games']], [('13', 'Titolo; uno')])
        self.assertEqual(response.context['missing_lines'], [5])
        self.assertEqual(response.context['invalid_lines'], [6, 7])
        headerless = self.upload(b'13\n822\n')
        self.assertEqual([i['bgg_id'] for i in headerless.context['games']], ['13', '822'])

    def test_rejects_files_without_id_column_and_invalid_batches(self):
        for content in (b'Game,Notes\nCatan,none\n', b'BGG ID\n\xff', b'BGG ID\n"unterminated'):
            with self.subTest(content=content):
                preview = self.upload(content)
                self.assertIn('csv_file', preview.context['csv_form'].errors)
        for code in ('10.0', '0', '-1', True):
            with self.subTest(code=code):
                self.assertEqual(self.batch([{'bgg_id': code}]).status_code, 400)
        self.assertFalse(self.destination.location_games.exists())

    def test_outsider_cannot_upload_or_import(self):
        self.client.force_login(UserProfileFactory(preferred_language='it').user)
        self.assertEqual(self.client.get(self.url('location-games-csv-import')).status_code, 403)
        self.assertEqual(self.upload(b'BGG ID\n13\n').status_code, 403)
        self.assertEqual(self.batch([{'bgg_id': '13'}]).status_code, 403)
