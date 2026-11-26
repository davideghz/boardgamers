from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Event, LocationFollower


def tables(response):
    return [item for kind, item in response.context['items'] if kind == 'table']


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
                response = self.client.get(url, {'tab': tab})  # the old parameter still works
                self.assertEqual(tables(response), [table])

        home = self.client.get(reverse('home'))
        self.assertNotIn(self.upcoming, home.context['future_tables'])
        self.assertNotIn(self.past, home.context['past_tables'])

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
                self.assertEqual(tables(response), expected)

    def test_tables_of_published_events_are_in_the_index(self):
        draft = Event.objects.create(name='Draft', creator=self.profile, status=Event.DRAFT)
        TableFactory(author=self.profile, location=None, event=draft, date=self.upcoming.date)
        response = self.client.get(reverse('table-index'))
        self.assertEqual(tables(response), [self.upcoming])

        draft.status = Event.PUBLISHED
        draft.save()
        response = self.client.get(reverse('table-index'))
        self.assertEqual(len(tables(response)), 2)

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

        response = self.client.get(reverse('location-search'), {'suggested': '1'})
        self.assertEqual(
            {result['slug'] for result in response.json()['results']},
            {self.location.slug, self.empty_location.slug, followed.slug},
        )

    def test_selecting_an_empty_location_names_it_among_the_filters(self):
        for tab in ('upcoming', 'past'):
            with self.subTest(tab=tab), translation.override('it'):
                response = self.client.get(
                    reverse('table-index'), {'location': self.empty_location.slug, 'tab': tab},
                    headers={'Accept-Language': 'it'},
                )
                self.assertContains(response, 'Luogo: Club senza tavoli')
                self.assertContains(response, 'Nessun risultato.')
                self.assertEqual(tables(response), [])
