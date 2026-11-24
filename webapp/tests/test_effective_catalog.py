from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.forms import EventGameForm
from webapp.models import Event, EventGame, LocationGame, LocationGameLoan, LocationGameTag, Member
from webapp.services.event_games import effective_catalog
from webapp.services.games import merge_games


class EffectiveCatalogTest(TestCase):
    def setUp(self):
        self.club = LocationFactory(creator=UserProfileFactory())
        self.event = Event.objects.create(name='Serata', organizer_location=self.club, venue_location=self.club,
                                          status=Event.PUBLISHED, enable_public_games=True)
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
        self.assertTrue(entry.is_on_loan)
        self.assertFalse(hasattr(entry, 'loan_due_date'))
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
        self.assertEqual(effective_catalog(self.event).get().game_id, self.game.pk)
        self.event.catalog_mode = Event.CATALOG_LOCATION
        self.assertTrue(self.event.uses_location_library)
        self.assertFalse(effective_catalog(self.event).exists())

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
