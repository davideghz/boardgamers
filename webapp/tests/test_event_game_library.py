import datetime

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory
from webapp.models import Event, EventDate, EventGame, EventGameTag, Table
from webapp.services.event_games import FEATURED_GAMES_LIMIT, featured_games
from webapp.services.games import merge_games


class LibraryTestCase(TestCase):
    def setUp(self):
        translation.activate('en')
        self.addCleanup(translation.deactivate)
        self.today = timezone.localdate()
        self.owner = UserProfileFactory(preferred_language='en')
        self.outsider = UserProfileFactory(preferred_language='en')
        self.event = Event.objects.create(
            name="Con", slug="con", creator=self.owner, status=Event.APPROVED, enable_public_games=True)
        EventDate.objects.create(event=self.event, date=self.today + datetime.timedelta(days=10))
        self.detail_url = reverse('event_detail', kwargs={'slug': self.event.slug})
        self.library_url = reverse('event-games', kwargs={'slug': self.event.slug})
        self.flagged = EventGameTag.objects.create(event=self.event, name="Preview", show_on_event_page=True)
        self.plain = EventGameTag.objects.create(event=self.event, name="Family")

    def entry(self, name, *tags):
        entry = EventGame.objects.create(event=self.event, game=GameFactory(name=name))
        entry.tags.add(*tags)
        return entry

    def table(self, game, days=1, **kwargs):
        return Table.objects.create(
            title=game.name, event=self.event, game=game, author=self.owner,
            date=self.today + datetime.timedelta(days=days), time=datetime.time(20, 0), **kwargs)


class FeaturedGamesTest(LibraryTestCase):
    def test_only_games_with_a_flagged_tag(self):
        self.entry("Featured", self.flagged)
        self.entry("Not featured", self.plain)
        self.entry("Untagged")
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Featured")
        self.assertNotContains(response, "Not featured")
        self.assertNotContains(response, "Untagged")

    def test_game_with_two_flagged_tags_appears_once_with_all_its_tags(self):
        other = EventGameTag.objects.create(event=self.event, name="New", show_on_event_page=True)
        self.entry("Twice", self.flagged, other, self.plain)
        entries = featured_games(self.event)
        self.assertEqual(len(entries), 1)
        response = self.client.get(self.detail_url)
        for name in ("Preview", "New", "Family"):
            self.assertContains(response, name)

    def test_capped_and_see_all_is_always_there(self):
        self.entry("Only one", self.flagged)
        self.assertContains(self.client.get(self.detail_url), "See all")
        for i in range(FEATURED_GAMES_LIMIT + 3):
            self.entry(f"Game {i:02d}", self.flagged)
        response = self.client.get(self.detail_url)
        self.assertEqual(len(response.context['featured_games']), FEATURED_GAMES_LIMIT)
        self.assertContains(response, "See all")

    def test_section_hidden_without_featured_games(self):
        self.entry("Untagged")
        response = self.client.get(self.detail_url)
        self.assertNotContains(response, "Featured games")
        self.assertContains(response, self.library_url)  # the library is still reachable

    def test_no_library_link_when_the_library_is_empty(self):
        self.assertNotContains(self.client.get(self.detail_url), self.library_url)

    def test_game_descriptions_are_not_loaded(self):
        self.entry("Long", self.flagged)
        with CaptureQueriesContext(connection) as ctx:
            featured_games(self.event)
        self.assertFalse([q for q in ctx.captured_queries if '"description"' in q['sql']])

    def test_query_count_does_not_grow_with_the_games(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(self.detail_url)
            return len(ctx)

        location = LocationFactory()
        self.event.sponsor_locations.add(location)
        entry = self.entry("First", self.flagged, self.plain)
        entry.sponsor_locations.add(location)
        self.table(entry.game)
        one_game = count()
        for i in range(FEATURED_GAMES_LIMIT - 1):
            entry = self.entry(f"Game {i:02d}", self.flagged, self.plain)
            entry.sponsor_locations.add(location)
            self.table(entry.game)
        self.assertEqual(count(), one_game)


class BookingIndicatorTest(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.game_entry = self.entry("Catan", self.flagged)
        self.game = self.game_entry.game

    def test_no_tables(self):
        response = self.client.get(self.detail_url)
        self.assertContains(response, "Reservation not needed")
        self.assertNotContains(response, f"game={self.game.pk}")

    def test_link_points_to_the_first_day_with_tables(self):
        self.table(self.game, days=5)
        self.table(self.game, days=3)
        first = (self.today + datetime.timedelta(days=3)).isoformat()
        response = self.client.get(self.detail_url)
        self.assertContains(response, f"?game={self.game.pk}&amp;date={first}")
        self.assertNotContains(response, "Reservation not needed")

    def test_link_finds_the_table_in_the_program(self):
        table = self.table(self.game, days=5)
        program = reverse('event-program', kwargs={'slug': self.event.slug})
        date = table.date.isoformat()
        response = self.client.get(f"{program}?game={self.game.pk}&date={date}")
        self.assertTrue(response.context['has_tables'])

    def test_past_and_closed_tables_do_not_count(self):
        self.table(self.game, days=-1)
        Table.objects.filter(pk=self.table(self.game, days=2).pk).update(status=Table.CLOSED)
        self.assertContains(self.client.get(self.detail_url), "Reservation not needed")

    def test_hidden_once_the_event_is_over(self):
        self.event.dates.all().delete()
        EventDate.objects.create(event=self.event, date=self.today - datetime.timedelta(days=1))
        self.table(self.game, days=1)
        for url in (self.detail_url, self.library_url):
            response = self.client.get(url)
            self.assertNotContains(response, "Reservation not needed")
            self.assertNotContains(response, "See the tables")

    def test_concluded_box_on_the_event_page(self):
        self.event.dates.all().delete()
        EventDate.objects.create(event=self.event, date=self.today - datetime.timedelta(days=1))
        self.assertContains(self.client.get(self.detail_url), "Event concluded")

    def test_game_does_not_link_to_its_site_page(self):
        # Its "back" link leads to the site-wide library, not the event's one.
        self.assertNotContains(
            self.client.get(self.detail_url), reverse('game-detail', kwargs={'slug': self.game.slug}))


class PublicLibraryTest(LibraryTestCase):
    def test_shows_every_game(self):
        self.entry("Tagged", self.plain)
        self.entry("Untagged")
        response = self.client.get(self.library_url)
        self.assertContains(response, "Tagged")
        self.assertContains(response, "Untagged")

    def names(self, **params):
        response = self.client.get(self.library_url, params)
        return [entry.game.name for entry in response.context['entries']]

    def test_filters(self):
        location = LocationFactory()
        self.event.sponsor_locations.add(location)
        self.entry("Azul", self.plain)
        self.entry("Brass").sponsor_locations.add(location)
        self.assertEqual(self.names(), ["Azul", "Brass"])
        self.assertEqual(self.names(q="azu"), ["Azul"])
        self.assertEqual(self.names(tag=self.plain.pk), ["Azul"])
        self.assertEqual(self.names(sponsor=location.pk), ["Brass"])

    def test_bad_or_foreign_filters_are_ignored(self):
        self.entry("Azul")
        other = Event.objects.create(name="Other", slug="other")
        foreign = EventGameTag.objects.create(event=other, name="X")
        self.assertEqual(self.names(tag="nope"), ["Azul"])
        self.assertEqual(self.names(tag=foreign.pk), ["Azul"])

    def test_pagination(self):
        for i in range(17):
            self.entry(f"Game {i:02d}")
        self.assertEqual(len(self.names()), 16)
        self.assertEqual(self.names(page=2), ["Game 16"])

    def test_pending_event_is_private(self):
        self.event.status = Event.PENDING
        self.event.save()
        self.assertEqual(self.client.get(self.library_url).status_code, 404)
        self.client.force_login(self.owner.user)
        self.assertEqual(self.client.get(self.library_url).status_code, 200)


class LibraryFlagTest(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.entry("Azul", self.flagged)
        Event.objects.filter(pk=self.event.pk).update(enable_public_games=False)
        self.event.refresh_from_db()

    def test_off_by_default(self):
        self.assertFalse(Event.objects.create(name="New", slug="new").enable_public_games)

    def test_hidden_from_the_event_page(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.context['featured_games'], [])
        self.assertNotContains(response, "Azul")
        self.assertNotContains(response, self.library_url)

    def test_hidden_event_page_runs_no_library_query(self):
        with CaptureQueriesContext(connection) as ctx:
            self.client.get(self.detail_url)
        self.assertFalse([q for q in ctx.captured_queries if 'webapp_eventgame' in q['sql']])

    def test_library_page_is_only_a_preview_for_managers(self):
        self.assertEqual(self.client.get(self.library_url).status_code, 404)
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(self.library_url).status_code, 404)
        self.client.force_login(self.owner.user)
        self.assertEqual(self.client.get(self.library_url).status_code, 200)

    def test_tables_keep_filling_the_library(self):
        game = GameFactory(name="Brass")
        self.table(game)
        self.assertTrue(EventGame.objects.filter(event=self.event, game=game).exists())

    def test_toggle(self):
        url = reverse('event-manage-games-toggle', kwargs={'slug': self.event.slug})
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.post(url, {'enabled': 'on'}).status_code, 403)
        self.event.refresh_from_db()
        self.assertFalse(self.event.enable_public_games)

        self.client.force_login(self.owner.user)
        self.client.post(url, {'enabled': 'on'})
        self.event.refresh_from_db()
        self.assertTrue(self.event.enable_public_games)
        self.assertContains(self.client.get(self.detail_url), "Azul")

        self.client.post(url)
        self.event.refresh_from_db()
        self.assertFalse(self.event.enable_public_games)


class AutomaticAdditionTest(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.game = GameFactory(name="Catan")

    def in_library(self, game=None):
        return EventGame.objects.filter(event=self.event, game=game or self.game).exists()

    def test_new_table_adds_its_game_once(self):
        self.table(self.game)
        self.table(self.game)
        self.assertEqual(EventGame.objects.filter(event=self.event, game=self.game).count(), 1)

    def test_changing_the_game_adds_the_new_one(self):
        table = self.table(self.game)
        other = GameFactory(name="Azul")
        table.game = other
        table.save()
        self.assertTrue(self.in_library(other))
        self.assertTrue(self.in_library())

    def test_removed_game_does_not_come_back_on_a_later_save(self):
        table = Table.objects.get(pk=self.table(self.game).pk)
        EventGame.objects.filter(event=self.event, game=self.game).delete()
        table.title = "Renamed"
        table.save()
        self.assertFalse(self.in_library())

    def test_existing_tags_are_kept(self):
        self.entry("Azul", self.plain)
        entry = EventGame.objects.get(game__name="Azul")
        self.table(entry.game)
        self.assertEqual(list(EventGame.objects.get(pk=entry.pk).tags.all()), [self.plain])

    def test_location_tables_do_not_touch_any_library(self):
        Table.objects.create(
            title="T", location=LocationFactory(), game=self.game, author=self.owner,
            date=self.today, time=datetime.time(20, 0))
        self.assertFalse(EventGame.objects.exists())


class SponsorsAndMergeTest(LibraryTestCase):
    def test_removed_sponsor_leaves_its_games(self):
        kept, removed = LocationFactory(), LocationFactory()
        self.event.sponsor_locations.add(kept, removed)
        entry = self.entry("Azul")
        entry.sponsor_locations.add(kept, removed)
        self.client.force_login(self.owner.user)
        self.client.post(reverse('event-manage-location-remove', kwargs={'slug': self.event.slug, 'pk': removed.pk}))
        self.assertEqual(list(entry.sponsor_locations.all()), [kept])

    def test_merge_moves_entries(self):
        duplicate = self.entry("Dup", self.plain).game
        keeper = GameFactory(name="Keeper")
        result = merge_games(keeper, duplicate, {})
        self.assertEqual(result.event_library_moved, 1)
        self.assertEqual(list(EventGame.objects.get(event=self.event).tags.all()), [self.plain])
        self.assertEqual(EventGame.objects.get(event=self.event).game, keeper)

    def test_merge_folds_entries_of_the_same_event(self):
        location = LocationFactory()
        kept = self.entry("Keeper", self.flagged)
        dup = self.entry("Dup", self.plain)
        dup.sponsor_locations.add(location)
        result = merge_games(kept.game, dup.game, {})
        self.assertEqual(result.event_library_merged, 1)
        entry = EventGame.objects.get(event=self.event)
        self.assertEqual(entry.pk, kept.pk)
        self.assertEqual(set(entry.tags.all()), {self.flagged, self.plain})
        self.assertEqual(list(entry.sponsor_locations.all()), [location])


class ManageLibraryTest(LibraryTestCase):
    def setUp(self):
        super().setUp()
        self.slug = {'slug': self.event.slug}
        self.add_url = reverse('event-manage-game-add', kwargs=self.slug)
        self.client.force_login(self.owner.user)

    def test_outsider_is_refused_everywhere(self):
        entry = self.entry("Azul")
        self.client.force_login(self.outsider.user)
        urls = [
            self.add_url,
            reverse('event-manage-game-delete', kwargs={**self.slug, 'game_uuid': entry.uuid}),
            reverse('event-manage-game-tag-add', kwargs=self.slug),
            reverse('event-manage-game-tag-delete', kwargs={**self.slug, 'pk': self.plain.pk}),
            reverse('event-manage-game-tags-reorder', kwargs=self.slug),
        ]
        for url in urls:
            self.assertEqual(self.client.post(url, {'game': GameFactory(name="X").pk, 'name': 'X'}).status_code, 403)
        self.assertEqual(EventGame.objects.filter(event=self.event).count(), 1)
        self.assertEqual(self.event.game_tags.count(), 2)

    def test_add_with_tags_and_sponsors(self):
        location = LocationFactory()
        self.event.sponsor_locations.add(location)
        game = GameFactory(name="Azul")
        response = self.client.post(self.add_url, {
            'game': game.pk, 'tags': [self.plain.pk], 'sponsor_locations': [location.pk]})
        self.assertRedirects(response, reverse('event-manage-games', kwargs=self.slug), fetch_redirect_response=False)
        entry = EventGame.objects.get(event=self.event, game=game)
        self.assertEqual(list(entry.tags.all()), [self.plain])
        self.assertEqual(list(entry.sponsor_locations.all()), [location])

    def test_save_and_add_another(self):
        response = self.client.post(self.add_url, {'game': GameFactory(name="Azul").pk, 'add_another': '1'})
        self.assertRedirects(response, self.add_url, fetch_redirect_response=False)

    def test_same_game_twice_is_refused(self):
        entry = self.entry("Azul")
        response = self.client.post(self.add_url, {'game': entry.game.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(EventGame.objects.filter(event=self.event).count(), 1)

    def test_duplicate_error_is_shown_when_editing(self):
        entry, other = self.entry("Azul"), self.entry("Brass")
        url = reverse('event-manage-game-detail', kwargs={**self.slug, 'game_uuid': entry.uuid})
        response = self.client.post(url, {'game': other.game.pk})
        self.assertContains(response, "This game is already in the library.")

    def test_only_sponsors_and_tags_of_this_event_are_accepted(self):
        other = Event.objects.create(name="Other", slug="other")
        foreign_tag = EventGameTag.objects.create(event=other, name="X")
        game = GameFactory(name="Azul")
        for data in ({'tags': [foreign_tag.pk]}, {'sponsor_locations': [LocationFactory().pk]}):
            self.assertEqual(self.client.post(self.add_url, {'game': game.pk, **data}).status_code, 200)
        self.assertFalse(EventGame.objects.exists())

    def test_edit_and_delete(self):
        entry = self.entry("Azul", self.plain)
        detail = reverse('event-manage-game-detail', kwargs={**self.slug, 'game_uuid': entry.uuid})
        self.assertEqual(self.client.get(detail).status_code, 200)
        self.client.post(detail, {'game': entry.game.pk, 'tags': [self.flagged.pk]})
        self.assertEqual(list(entry.tags.all()), [self.flagged])
        self.client.post(reverse('event-manage-game-delete', kwargs={**self.slug, 'game_uuid': entry.uuid}))
        self.assertFalse(EventGame.objects.filter(pk=entry.pk).exists())

    def test_entry_of_another_event_is_not_reachable(self):
        other = Event.objects.create(name="Other", slug="other")
        entry = EventGame.objects.create(event=other, game=GameFactory(name="Azul"))
        url = reverse('event-manage-game-delete', kwargs={**self.slug, 'game_uuid': entry.uuid})
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_tag_lifecycle(self):
        add = reverse('event-manage-game-tag-add', kwargs=self.slug)
        self.client.post(add, {'name': 'Italian', 'show_on_event_page': 'on'})
        tag = self.event.game_tags.get(name='Italian')
        self.assertTrue(tag.show_on_event_page)
        self.assertEqual(tag.order, 1)

        self.client.post(add, {'name': 'italian'})  # same name, other case
        self.assertEqual(self.event.game_tags.filter(name__iexact='italian').count(), 1)

        update = reverse('event-manage-game-tag-update', kwargs={**self.slug, 'pk': tag.pk})
        self.client.post(update, {'name': 'Language independent'})
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'Language independent')
        self.assertFalse(tag.show_on_event_page)

        self.client.post(reverse('event-manage-game-tag-delete', kwargs={**self.slug, 'pk': tag.pk}))
        self.assertFalse(self.event.game_tags.filter(pk=tag.pk).exists())

    def test_reorder_only_touches_this_event(self):
        other = Event.objects.create(name="Other", slug="other")
        foreign = EventGameTag.objects.create(event=other, name="X", order=7)
        self.client.post(
            reverse('event-manage-game-tags-reorder', kwargs=self.slug),
            data={'tags': [{'id': self.plain.pk, 'order': 9}, {'id': foreign.pk, 'order': 9}]},
            content_type='application/json')
        self.plain.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(self.plain.order, 9)
        self.assertEqual(foreign.order, 7)

    def test_pages_render(self):
        self.entry("Azul", self.plain)
        for name in ('event-manage-games', 'event-manage-game-add', 'event-manage'):
            self.assertEqual(self.client.get(reverse(name, kwargs=self.slug)).status_code, 200)
