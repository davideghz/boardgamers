import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import LocationFollower, Player, Table


class LocationFilterPickerTest(TestCase):
    """The location filters of Tables, My tables and My activities use the shared search picker."""

    @classmethod
    def setUpTestData(cls):
        cls.profile = UserProfileFactory()
        cls.location = LocationFactory(creator=UserProfileFactory())
        cls.other = LocationFactory(creator=UserProfileFactory())
        cls.table = Table.objects.create(
            title='Serata', location=cls.location, author=cls.profile,
            date=timezone.localdate() + datetime.timedelta(days=2), time=datetime.time(21))
        Player.objects.create(table=cls.table, user_profile=cls.profile)

    def test_tables_index_restores_the_location_in_the_search_picker(self):
        response = self.client.get(reverse('table-index'), {'location': self.location.slug})

        self.assertContains(response, 'class="js-search-picker"')
        self.assertContains(response, 'data-value-key="slug"')
        self.assertContains(response, f'value="{self.location.slug}"')
        self.assertNotContains(response, 'location-filter-modal')

    def test_my_tables_filters_the_locations_of_the_users_tables(self):
        self.client.force_login(self.profile.user)
        response = self.client.get(reverse('account-tables'))

        self.assertContains(response, 'data-local-items="location-filter-items"')
        self.assertEqual([item['slug'] for item in response.context['location_filter_items']], [self.location.slug])

    def test_my_activities_uses_the_picker_instead_of_a_select(self):
        self.client.force_login(self.profile.user)
        response = self.client.get(reverse('account-activities'), {'location': self.location.slug})

        self.assertContains(response, 'data-local-items="location-filter-items"')
        self.assertContains(response, f'value="{self.location.slug}"')
        self.assertNotContains(response, '<select class="mt-1 w-full rounded-xl border border-divider bg-surface px-3 py-2.5 text-sm" name="location">')

    def test_suggestions_are_the_users_locations_else_the_busiest(self):
        url = reverse('location-search')
        anonymous = self.client.get(url, {'suggested': '1'}).json()['results']
        self.assertEqual([item['slug'] for item in anonymous], [self.location.slug])

        LocationFollower.objects.create(user_profile=self.profile, location=self.other)
        self.client.force_login(self.profile.user)
        mine = self.client.get(url, {'suggested': '1'}).json()['results']
        self.assertEqual([item['slug'] for item in mine], [self.other.slug])
