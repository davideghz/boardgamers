import json
from datetime import date, time, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import (
    Event, EventGame, EventParticipant, EventParticipantDate, MasterEvent, Player, Sponsor, Table,
)
from webapp.services.event_attendance import attendance_by_day, select_event_days
from webapp.services.profile_merge import merge_accounts


class LegacyEventMappingTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory()
        cls.organizer = LocationFactory(creator=cls.owner)
        cls.venue = LocationFactory()
        cls.sponsor_location = LocationFactory(name='Legacy sponsor', website='https://example.org/publisher')
        cls.event = Event.objects.create(name='Historic Tournament', status=Event.PUBLISHED, creator=cls.owner,
                                         enable_public_games=True, address='Historic address', city='Vicenza')
        # Slugs already stored in incoming links may differ from the current title.
        Event.objects.filter(pk=cls.event.pk).update(slug='original-tournament-url')
        cls.event.refresh_from_db()
        cls.event.sponsor_locations.add(cls.sponsor_location)
        cls.day = date(2024, 6, 7)
        cls.date = cls.event.dates.create(date=cls.day, opening_time=time(9), closing_time=time(18))
        cls.table = Table.objects.create(event=cls.event, date=cls.day, title='Original session')
        cls.booking = Player.objects.create(table=cls.table, user_profile=cls.owner)
        cls.participant, _ = EventParticipant.objects.get_or_create(event=cls.event, user_profile=cls.owner)
        cls.undated = EventParticipant.objects.create(event=cls.event, user_profile=UserProfileFactory())
        cls.game = EventGame.objects.create(event=cls.event, game=GameFactory(name='Historical game'))
        cls.game.sponsor_locations.add(cls.sponsor_location)
        cls.master = MasterEvent.objects.create(name='Historic Festival', description='Historical programme',
                                                venue_location=cls.venue)
        cls.master.dates.create(date=cls.day)
        cls.admin = UserProfileFactory(user__is_staff=True, user__is_superuser=True).user

    def run_mapping(self, *flags, rows=None):
        output = StringIO()
        with TemporaryDirectory() as directory:
            mapping = Path(directory) / 'mapping.json'
            mapping.write_text(json.dumps({'events': rows if rows is not None else [self.row()]}), encoding='utf-8')
            call_command('map_legacy_events', str(mapping), *flags, stdout=output)
        return output.getvalue()

    def row(self, event=None, **overrides):
        event = event or self.event
        mapping = {
            'organizer_location_id': self.organizer.pk, 'venue_location_id': self.venue.pk,
            'classification': 'master_child', 'master_slug': self.master.slug, **overrides,
        }
        return {'event_id': event.pk, 'slug': event.slug, 'mapping': mapping}

    def test_dry_run_and_reapplication_preserve_history(self):
        self.master.approve(self.admin)
        url = self.event.get_absolute_url()
        table_url = self.table.get_absolute_url()
        self.assertContains(self.client.get(url), self.event.name)
        self.assertIn('Dry run: 1 assignment', self.run_mapping('--require-complete'))
        self.event.refresh_from_db()
        self.assertIsNone(self.event.organizer_location_id)
        self.assertFalse(self.master.sponsors.exists())
        self.assertFalse(EventParticipantDate.objects.exists())
        self.assertIn('Applied: 1 assignment', self.run_mapping('--apply', '--require-complete'))
        self.assertIn('0 assignment(s), 1 already assigned', self.run_mapping('--apply', '--require-complete'))

        self.event.refresh_from_db()
        self.assertEqual(self.event.get_absolute_url(), url)
        self.assertEqual(self.event.status, Event.PUBLISHED)
        self.assertEqual(self.event.master_event, self.master)
        self.assertEqual(self.event.venue_location, self.venue)
        self.assertEqual(self.event.organizer_location, self.organizer)
        self.assertEqual(self.event.address, 'Historic address')
        self.assertEqual(self.event.catalog_mode, Event.CATALOG_SELECTED)
        self.assertEqual(list(self.event.dates.all()), [self.date])
        self.assertEqual(self.event.tables.get().get_absolute_url(), table_url)
        self.assertEqual(self.event.tables.get().player_set.get(), self.booking)
        self.assertEqual(self.event.games.get(), self.game)
        self.assertEqual(self.game.sponsor_locations.get(), self.sponsor_location)
        self.assertEqual(self.master.sponsors.get().location, self.sponsor_location)
        self.assertEqual(Sponsor.objects.filter(location=self.sponsor_location).count(), 1)
        self.assertTrue(self.event.participants.filter(pk=self.undated.pk).exists())
        self.assertFalse(self.undated.selected_dates.exists())
        self.assertTrue(self.participant.selected_dates.get(event_date=self.date).inferred_from_booking)
        self.assertContains(self.client.get(url), self.master.get_absolute_url())
        self.assertContains(self.client.get(table_url), 'Original session')
        self.client.force_login(self.owner.user)
        roster = self.client.get(reverse('event-manage-participants', args=[self.event.slug]))
        self.assertContains(roster, gettext('From a booking'))
        self.assertContains(roster, gettext('No dates selected'))
        self.assertEqual(attendance_by_day([self.event])[self.day], {('profile', self.owner.pk)})
        self.booking.delete()
        self.assertFalse(attendance_by_day([self.event]))
        # Still registered: without the booking they only lose their day.
        self.assertEqual(self.client.get(url).context['participant_count'], 2)

    def test_output_lists_who_loses_access_to_the_event(self):
        self.master.approve(self.admin)
        creator, manager, table_creator, staff = [UserProfileFactory() for _ in range(4)]
        self.event.creator = creator
        self.event.save(update_fields=['creator'])
        self.organizer.managers.add(staff)
        self.event.managers.add(manager, staff, self.owner, self.admin.user_profile)
        self.event.allowed_table_creators.add(table_creator, manager, staff)
        expected = [
            f'    Can no longer manage the event: {creator.nickname} (#{creator.pk}), {manager.nickname} (#{manager.pk})',
            f'    Can no longer create tables: {table_creator.nickname} (#{table_creator.pk})',
        ]
        for flags in ((), ('--apply',)):
            with self.subTest(flags=flags):
                lines = self.run_mapping(*flags).splitlines()
                self.assertEqual([line for line in lines if 'Can no longer' in line], expected)

    def test_validation_rejects_unapproved_calendar_or_partial_batch(self):
        with self.assertRaisesMessage(CommandError, 'admin-approved'):
            self.run_mapping('--apply')
        self.master.approve(self.admin)
        broken = Event.objects.create(name='Unexpected session')
        table = Table.objects.create(event=broken, date=self.day, title='Outside the calendar')
        row = self.row(broken, classification='standalone', master_slug=None)
        with self.assertRaisesMessage(CommandError, f'Tables outside the event calendar: #{table.pk}'):
            self.run_mapping('--apply', rows=[self.row(), row])
        self.assertIn(f'Events missing from the mapping: [{broken.pk}]', self.run_mapping())
        with self.assertRaisesMessage(CommandError, 'Events missing from the mapping'):
            self.run_mapping('--apply', '--require-complete')
        self.event.refresh_from_db()
        self.assertIsNone(self.event.organizer_location_id)
        self.assertFalse(self.master.sponsors.exists())
        self.assertFalse(self.participant.selected_dates.exists())

    def test_mapping_a_standalone_event_and_rejecting_different_assignments(self):
        row = self.row(classification='standalone', master_slug=None)
        del row['mapping']['venue_location_id']
        self.run_mapping('--apply', rows=[row])
        self.event.refresh_from_db()
        self.assertIsNone(self.event.master_event_id)
        self.assertEqual(self.event.organizer_location, self.organizer)
        self.assertEqual(self.event.address, 'Historic address')
        self.assertTrue(self.event.is_published)
        self.assertFalse(Sponsor.objects.exists())
        changed = self.row(classification='standalone', master_slug=None, organizer_location_id=self.venue.pk)
        with self.assertRaisesMessage(CommandError, 'already been assigned with different values'):
            self.run_mapping('--apply', rows=[changed])

    def test_mapping_checks_slug_and_child_dates(self):
        with self.assertRaisesMessage(CommandError, 'slug changed since the audit'):
            self.run_mapping('--apply', rows=[{**self.row(), 'slug': 'changed'}])
        late = self.day + timedelta(days=2)
        self.event.dates.create(date=late)
        self.master.approve(self.admin)
        with self.assertRaisesMessage(CommandError, f'Days outside the manifestation calendar: {late.isoformat()}'):
            self.run_mapping('--apply')
        self.event.refresh_from_db()
        self.assertIsNone(self.event.master_event_id)

    def test_explicit_dates_win_and_old_sponsor_links_are_reused(self):
        self.master.approve(self.admin)
        other = Event.objects.create(name='Another historic event')
        other.dates.create(date=self.day)
        other.sponsor_locations.add(self.sponsor_location)
        selection = EventParticipantDate.objects.create(participant=self.participant, event_date=self.date)
        existing_sponsor = Sponsor.objects.create(location=self.sponsor_location, name='Existing sponsor')
        self.run_mapping('--apply', rows=[self.row(), self.row(other)])
        selection.refresh_from_db()
        self.assertFalse(selection.inferred_from_booking)
        self.assertEqual(self.master.sponsors.get(), existing_sponsor)
        self.assertEqual(Sponsor.objects.filter(location=self.sponsor_location).count(), 1)

    def test_selecting_a_reconstructed_day_makes_it_explicit(self):
        today = timezone.localdate()
        future = Event.objects.create(name='Previously scheduled', organizer_location=self.organizer)
        first = future.dates.create(date=today + timedelta(days=1))
        second = future.dates.create(date=today + timedelta(days=2))
        participant = EventParticipant.objects.create(event=future, user_profile=self.owner)
        old = EventParticipantDate.objects.create(participant=participant, event_date=first, inferred_from_booking=True)
        self.client.force_login(self.owner.user)
        self.assertNotIn(first.pk, self.client.get(future.get_absolute_url()).context['selected_days'])
        select_event_days(future, self.owner, [second.pk])
        self.assertTrue(participant.selected_dates.filter(pk=old.pk, inferred_from_booking=True).exists())
        select_event_days(future, self.owner, [first.pk])
        old.refresh_from_db()
        self.assertFalse(old.inferred_from_booking)
        self.assertFalse(participant.selected_dates.filter(event_date=second).exists())

    def test_merging_profiles_keeps_inferred_evidence_and_prefers_an_explicit_choice(self):
        self.owner.user.set_password('local-merge-password')
        self.owner.user.save(update_fields=['password'])
        duplicate = UserProfileFactory()
        incoming = EventParticipant.objects.create(event=self.event, user_profile=duplicate)
        second = self.event.dates.create(date=self.day + timedelta(days=2))
        EventParticipantDate.objects.create(participant=self.participant, event_date=self.date, inferred_from_booking=True)
        EventParticipantDate.objects.create(participant=incoming, event_date=self.date)
        EventParticipantDate.objects.create(participant=incoming, event_date=second, inferred_from_booking=True)
        merge_accounts(self.owner.pk, duplicate.pk)
        self.assertFalse(self.participant.selected_dates.get(event_date=self.date).inferred_from_booking)
        self.assertTrue(self.participant.selected_dates.get(event_date=second).inferred_from_booking)
