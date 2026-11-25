from datetime import date, time

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventGame, Game, LocationGame, MasterEvent, MasterEventDate, Table
from webapp.services.event_games import effective_catalog


class MasterCatalogTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.master = MasterEvent.objects.create(name='Festival', status=Event.PUBLISHED)
        cls.day = date(2030, 3, 2)
        MasterEventDate.objects.create(master_event=cls.master, date=cls.day)
        cls.club = LocationFactory(name='Organizer Club')
        cls.live = Event.objects.create(
            name='Library event', organizer_location=cls.club, venue_location=cls.club, master_event=cls.master,
            status=Event.PUBLISHED, enable_public_games=True,
        )
        cls.curated = Event.objects.create(
            name='Selected event', organizer_location=cls.club, master_event=cls.master,
            status=Event.PUBLISHED, enable_public_games=True,
        )
        for event in (cls.live, cls.curated):
            EventDate.objects.create(event=event, date=cls.day)
        cls.url = reverse('master-event-games', args=[cls.master.slug])

    def test_union_deduplicates_games_and_sources_and_lists_public_sessions(self):
        shared = GameFactory(name='Azul')
        only_library = GameFactory(name='Cascadia')
        LocationGame.objects.create(location=self.club, game=shared, notes='Private inventory note')
        LocationGame.objects.create(location=self.club, game=only_library)
        EventGame.objects.create(event=self.curated, game=shared)
        first = Table.objects.create(event=self.live, game=shared, title='Morning table', date=self.day, time=time(10))
        second = Table.objects.create(
            event=self.curated, game=shared, title='Evening table', date=self.day, time=time(18),
        )
        Table.objects.create(location=self.club, game=shared, title='Standalone table', date=self.day)
        page = self.client.get(self.url)
        entries = {entry['game']: entry['offers'] for entry in page.context['entries']}
        self.assertEqual(set(entries), {shared, only_library})
        self.assertEqual(entries[shared], [
            {'event': self.live, 'tables': [first]}, {'event': self.curated, 'tables': [second]},
        ])
        self.assertEqual(entries[only_library], [{'event': self.live, 'tables': []}])
        self.assertContains(page, 'Azul', count=1)
        self.assertContains(page, first.get_absolute_url())
        self.assertContains(page, second.get_absolute_url())
        self.assertContains(page, self.club.name)
        self.assertNotContains(page, 'Standalone table')
        self.assertNotContains(page, 'Private inventory note')
        self.assertContains(self.client.get(self.master.get_absolute_url()), self.url)

    def test_respects_event_library_and_table_visibility(self):
        game = GameFactory(name='Public game')
        LocationGame.objects.create(location=self.club, game=game)
        table = Table.objects.create(event=self.curated, game=game, title='Hidden table', date=self.day)

        self.club.enable_public_games = False
        self.club.save(update_fields=['enable_public_games'])
        self.curated.table_booking_enabled = False
        self.curated.save(update_fields=['table_booking_enabled'])
        page = self.client.get(self.url)
        self.assertContains(page, game.name)
        self.assertContains(page, self.curated.name)
        self.assertNotContains(page, self.live.name)
        self.assertNotContains(page, table.get_absolute_url())

        self.curated.enable_public_games = False
        self.curated.save(update_fields=['enable_public_games'])
        self.assertNotContains(self.client.get(self.url), game.name)
        self.assertNotContains(self.client.get(self.master.get_absolute_url()), self.url)
        self.curated.enable_public_games = True
        self.curated.status = Event.DRAFT
        self.curated.save(update_fields=['enable_public_games', 'status'])
        self.assertNotContains(self.client.get(self.url), game.name)

    def test_live_catalog_matches_event_rules_and_updates_on_inventory_changes(self):
        withdrawn = GameFactory(name='Withdrawn game')
        played = GameFactory(name='Played game')
        active = GameFactory(name='Active game')
        for game in (withdrawn, played, active):
            copy = LocationGame.objects.create(location=self.club, game=game, is_archived=(game != active))
            EventGame.objects.create(event=self.live, game=game, source_location_game=copy)
        Table.objects.create(event=self.live, game=played, title='Planned table', date=self.day)
        # Use the library explicitly even at an external venue.
        self.live.venue_location = LocationFactory()
        self.live.catalog_mode = Event.CATALOG_LOCATION
        self.live.save()
        page = self.client.get(self.url)
        self.assertEqual([entry['game'] for entry in page.context['entries']], list(effective_catalog(self.live)))
        self.assertContains(page, active.name)
        self.assertContains(page, played.name)
        self.assertNotContains(page, withdrawn.name)
        LocationGame.objects.filter(location=self.club, game=active).update(is_archived=True)
        self.assertNotContains(self.client.get(self.url), active.name)

    def test_catalog_inherits_manifestation_draft_permissions(self):
        self.master.status = Event.DRAFT
        self.master.save(update_fields=['status'])
        game = GameFactory(name='Preview title')
        EventGame.objects.create(event=self.curated, game=game)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        manager = UserProfileFactory().user
        self.master.managers.add(manager.user_profile)
        self.client.force_login(manager)
        self.assertContains(self.client.get(self.url), game.name)
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        reviewer = UserProfileFactory(user__is_staff=True).user
        reviewer.user_permissions.add(Permission.objects.get(
            content_type__app_label='webapp', codename='change_masterevent',
        ))
        self.client.force_login(reviewer)
        self.assertContains(self.client.get(self.url), game.name)

    def test_search_is_case_insensitive_and_pagination_preserves_query(self):
        games = Game.objects.bulk_create([
            Game(name=f'Group {number:02d}', slug=f'test-game-{number}') for number in range(25)
        ])
        LocationGame.objects.bulk_create([LocationGame(location=self.club, game=game) for game in games])
        LocationGame.objects.create(location=self.club, game=GameFactory(name='Other game'))
        page = self.client.get(self.url, {'q': 'group'})
        self.assertEqual(page.context['paginator'].count, 25)
        self.assertContains(page, '?q=group&amp;page=2')
        self.assertNotContains(page, 'Other game')
        self.assertNotContains(page, 'Group 24')
        self.assertContains(self.client.get(self.url, {'q': 'group', 'page': 2}), 'Group 24')
        self.assertEqual(self.client.get(self.url, {'q': '  GrOuP 24  '}).context['paginator'].count, 1)
