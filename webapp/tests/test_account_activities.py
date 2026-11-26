from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventParticipant, EventParticipantDate, Player, Table
from webapp.tests.test_location_table_access import italian


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
        # Created without a seat: still the user's, since My tables lives here (E5)
        created = Table.objects.create(location=self.club, author=self.profile, date=self.today)
        self.client.force_login(self.profile.user)
        upcoming = self.client.get(self.url).context['items']
        self.assertEqual(upcoming, [('table', created), ('event', self.event)])
        self.assertEqual(upcoming[1][1].matching_date, later)
        self.assertEqual(self.client.get(self.url, {'tab': 'past'}).context['items'],
                         [('table', past), ('event', self.event)])
        self.assertEqual(self.client.get(self.url, {'location': self.club.slug}).context['items'], [('table', created)])
        self.assertEqual(self.client.get(self.url, {'location': self.venue.slug}).context['items'], upcoming[1:])
        participant.delete()
        self.assertEqual(self.client.get(self.url).context['items'], [('table', created)])
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
        self.assertEqual(response.context['location_filter_items'], [])
        self.assertNotContains(response, table.title)

        self.client.force_login(other.user)
        response = self.client.get(self.url, {'type': 'tables', 'q': 'booking'})
        self.assertEqual(response.context['items'], [('table', table)])
        self.assertEqual([item['slug'] for item in response.context['location_filter_items']], [self.venue.slug])
        self.assertContains(response, table.get_absolute_url())

    def test_null_characters_in_the_filters_are_ignored(self):
        self.client.force_login(self.profile.user)
        for url in (self.url, reverse('table-index')):
            for name in ('q', 'location'):
                with self.subTest(url=url, name=name):
                    self.assertEqual(self.client.get(url, {name: 'a\x00'}).status_code, 200)

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


class MyTablesInMyActivitiesTest(TestCase):
    """E5: My tables is the "Organized by me" view of My activities, with row actions."""

    def setUp(self):
        self.profile = UserProfileFactory()
        self.other = UserProfileFactory()
        self.club = LocationFactory(name='Circolo')
        today = timezone.localdate()
        self.created = Table.objects.create(title='Creato da me', location=self.club, author=self.profile,
                                            date=today + timedelta(days=1), time=time(21))
        self.joined = Table.objects.create(title='Mi siedo', location=self.club, author=self.other,
                                           date=today + timedelta(days=2), time=time(21))
        Player.objects.create(table=self.joined, user_profile=self.profile)
        self.url = reverse('account-activities')
        self.client.force_login(self.profile.user)

    def test_account_tables_redirects_keeping_its_filters(self):
        response = self.client.get(reverse('account-tables'), {'tab': 'past', 'q': 'Azul', 'location': 'circolo'})
        self.assertRedirects(
            response, f'{self.url}?type=tables&role=organizer&tab=past&q=Azul&location=circolo',
            fetch_redirect_response=False)

    def test_organized_by_me(self):
        response = self.client.get(self.url, {'role': 'organizer'})
        self.assertEqual(response.context['items'], [('table', self.created)])
        self.assertContains(response, 'name="role" value="organizer" checked')
        self.assertIn((italian('Organized by me'), '?'), [(str(label), url) for label, url in response.context['active_filters']])

        everything = self.client.get(self.url).context['items']
        self.assertEqual(everything, [('table', self.created), ('table', self.joined)])

    def test_created_tables_offer_edit_and_duplicate_and_seats_say_youre_in(self):
        response = self.client.get(self.url)
        edit = reverse('location-table-update', args=[self.club.slug, self.created.slug])
        self.assertContains(response, f'href="{edit}"')
        self.assertContains(response, f'href="{reverse("table-duplicate", args=[self.created.slug])}"')
        self.assertNotContains(response, reverse('table-duplicate', args=[self.joined.slug]))
        self.assertContains(response, italian("You're in"), count=1)  # the joined table only
