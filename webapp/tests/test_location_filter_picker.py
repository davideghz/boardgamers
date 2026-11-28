import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import LocationFollower, Player, Table


class LocationFilterPickerTest(TestCase):
    """The location filter of Tables uses the shared search picker; My tables and My activities,
    with only the user's own locations, a menu of them."""

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

        self.assertContains(response, 'class="js-search-picker inline-flex"')  # as a filter chip
        self.assertContains(response, 'data-value-key="slug"')
        self.assertContains(response, f'value="{self.location.slug}"')
        self.assertNotContains(response, 'location-filter-modal')

    def test_my_tables_and_activities_offer_the_users_locations_in_a_menu(self):
        self.client.force_login(self.profile.user)
        response = self.client.get(reverse('account-tables'), follow=True)
        self.assertEqual(response.context['locations'], [self.location])
        self.assertContains(response, 'popovertarget="activity-location-menu"')
        self.assertContains(response, f'?type=tables&amp;role=organizer&amp;location={self.location.slug}')
        self.assertNotContains(response, self.other.name)

        response = self.client.get(reverse('account-activities'), {'location': self.location.slug})
        self.assertEqual(response.context['selected_location_name'], self.location.name)
        self.assertContains(response, f'<input type="hidden" name="location" value="{self.location.slug}">')

    def test_suggestions_are_the_users_locations_else_the_busiest(self):
        url = reverse('location-search')
        anonymous = self.client.get(url, {'suggested': '1'}).json()['results']
        self.assertEqual([item['slug'] for item in anonymous], [self.location.slug])

        LocationFollower.objects.create(user_profile=self.profile, location=self.other)
        self.client.force_login(self.profile.user)
        mine = self.client.get(url, {'suggested': '1'}).json()['results']
        self.assertEqual([item['slug'] for item in mine], [self.other.slug])
