from datetime import time, timedelta

from django.contrib.admin import site
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.forms import EventGameForm
from webapp.models import Event, EventGame, EventGameTag, LocationGame, LocationGameLoan, LocationGameTag, Member, Table
from webapp.services.event_games import catalog_entries, effective_catalog, featured_games
from webapp.services.games import merge_games


class EffectiveCatalogTest(TestCase):
    def setUp(self):
        self.club = LocationFactory(creator=UserProfileFactory())
        self.event = Event.objects.create(name='Serata', organizer_location=self.club, venue_location=self.club,
                                          status=Event.PUBLISHED, enable_public_games=True)
        self.event.dates.create(date=timezone.localdate())
        self.game = GameFactory()
        self.copy = LocationGame.objects.create(location=self.club, game=self.game)
        self.library = reverse('event-games', args=[self.event.slug])

    def test_live_library_tracks_inventory_and_hides_internal_data(self):
        self.copy.notes = 'Private owner address'
        self.copy.save()
        self.copy.tags.add(LocationGameTag.objects.create(location=self.club, name='Private shelf'))
        borrower = Member.objects.create(location=self.club, first_name='Private borrower')
        LocationGameLoan.objects.create(location=self.club, location_game=self.copy, member=borrower,
                                        due_date=timezone.localdate() + timedelta(days=5))
        page = self.client.get(self.library)
        self.assertContains(page, self.game.name)
        self.assertNotContains(page, 'Private shelf')
        self.assertNotContains(page, 'Private owner address')
        self.assertNotContains(page, borrower.first_name)
        entry = page.context['entries'][0]
        self.assertTrue(entry.location_game.is_on_loan)
        self.assertFalse(hasattr(entry.location_game, 'loan_due_date'))
        self.assertFalse(self.event.games.exists())
        self.copy.is_archived = True
        self.copy.save()
        self.assertFalse(effective_catalog(self.event).exists())
        self.club.enable_public_games = False
        self.club.save()
        self.assertEqual(self.client.get(self.library).status_code, 404)

    def test_external_selection_validates_source_and_survives_its_removal(self):
        self.event.venue_location = LocationFactory()
        self.event.save()
        self.assertFalse(self.event.uses_location_library)
        form = EventGameForm({'source_location_game': self.copy.pk}, event=self.event)
        self.assertTrue(form.is_valid(), form.errors)
        entry = form.save()
        other = LocationGame.objects.create(location=self.event.venue_location, game=self.game)
        entry.source_location_game = other
        with self.assertRaises(ValidationError):
            entry.save()
        self.copy.delete()
        entry.refresh_from_db()
        self.assertIsNone(entry.source_location_game_id)
        self.assertEqual(effective_catalog(self.event).get(), self.game)
        self.event.catalog_mode = Event.CATALOG_LOCATION
        self.assertTrue(self.event.uses_location_library)
        self.assertEqual(effective_catalog(self.event).get(), self.game)

    def test_catalog_override_can_be_saved_from_event_management(self):
        selected = GameFactory(name='Event-only title')
        EventGame.objects.create(event=self.event, game=selected)
        self.client.force_login(self.club.creator.user)
        response = self.client.post(reverse('event-manage-data', args=[self.event.slug]), {
            'name': self.event.name, 'description': 'Serata giochi', 'venue_location': self.club.pk,
            'catalog_mode': Event.CATALOG_SELECTED, 'table_booking_enabled': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.catalog_mode, Event.CATALOG_SELECTED)
        self.client.logout()
        catalog = self.client.get(self.library)
        self.assertContains(catalog, selected.name)
        self.assertNotContains(catalog, self.game.name)

    def test_game_detail_links_back_only_when_the_effective_catalog_is_visible(self):
        detail = reverse('game-detail', args=[self.game.slug], query={'from_event': self.event.slug})
        self.assertEqual(self.client.get(detail).context['back_event'], self.event)
        self.club.enable_public_games = False
        self.club.save(update_fields=['enable_public_games'])
        self.assertIsNone(self.client.get(detail).context.get('back_event'))
        self.client.force_login(self.club.creator.user)
        self.assertEqual(self.client.get(detail).context['back_event'], self.event)

    def test_withdrawn_source_is_retained_when_an_existing_selection_is_edited(self):
        entry = EventGame.objects.create(event=self.event, game=self.game, source_location_game=self.copy)
        self.copy.is_archived = True
        self.copy.save(update_fields=['is_archived'])
        data = {'game': self.game.pk, 'source_location_game': self.copy.pk}
        edit = EventGameForm(data, event=self.event, instance=entry)
        self.assertTrue(edit.is_valid(), edit.errors)
        self.assertEqual(edit.save().source_location_game, self.copy)
        add = EventGameForm(data, event=self.event)
        self.assertIn('source_location_game', add.errors)

    def test_combining_duplicate_games_preserves_the_selected_sources(self):
        keeper = GameFactory(name='Preferred title')
        kept_entry = EventGame.objects.create(event=self.event, game=keeper)
        kept_copy = LocationGame.objects.create(location=self.club, game=keeper)
        EventGame.objects.create(event=self.event, game=self.game, source_location_game=self.copy)

        merge_games(keeper, self.game, {})

        kept_entry.refresh_from_db()
        self.assertEqual(kept_entry.source_location_game, kept_copy)

    def test_live_catalog_includes_the_games_of_the_event_tables(self):
        brought = GameFactory(name='Brought by a player')
        Table.objects.create(title='Tavolo', event=self.event, game=brought, author=self.club.creator,
                             date=timezone.localdate(), time=time(20))
        self.assertCountEqual(effective_catalog(self.event), [self.game, brought])
        entry = next(e for e in self.client.get(self.library).context['entries'] if e.game == brought)
        self.assertIsNone(entry.location_game)
        self.assertEqual(entry.first_table_date, timezone.localdate())

    def test_withdrawn_title_stays_out_unless_a_table_plays_it(self):
        EventGame.objects.create(event=self.event, game=self.game)
        self.copy.is_archived = True
        self.copy.save()
        self.assertFalse(effective_catalog(self.event).exists())
        Table.objects.create(title='Tavolo', event=self.event, game=self.game, author=self.club.creator,
                             date=timezone.localdate(), time=time(20))
        self.assertEqual(effective_catalog(self.event).get(), self.game)
        self.assertIsNone(catalog_entries(self.event, [self.game])[0].location_game)

    def test_live_catalog_features_and_filters_by_event_tag(self):
        self.assertEqual(featured_games(self.event), [])
        tag = EventGameTag.objects.create(event=self.event, name='Highlights', show_on_event_page=True)
        extra = GameFactory(name='Extra')
        for game in (self.game, extra):
            EventGame.objects.create(event=self.event, game=game).tags.add(tag)
        LocationGame.objects.create(location=self.club, game=GameFactory())
        self.assertCountEqual([entry.game for entry in featured_games(self.event)], [self.game, extra])
        page = self.client.get(self.library, {'tag': tag.pk})
        self.assertCountEqual([entry.game for entry in page.context['entries']], [self.game, extra])

    def test_titles_must_be_brought_to_an_external_venue(self):
        at_club, to_bring = gettext('At the association'), gettext('To be brought')
        self.assertContains(self.client.get(self.library), at_club)
        self.event.venue_location = LocationFactory()
        self.event.catalog_mode = Event.CATALOG_LOCATION
        self.event.save()
        page = self.client.get(self.library)
        self.assertContains(page, to_bring)
        self.assertNotContains(page, at_club)

    def test_the_changed_field_wins_when_editing_a_selection(self):
        other = GameFactory()
        other_copy = LocationGame.objects.create(location=self.club, game=other)
        entry = EventGame.objects.create(event=self.event, game=self.game, source_location_game=self.copy)
        form = EventGameForm({'game': self.game.pk, 'source_location_game': other_copy.pk},
                             event=self.event, instance=entry)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        entry.refresh_from_db()
        self.assertEqual((entry.game, entry.source_location_game), (other, other_copy))
        form = EventGameForm({'game': self.game.pk, 'source_location_game': other_copy.pk},
                             event=self.event, instance=entry)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        entry.refresh_from_db()
        self.assertEqual((entry.game, entry.source_location_game), (self.game, None))

    def test_mismatch_keeps_the_picked_game_in_the_form(self):
        self.client.force_login(self.club.creator.user)
        picked = GameFactory(name='Picked title')
        page = self.client.post(reverse('event-manage-game-add', args=[self.event.slug]),
                                {'game': picked.pk, 'source_location_game': self.copy.pk})
        self.assertContains(page, f'value="{picked.pk}"')
        self.assertContains(page, picked.name)
        self.assertFalse(self.event.games.exists())

    def test_changing_the_organizer_clears_the_sources(self):
        entry = EventGame.objects.create(event=self.event, game=self.game, source_location_game=self.copy)
        self.event.save()
        entry.refresh_from_db()
        self.assertEqual(entry.source_location_game, self.copy)
        self.event.organizer_location = None
        self.event.save()
        entry = EventGame.objects.get(pk=entry.pk)
        self.assertIsNone(entry.source_location_game)
        # A source left behind by other means does not break the form.
        EventGame.objects.filter(pk=entry.pk).update(source_location_game=self.copy)
        entry = EventGame.objects.get(pk=entry.pk)
        form = EventGameForm({'game': self.game.pk}, event=Event.objects.get(pk=self.event.pk), instance=entry)
        self.assertTrue(form.is_valid(), form.errors)

    def test_manage_index_counts_the_effective_catalog(self):
        self.client.force_login(self.club.creator.user)
        page = self.client.get(reverse('event-manage', args=[self.event.slug]))
        self.assertEqual(page.context['catalog_count'], 1)

    def test_admin_searches_the_source_titles(self):
        self.assertIn('source_location_game', site.get_model_admin(EventGame).autocomplete_fields)
