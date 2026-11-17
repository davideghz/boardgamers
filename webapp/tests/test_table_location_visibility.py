from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Event, LocationFollower


class TableLocationVisibilityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.profile = UserProfileFactory()
        cls.location = LocationFactory(
            name='Club fuori dal feed', creator=cls.profile, show_tables_in_homepage=False)
        cls.empty_location = LocationFactory(
            name='Club senza tavoli', creator=cls.profile, show_tables_in_homepage=False)
        today = timezone.localdate()
        cls.upcoming = TableFactory(
            author=cls.profile, location=cls.location, date=today + timedelta(days=1), time=time(21))
        cls.past = TableFactory(
            author=cls.profile, location=cls.location, date=today - timedelta(days=1), time=time(18))

    def test_location_tables_outside_feed_appear_in_both_tabs(self):
        url = reverse('table-index')
        for tab, table in [('upcoming', self.upcoming), ('past', self.past)]:
            with self.subTest(tab=tab):
                response = self.client.get(url, {'tab': tab})
                self.assertEqual(list(response.context['tables']), [table])

        home = self.client.get(reverse('home'))
        self.assertNotIn(self.upcoming, home.context['future_tables'])
        self.assertNotIn(self.past, home.context['past_tables'])

    def test_home_only_lists_tables_from_owned_managed_and_followed_locations_after_login(self):
        managed = LocationFactory(show_tables_in_homepage=False)
        managed.managers.add(self.profile)
        followed = LocationFactory(show_tables_in_homepage=False)
        LocationFollower.objects.create(user_profile=self.profile, location=followed)
        LocationFollower.objects.create(user_profile=self.profile, location=self.location)
        public = TableFactory(author=self.profile, location=LocationFactory(), date=self.upcoming.date, time=time(16))
        public_past = TableFactory(author=self.profile, location=public.location, date=self.past.date)
        managed_table = TableFactory(author=self.profile, location=managed, date=self.upcoming.date, time=time(18))
        followed_table = TableFactory(author=self.profile, location=followed, date=self.upcoming.date, time=time(20))
        private_table = TableFactory(
            author=self.profile, location=LocationFactory(show_tables_in_homepage=False), date=self.upcoming.date,
        )

        home_url = reverse('home')
        home = self.client.get(home_url)
        self.assertEqual(list(home.context['future_tables']), [public])
        self.assertEqual(list(home.context['past_tables']), [public_past])

        self.client.force_login(self.profile.user)
        home = self.client.get(home_url)
        self.assertEqual(list(home.context['future_tables']), [managed_table, followed_table, self.upcoming])
        self.assertEqual(list(home.context['past_tables']), [self.past])
        self.assertContains(home, self.upcoming.get_absolute_url())
        self.assertNotContains(home, public.get_absolute_url())
        self.assertNotContains(home, private_table.get_absolute_url())

    def test_location_tables_on_the_same_date_are_ordered_by_time(self):
        earlier_upcoming = TableFactory(
            author=self.profile, location=self.location, date=self.upcoming.date, time=time(18))
        later_past = TableFactory(
            author=self.profile, location=self.location, date=self.past.date, time=time(21))

        detail = self.client.get(reverse('location-detail', kwargs={'slug': self.location.slug}))
        for tab, context_key, expected in [
            ('upcoming', 'future_tables', [earlier_upcoming, self.upcoming]),
            ('past', 'past_tables', [later_past, self.past]),
        ]:
            with self.subTest(tab=tab, view='detail'):
                self.assertEqual(list(detail.context[context_key]), expected)
            with self.subTest(tab=tab, view='index'):
                response = self.client.get(
                    reverse('table-index'), {'location': self.location.slug, 'tab': tab})
                self.assertEqual(list(response.context['tables']), expected)

    def test_event_tables_stay_outside_the_index(self):
        event = Event.objects.create(name='Event', creator=self.profile, status=Event.DRAFT)
        TableFactory(author=self.profile, location=None, event=event, date=self.upcoming.date)
        response = self.client.get(reverse('table-index'))
        self.assertEqual(list(response.context['tables']), [self.upcoming])

    def test_location_search_includes_locations_outside_feed_and_without_tables(self):
        response = self.client.get(reverse('location-search'), {'q': 'Club', 'tables': '1'})
        self.assertEqual(
            {result['slug'] for result in response.json()['results']},
            {self.location.slug, self.empty_location.slug},
        )

    def test_picker_suggestions_include_locations_outside_feed(self):
        followed = LocationFactory(show_tables_in_homepage=False)
        LocationFollower.objects.create(user_profile=self.profile, location=followed)
        self.client.force_login(self.profile.user)

        response = self.client.get(reverse('table-index'))
        self.assertEqual(
            [locations for _, locations in response.context['location_picker_sections']],
            [[self.location, self.empty_location], [followed]],
        )

    def test_selecting_an_empty_location_names_it_in_the_message(self):
        for tab, message in [
            ('upcoming', 'Nessun tavolo in programma per Club senza tavoli.'),
            ('past', 'Nessun tavolo passato per Club senza tavoli.'),
        ]:
            with self.subTest(tab=tab), translation.override('it'):
                response = self.client.get(
                    reverse('table-index'), {'location': self.empty_location.slug, 'tab': tab},
                    headers={'Accept-Language': 'it'},
                )
                self.assertContains(response, message)
                self.assertEqual(list(response.context['tables']), [])
