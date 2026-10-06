from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import LocationFollower


class HomeQuickLocationsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.created = LocationFactory(creator=self.user_profile)
        self.managed = LocationFactory(creator=UserProfileFactory())
        self.managed.managers.add(self.user_profile)
        self.followed = LocationFactory(creator=UserProfileFactory())
        LocationFollower.objects.create(user_profile=self.user_profile, location=self.followed)
        self.client.force_login(self.user_profile.user)

    def _manage_url(self, location):
        return reverse('location-manage', kwargs={'slug': location.slug})

    def test_roles_are_listed_in_order(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(
            [(location.pk, role) for location, role in response.context['quick_locations']],
            [(self.created.pk, 'creator'), (self.managed.pk, 'manager'), (self.followed.pk, None)],
        )

    def test_gear_is_shown_for_created_and_managed_locations_only(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, self._manage_url(self.created))
        self.assertContains(response, self._manage_url(self.managed))
        self.assertNotContains(response, self._manage_url(self.followed))

    def test_a_followed_managed_location_appears_once(self):
        LocationFollower.objects.create(user_profile=self.user_profile, location=self.managed)
        response = self.client.get(reverse('home'))
        pks = [location.pk for location, _role in response.context['quick_locations']]
        self.assertEqual(pks.count(self.managed.pk), 1)
