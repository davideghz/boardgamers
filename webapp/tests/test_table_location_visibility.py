from datetime import timedelta

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
            author=cls.profile, location=cls.location, date=today + timedelta(days=1))
        cls.past = TableFactory(
            author=cls.profile, location=cls.location, date=today - timedelta(days=1))

    def test_location_tables_outside_feed_appear_in_both_tabs(self):
        url = reverse('table-index')
        for tab, table in [('upcoming', self.upcoming), ('past', self.past)]:
            with self.subTest(tab=tab):
                response = self.client.get(url, {'tab': tab})
                self.assertEqual(list(response.context['tables']), [table])

        home = self.client.get(reverse('home'))
        self.assertNotIn(self.upcoming, home.context['future_tables'])
        self.assertNotIn(self.past, home.context['past_tables'])

    def test_event_tables_stay_outside_the_index(self):
        event = Event.objects.create(name='Event', creator=self.profile, status=Event.PENDING)
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
