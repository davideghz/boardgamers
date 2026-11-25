from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventParticipant, EventParticipantDate, Player, Table


class AccountActivitiesTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.club = LocationFactory(creator=self.profile)
        self.venue = LocationFactory()
        self.today = timezone.localdate()
        self.event = Event.objects.create(name='Fiera di giochi', organizer_location=self.club,
                                          venue_location=self.venue, status=Event.PUBLISHED)
        self.url = reverse('account-activities')

    def test_activities_follow_selected_or_booked_dates(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)
        first = self.today - timedelta(days=1)
        later = self.today + timedelta(days=2)
        EventDate.objects.create(event=self.event, date=self.today, opening_time=time(17))
        selected = EventDate.objects.create(event=self.event, date=later, opening_time=time(17))
        EventDate.objects.create(event=self.event, date=first, opening_time=time(17))
        participant = EventParticipant.objects.create(event=self.event, user_profile=self.profile)
        EventParticipantDate.objects.create(participant=participant, event_date=selected)
        past = Table.objects.create(event=self.event, date=first, time=time(19))
        Player.objects.create(table=past, user_profile=self.profile)
        Table.objects.create(location=self.club, author=self.profile, date=self.today)
        self.client.force_login(self.profile.user)
        upcoming = self.client.get(self.url).context['items']
        self.assertEqual(upcoming, [('event', self.event)])
        self.assertEqual(upcoming[0][1].matching_date, later)
        self.assertEqual(self.client.get(self.url, {'tab': 'past'}).context['items'],
                         [('table', past), ('event', self.event)])
        self.assertEqual(self.client.get(self.url, {'location': self.club.slug}).context['items'], [])
        self.assertEqual(self.client.get(self.url, {'location': self.venue.slug}).context['items'], upcoming)
        participant.delete()
        self.assertEqual(self.client.get(self.url).context['items'], [])
        self.assertEqual(self.client.get(self.url, {'tab': 'past', 'type': 'events'}).context['items'],
                         [('event', self.event)])

    def test_only_visible_registrations_and_bookings_are_listed(self):
        draft = Event.objects.create(name='Riservato', organizer_location=self.venue)
        date = EventDate.objects.create(event=draft, date=self.today)
        Player.objects.create(table=Table.objects.create(event=draft, date=date.date), user_profile=self.profile)
        legacy = Event.objects.create(name='Storico', status=Event.PUBLISHED)
        EventParticipant.objects.create(event=legacy, user_profile=self.profile)
        self.client.force_login(self.profile.user)
        self.assertEqual(self.client.get(self.url).context['items'], [('event', legacy)])
        self.assertEqual(self.client.get(self.url, {'tab': 'past'}).context['items'], [])

    def test_undated_registrations_follow_the_event_days(self):
        def registered_event(name, *offsets):
            event = Event.objects.create(name=name, status=Event.PUBLISHED)
            for offset in offsets:
                EventDate.objects.create(event=event, date=self.today + timedelta(days=offset))
            EventParticipant.objects.create(event=event, user_profile=self.profile)
            return event

        over = registered_event('Over', -10, -9)
        ongoing = registered_event('Ongoing', -1, 1, 2)
        upcoming = registered_event('Upcoming', 5, 6)
        no_days = registered_event('No days')
        self.client.force_login(self.profile.user)

        results = self.client.get(self.url).context['items']
        self.assertEqual(results, [('event', ongoing), ('event', upcoming), ('event', no_days)])
        self.assertEqual([item.matching_date for _, item in results],
                         [self.today + timedelta(days=1), self.today + timedelta(days=5), None])
        past = self.client.get(self.url, {'tab': 'past'}).context['items']
        self.assertEqual(past, [('event', over)])
        self.assertEqual(past[0][1].matching_date, self.today - timedelta(days=9))

    def test_registration_survives_the_cancellation_of_the_booking_it_was_dated_from(self):
        booked = EventDate.objects.create(event=self.event, date=self.today + timedelta(days=1))
        participant = EventParticipant.objects.create(event=self.event, user_profile=self.profile)
        EventParticipantDate.objects.create(participant=participant, event_date=booked, inferred_from_booking=True)
        self.client.force_login(self.profile.user)
        self.assertEqual(self.client.get(self.url).context['items'], [('event', self.event)])
        self.assertEqual(self.client.get(self.url, {'tab': 'past'}).context['items'], [])

    def test_booking_does_not_duplicate_event_or_replace_explicit_attendance(self):
        booked = EventDate.objects.create(event=self.event, date=self.today, opening_time=time(14))
        selected = EventDate.objects.create(event=self.event, date=self.today + timedelta(days=2))
        participant = EventParticipant.objects.create(event=self.event, user_profile=self.profile)
        EventParticipantDate.objects.create(participant=participant, event_date=booked, inferred_from_booking=True)
        EventParticipantDate.objects.create(participant=participant, event_date=selected)
        tables = [Table.objects.create(event=self.event, date=booked.date, time=time(hour)) for hour in (15, 18)]
        players = [Player.objects.create(table=table, user_profile=self.profile) for table in tables]
        self.client.force_login(self.profile.user)

        results = self.client.get(self.url).context['items']
        self.assertEqual(results, [('event', self.event), ('table', tables[0]), ('table', tables[1])])
        self.assertEqual(results[0][1].matching_date, booked.date)
        for player in players:
            player.delete()
        results = self.client.get(self.url).context['items']
        self.assertEqual(results, [('event', self.event)])
        self.assertEqual(results[0][1].matching_date, selected.date)

    def test_another_profiles_bookings_do_not_populate_results_or_venue_filter(self):
        other = UserProfileFactory()
        day = EventDate.objects.create(event=self.event, date=self.today)
        participant = EventParticipant.objects.create(event=self.event, user_profile=other)
        EventParticipantDate.objects.create(participant=participant, event_date=day)
        table = Table.objects.create(title='Private booking', event=self.event, date=day.date)
        Player.objects.create(table=table, user_profile=other)
        self.client.force_login(self.profile.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context['items'], [])
        self.assertQuerySetEqual(response.context['locations'], [])
        self.assertNotContains(response, table.title)

        self.client.force_login(other.user)
        response = self.client.get(self.url, {'type': 'tables', 'q': 'booking'})
        self.assertEqual(response.context['items'], [('table', table)])
        self.assertQuerySetEqual(response.context['locations'], [self.venue])
        self.assertContains(response, table.get_absolute_url())

    def test_visible_navigation_and_pagination_keep_the_filters(self):
        for index in range(16):
            table = Table.objects.create(title=f'Selected session {index}', location=self.venue, date=self.today)
            Player.objects.create(table=table, user_profile=self.profile)
        self.client.force_login(self.profile.user)
        account = self.client.get(reverse('account-index'))
        self.assertContains(account, f'href="{self.url}"', count=3)
        filters = {'type': 'tables', 'location': self.venue.slug, 'q': 'Selected'}
        first = self.client.get(self.url, filters)
        second = self.client.get(self.url, {**filters, 'page': 2})
        self.assertEqual(len(first.context['items']), 15)
        self.assertEqual(len(second.context['items']), 1)
        self.assertTrue(set(first.context['items']).isdisjoint(second.context['items']))
        self.assertContains(first, f'type=tables&amp;location={self.venue.slug}&amp;q=Selected&amp;page=2')
