from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventParticipant, EventParticipantDate, GuestProfile, Player, Table
from webapp.services.event_attendance import attendance_by_day
from webapp.services.profile_merge import merge_accounts


class EventDailyAttendanceTest(TestCase):
    def test_independent_sources_and_foreign_dates(self):
        club = LocationFactory()
        profile = UserProfileFactory()
        event = Event.objects.create(name='Serate', organizer_location=club, status=Event.PUBLISHED)
        day = timezone.localdate() + timedelta(days=2)
        first = EventDate.objects.create(event=event, date=day)
        second = EventDate.objects.create(event=event, date=day + timedelta(days=2))
        foreign = EventDate.objects.create(event=Event.objects.create(name='Other'), date=day)
        table = Table.objects.create(event=event, date=day)
        player = Player.objects.create(user_profile=profile, table=table)
        self.assertFalse(event.participants.exists())
        self.client.force_login(profile.user)
        url = reverse('event-join', args=[event.slug])
        self.client.post(url, {'days': [first.pk, foreign.pk]})
        self.assertFalse(event.participants.exists())
        self.client.post(url, {'days': [first.pk, second.pk]})
        self.client.post(url, {'days': [first.pk, second.pk]})
        self.assertEqual(EventParticipantDate.objects.count(), 2)
        with self.assertRaises(ValidationError):
            EventParticipantDate.objects.create(participant=event.participants.get(), event_date=foreign)
        self.assertEqual([len(v) for v in attendance_by_day([event]).values()], [1, 1])
        player.delete()
        self.assertEqual(len(attendance_by_day([event])), 2)
        Player.objects.create(table=table, user_profile=profile)
        self.client.post(reverse('event-leave', args=[event.slug]))
        self.assertEqual(dict(attendance_by_day([event])), {day: {('profile', profile.pk)}})

    def test_day_selection_uses_one_form_and_keeps_earlier_days_when_updating(self):
        club = LocationFactory()
        visitor = UserProfileFactory(preferred_language='it')
        event = Event.objects.create(name='Weekend', organizer_location=club, status=Event.PUBLISHED)
        today = timezone.localdate()
        previous, first, last = [EventDate.objects.create(event=event, date=today + timedelta(days=offset))
                                 for offset in (-1, 1, 3)]
        participant = EventParticipant.objects.create(event=event, user_profile=visitor)
        for date in (previous, first):
            EventParticipantDate.objects.create(participant=participant, event_date=date)
        self.client.force_login(visitor.user)

        detail = self.client.get(event.get_absolute_url())
        join = reverse('event-join', args=[event.slug])
        self.assertContains(detail, f'action="{join}"', count=1)
        self.assertContains(detail, 'name="days"', count=2)
        self.assertEqual(detail.context['selected_days'], {previous.pk, first.pk})
        self.client.post(join, {'days': [previous.pk]})
        self.assertCountEqual(participant.selected_dates.values_list('event_date_id', flat=True), [previous.pk, first.pk])
        self.client.post(join, {'days': [last.pk]})
        self.assertCountEqual(participant.selected_dates.values_list('event_date_id', flat=True), [previous.pk, last.pk])

    def test_manager_sees_daily_totals_and_undated_registrations(self):
        manager = UserProfileFactory(preferred_language='it')
        visitor = UserProfileFactory()
        club = LocationFactory(creator=manager)
        event = Event.objects.create(name='Meetup', organizer_location=club, status=Event.PUBLISHED)
        day = EventDate.objects.create(event=event, date=timezone.localdate() + timedelta(days=2))
        EventParticipant.objects.create(event=event, user_profile=visitor)
        participant = EventParticipant.objects.create(event=event, user_profile=manager)
        EventParticipantDate.objects.create(participant=participant, event_date=day)
        Player.objects.create(user_profile=manager, table=Table.objects.create(event=event, date=day.date))
        self.assertEqual(self.client.get(event.get_absolute_url()).context['participant_count'], 2)
        self.client.force_login(manager.user)
        response = self.client.get(reverse('event-manage-participants', args=[event.slug]))
        self.assertEqual(response.context['daily_counts'], [(day.date, 1)])
        self.assertContains(response, 'Nessuna giornata indicata')
        self.assertContains(response, visitor.nickname)

    def test_selected_day_cannot_be_removed_but_event_can_be_deleted(self):
        event = Event.objects.create(name='Meetup', organizer_location=LocationFactory())
        day = EventDate.objects.create(event=event, date=timezone.localdate() + timedelta(days=1))
        participant = EventParticipant.objects.create(event=event, user_profile=UserProfileFactory())
        EventParticipantDate.objects.create(participant=participant, event_date=day)
        with self.assertRaises(ValidationError), transaction.atomic():
            day.delete()
        day.date += timedelta(days=1)
        with self.assertRaises(ValidationError):
            day.save()
        event.delete()

    def test_merging_duplicate_profiles_keeps_both_sets_of_dates(self):
        event = Event.objects.create(name='Meetup', organizer_location=LocationFactory())
        today = timezone.localdate()
        days = [EventDate.objects.create(event=event, date=today + timedelta(days=offset)) for offset in (1, 3)]
        keeper = UserProfileFactory()
        keeper.user.set_password('keeper-password')
        keeper.user.save(update_fields=['password'])
        duplicate = UserProfileFactory()
        for profile, selected in ((keeper, days[:1]), (duplicate, days)):
            participant = EventParticipant.objects.create(event=event, user_profile=profile)
            for day in selected:
                EventParticipantDate.objects.create(participant=participant, event_date=day)
        merge_accounts(keeper.pk, duplicate.pk)
        self.assertCountEqual(event.participants.get(user_profile=keeper).selected_dates.values_list('event_date', flat=True),
                              [day.pk for day in days])

    def test_private_bookings_are_excluded_from_public_totals_and_guests_are_deduplicated(self):
        manager = UserProfileFactory()
        guest = GuestProfile.objects.create(owner=manager, name='Guest')
        event = Event.objects.create(name='Meetup', organizer_location=LocationFactory(creator=manager),
                                     status=Event.PUBLISHED, table_booking_enabled=False)
        day = EventDate.objects.create(event=event, date=timezone.localdate() + timedelta(days=2))
        for title in ('First table', 'Second table'):
            table = Table.objects.create(event=event, date=day.date, title=title)
            Player.objects.create(table=table, guest_profile=guest)
        self.assertEqual(attendance_by_day([event])[day.date], {('guest', guest.pk)})
        self.assertEqual(self.client.get(event.get_absolute_url()).context['participant_count'], 0)
