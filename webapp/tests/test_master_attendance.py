from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import (
    Event, EventParticipant, EventParticipantDate, GuestProfile, MasterEvent, MasterEventDate,
    MasterEventDateParticipant, Player, Table,
)
from webapp.services.profile_merge import merge_accounts


class MasterAttendanceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.first_person = UserProfileFactory()
        cls.second_person = UserProfileFactory()
        cls.master = MasterEvent.objects.create(name='Festival', status=Event.PUBLISHED)
        cls.day = timezone.localdate() + timedelta(days=2)
        cls.first = MasterEventDate.objects.create(master_event=cls.master, date=cls.day)
        cls.second = MasterEventDate.objects.create(master_event=cls.master, date=cls.day + timedelta(days=2))
        cls.url = reverse('master-event-register', args=[cls.master.slug])
        cls.detail = cls.master.get_absolute_url()

    def register_directly(self, profile, *dates):
        for day in dates:
            MasterEventDateParticipant.objects.create(master_event_date=day, user_profile=profile)

    def test_registration_before_the_program_and_idempotent_updates(self):
        self.assertRedirects(self.client.post(self.url, {'days': self.first.pk}), reverse('login') + f'?next={self.url}')
        self.client.force_login(self.first_person.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        past = MasterEventDate.objects.create(master_event=self.master, date=timezone.localdate() - timedelta(days=1))
        other = MasterEvent.objects.create(name='Other festival')
        foreign_day = MasterEventDate.objects.create(master_event=other, date=self.first.date)
        self.register_directly(self.first_person, past, foreign_day)
        self.register_directly(self.second_person, self.first)

        self.assertContains(self.client.get(self.detail), self.url)
        requested = [self.first.pk, self.second.pk, self.second.pk]
        for _ in range(2):
            self.assertRedirects(self.client.post(self.url, {'days': requested}),
                                 self.detail + '#manifestation-attendance')
        registrations = self.first_person.master_event_registrations
        original = {past.pk, foreign_day.pk, self.first.pk, self.second.pk}
        self.assertEqual(set(registrations.values_list('master_event_date_id', flat=True)), original)
        for invalid in (past.pk, foreign_day.pk, 'invalid'):
            self.client.post(self.url, {'days': [self.first.pk, invalid]})
            self.assertEqual(set(registrations.values_list('master_event_date_id', flat=True)), original)
        self.client.post(self.url, {'days': [self.first.pk]})
        self.assertEqual(set(registrations.values_list('master_event_date_id', flat=True)),
                         {past.pk, foreign_day.pk, self.first.pk})
        self.client.post(self.url, {})
        self.assertEqual(set(registrations.values_list('master_event_date_id', flat=True)), {past.pk, foreign_day.pk})
        self.assertTrue(self.first.participants.filter(user_profile=self.second_person).exists())

    def test_draft_and_ended_manifestations_do_not_accept_registrations(self):
        draft = MasterEvent.objects.create(name='Draft festival')
        draft.managers.add(self.first_person)
        draft_day = MasterEventDate.objects.create(master_event=draft, date=self.day)
        draft_url = reverse('master-event-register', args=[draft.slug])
        self.client.force_login(self.first_person.user)
        self.assertNotContains(self.client.get(draft.get_absolute_url()), draft_url)
        self.assertEqual(self.client.post(draft_url, {'days': draft_day.pk}).status_code, 404)

        ended = MasterEvent.objects.create(name='Ended festival', status=Event.PUBLISHED)
        ended_day = MasterEventDate.objects.create(master_event=ended, date=timezone.localdate() - timedelta(days=1))
        ended_url = reverse('master-event-register', args=[ended.slug])
        self.assertNotContains(self.client.get(ended.get_absolute_url()), ended_url)
        self.assertEqual(self.client.post(ended_url, {'days': ended_day.pk}).status_code, 302)
        self.assertFalse(MasterEventDateParticipant.objects.exists())

    def test_daily_union_and_cancellations_keep_the_sources_independent(self):
        self.register_directly(self.first_person, self.first, self.second)
        named_guest = GuestProfile.objects.create(owner=self.first_person, name='Named guest')
        event = Event.objects.create(
            name='Tournament', organizer_location=LocationFactory(), master_event=self.master, status=Event.PUBLISHED,
        )
        event_date = event.dates.create(date=self.day)
        participant = EventParticipant.objects.create(event=event, user_profile=self.first_person)
        EventParticipantDate.objects.create(participant=participant, event_date=event_date)
        bookings = []
        for title in ('Morning session', 'Evening session'):
            table = Table.objects.create(event=event, date=self.day, title=title, external_players=3)
            bookings.append(Player.objects.create(table=table, user_profile=self.first_person))
            Player.objects.create(table=table, guest_profile=named_guest)
        standalone = Table.objects.create(location=event.organizer_location, date=self.day, title='Standalone')
        Player.objects.create(table=standalone, user_profile=self.second_person)

        page = self.client.get(self.detail)
        self.assertEqual((page.context['unique_people'], page.context['person_days']), (2, 3))
        self.assertEqual([day.expected for day in page.context['days']], [2, 1])
        for booking in bookings:
            booking.delete()
        self.assertEqual(self.client.get(self.detail).context['person_days'], 3)
        self.client.force_login(self.first_person.user)
        self.client.post(self.url, {})
        self.assertTrue(participant.selected_dates.exists())
        page = self.client.get(self.detail)
        self.assertEqual((page.context['unique_people'], page.context['person_days']), (2, 2))

    def test_public_attendance_excludes_draft_events_and_private_table_bookings(self):
        organizer = LocationFactory()
        private_program = Event.objects.create(
            name='Private program', organizer_location=organizer, master_event=self.master,
            status=Event.PUBLISHED, table_booking_enabled=False,
        )
        event_date = private_program.dates.create(date=self.day)
        participant = EventParticipant.objects.create(event=private_program, user_profile=self.first_person)
        EventParticipantDate.objects.create(participant=participant, event_date=event_date)
        table = Table.objects.create(event=private_program, date=self.day, title='Private table')
        Player.objects.create(table=table, user_profile=self.second_person)
        self.assertEqual(self.client.get(self.detail).context['person_days'], 1)
        private_program.status = Event.DRAFT
        private_program.save(update_fields=['status'])
        self.assertEqual(self.client.get(self.detail).context['person_days'], 0)

    def test_registered_dates_are_protected_until_people_cancel(self):
        self.register_directly(self.first_person, self.first)
        self.master.managers.add(self.second_person)
        self.client.force_login(self.second_person.user)
        calendar = reverse('master-event-calendar', args=[self.master.slug])
        self.client.post(calendar, {'remove': self.first.pk})
        self.assertTrue(self.master.dates.filter(pk=self.first.pk).exists())
        with self.assertRaises(ValidationError), transaction.atomic():
            self.master.dates.all().delete()
        self.first.date += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.first.save()

        self.client.force_login(self.first_person.user)
        self.client.post(self.url, {})
        self.client.force_login(self.second_person.user)
        self.client.post(calendar, {'remove': self.first.pk})
        self.assertFalse(self.master.dates.filter(pk=self.first.pk).exists())

    def test_account_merge_keeps_one_registration_per_date(self):
        self.first_person.user.set_password('local-merge-password')
        self.first_person.user.save(update_fields=['password'])
        self.register_directly(self.first_person, self.first)
        self.register_directly(self.second_person, self.first, self.second)
        merge_accounts(self.first_person.pk, self.second_person.pk)
        self.assertCountEqual(
            self.first_person.master_event_registrations.values_list('master_event_date_id', flat=True),
            [self.first.pk, self.second.pk],
        )
