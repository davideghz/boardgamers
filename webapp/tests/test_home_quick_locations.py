from django.test import TestCase, Client
from django.urls import reverse

import datetime

from django.utils import timezone

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import LocationFollower, Membership, Table
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import add_membership, italian


class HomeQuickLocationsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.created = LocationFactory(creator=self.user_profile)
        self.managed = LocationFactory(creator=UserProfileFactory())
        self.managed.managers.add(self.user_profile)
        self.member_of = LocationFactory(creator=UserProfileFactory())
        add_membership(self.member_of, self.user_profile, Membership.ACTIVE)
        self.followed = LocationFactory(creator=UserProfileFactory())
        LocationFollower.objects.create(user_profile=self.user_profile, location=self.followed)
        self.client.force_login(self.user_profile.user)

    def _manage_url(self, location):
        return reverse('location-manage', kwargs={'slug': location.slug})

    def test_roles_are_listed_in_order(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(
            [(location.pk, role) for location, role in response.context['quick_locations']],
            [(self.created.pk, 'creator'), (self.managed.pk, 'manager'), (self.member_of.pk, 'member'),
             (self.followed.pk, None)],
        )

    def test_gear_is_shown_for_created_and_managed_locations_only(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, self._manage_url(self.created))
        self.assertContains(response, self._manage_url(self.managed))
        self.assertNotContains(response, self._manage_url(self.member_of))
        self.assertNotContains(response, self._manage_url(self.followed))

    def test_member_locations_say_so(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Socio')

    def test_pending_or_expired_memberships_are_not_listed_as_member(self):
        location = LocationFactory(creator=UserProfileFactory())
        add_membership(location, self.user_profile, Membership.PENDING)
        add_membership(LocationFactory(creator=UserProfileFactory()), self.user_profile, Membership.ACTIVE,
                       end_date=timezone.localdate() - datetime.timedelta(days=1))
        response = self.client.get(reverse('home'))
        self.assertEqual([role for _location, role in response.context['quick_locations']].count('member'), 1)

    def test_a_followed_managed_location_appears_once(self):
        LocationFollower.objects.create(user_profile=self.user_profile, location=self.managed)
        response = self.client.get(reverse('home'))
        pks = [location.pk for location, _role in response.context['quick_locations']]
        self.assertEqual(pks.count(self.managed.pk), 1)


class HomeByPersonaTest(TestCase):
    """The home page for each demo persona (see `seed_ui_personas`)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(reverse('home'))

    def table_ids(self, response):
        return {table.pk for table in response.context['future_tables']}

    def test_without_followed_locations_the_public_tables_show(self):
        visitor, newcomer = self.get(), self.get('newcomer')

        self.assertFalse(newcomer.context['shows_my_tables'])
        self.assertTrue(self.table_ids(newcomer))
        self.assertEqual(self.table_ids(newcomer), self.table_ids(visitor))
        self.assertContains(newcomer, italian('Find locations to follow'))

    def test_followed_locations_without_tables_fall_back_to_the_public_ones(self):
        Table.objects.filter(location__in=[self.data.circolo, self.data.associazione]).delete()

        response = self.get('member')

        self.assertFalse(response.context['shows_my_tables'])
        self.assertTrue(self.table_ids(response))
        self.assertContains(response, italian(
            'Your locations have no upcoming tables: here are the ones from all locations.'))

    def test_followed_tables_come_first_when_there_are_some(self):
        response = self.get('member')

        self.assertTrue(response.context['shows_my_tables'])
        self.assertEqual(self.table_ids(response), {self.data.tables['members'].pk})

    def test_managers_see_the_tables_of_their_locations(self):
        response = self.get('manager')

        self.assertTrue(response.context['shows_my_tables'])
        self.assertEqual(self.table_ids(response), {self.data.tables['upcoming'].pk, self.data.tables['members'].pk})

    def test_add_location_invites_skip_who_runs_one(self):
        cta = italian('Have a location to add?')
        self.assertContains(self.get('newcomer'), cta)
        self.assertContains(self.get(), cta)
        self.assertNotContains(self.get('manager'), cta)
        self.client.force_login(self.data.manager.user)
        self.assertNotContains(self.client.get(reverse('locations-index')), cta)

    def test_location_section_invites_to_see_locations(self):
        self.assertContains(self.get(), italian('to see nearby locations.'))

    def test_empty_home_offers_a_way_forward(self):
        Table.objects.filter(date__gte=timezone.localdate()).delete()

        self.assertContains(self.get(), italian('Find a place to play'))
        self.assertContains(self.get('newcomer'), f"{reverse('locations-index')}?new_table=1")
