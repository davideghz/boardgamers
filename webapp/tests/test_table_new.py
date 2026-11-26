from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, Location, LocationFollower, Membership, Table
from webapp.tests.access_matrix import add_membership
from webapp.tests.test_location_table_access import italian

MANAGERS_ONLY = Location.PERM_MANAGERS_ONLY
MEMBERS_ONLY = Location.PERM_MEMBERS_ONLY


class TableNewTest(TestCase):
    """F2: "New table" asks for the location only when it isn't known, and only among the
    locations where the user may create tables."""

    def setUp(self):
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)
        self.url = reverse('table-new')

    def create_url(self, location, **query):
        return reverse('location-table-create', args=[location.slug], query=query or None)

    def test_anonymous_users_sign_in_first(self):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f'{reverse("login")}?next={self.url}',
                             fetch_redirect_response=False)

    def test_no_location_to_choose(self):
        LocationFactory(table_creation_permission=MANAGERS_ONLY)
        response = self.client.get(self.url)
        self.assertFalse(response.context['has_choices'])
        self.assertContains(response, italian("You can't propose tables at any location yet."))
        self.assertNotContains(response, 'data-submit-on-select')

    def test_one_location_skips_the_choice(self):
        LocationFactory(table_creation_permission=MANAGERS_ONLY)
        only = LocationFactory()
        self.assertRedirects(self.client.get(self.url, {'date': '2030-05-04'}),
                             self.create_url(only, date='2030-05-04'), fetch_redirect_response=False)

    def test_several_locations_own_ones_first_then_the_search(self):
        followed = LocationFactory(name='Seguita')
        LocationFactory(name='Altra')
        LocationFollower.objects.create(user_profile=self.profile, location=followed)
        response = self.client.get(self.url)
        self.assertEqual(response.context['your_locations'], [followed])
        self.assertContains(response, f'href="{self.create_url(followed)}"')
        self.assertContains(response, 'data-submit-on-select')
        self.assertContains(response, reverse('location-creatable'))

    def test_the_context_picks_the_location_or_the_event(self):
        open_to_all, closed = LocationFactory(), LocationFactory(table_creation_permission=MANAGERS_ONLY)
        LocationFactory()
        self.assertRedirects(self.client.get(self.url, {'location': open_to_all.slug, 'date': '2030-05-04'}),
                             self.create_url(open_to_all, date='2030-05-04'), fetch_redirect_response=False)
        # Not allowed there: the chooser instead
        self.assertEqual(self.client.get(self.url, {'location': closed.slug}).status_code, 200)

        event = Event.objects.create(name='Fiera', organizer_location=closed, status=Event.PUBLISHED)
        EventDate.objects.create(event=event, date=timezone.localdate() + timedelta(days=3))
        self.assertEqual(self.client.get(self.url, {'event': event.slug}).status_code, 200)
        closed.managers.add(self.profile)
        self.assertRedirects(self.client.get(self.url, {'event': event.slug}),
                             reverse('event-table-create', args=[event.slug]), fetch_redirect_response=False)

    def test_the_old_entry_point_redirects(self):
        self.assertRedirects(self.client.get(reverse('locations-index'), {'new_table': '1'}), self.url,
                             fetch_redirect_response=False)

    def test_a_table_called_new_keeps_the_address_free(self):
        table = Table.objects.create(title='New', location=LocationFactory(), date=date(2030, 5, 4))
        self.assertNotEqual(table.slug, 'new')


class CreatableLocationSearchTest(TestCase):
    """api/locations/creatable/: the picker of "New table" (and, with for=events, of events)."""

    def setUp(self):
        self.profile = UserProfileFactory()
        self.open = LocationFactory(name='Club aperto', city='Padova')
        self.members = LocationFactory(name='Club soci', city='Padova', table_creation_permission=MEMBERS_ONLY)
        self.closed = LocationFactory(name='Club chiuso', city='Padova', table_creation_permission=MANAGERS_ONLY)
        self.url = reverse('location-creatable')

    def slugs(self, **params):
        return [item['slug'] for item in self.client.get(self.url, params).json()['results']]

    def test_by_permission(self):
        self.assertEqual(self.slugs(q='Padova'), [])  # anonymous
        self.client.force_login(self.profile.user)
        self.assertEqual(self.slugs(q='Padova'), [self.open.slug])
        add_membership(self.members, self.profile, Membership.ACTIVE,
                       start_date=timezone.localdate(), end_date=timezone.localdate() + timedelta(days=30))
        self.assertEqual(sorted(self.slugs(q='club')), sorted([self.open.slug, self.members.slug]))
        self.closed.managers.add(self.profile)
        self.assertEqual(len(self.slugs(q='club')), 3)

    def test_events_and_suggestions(self):
        self.client.force_login(self.profile.user)
        self.assertEqual(self.slugs(q='club', **{'for': 'events'}), [])
        self.closed.managers.add(self.profile)
        self.assertEqual(self.slugs(q='club', **{'for': 'events'}), [self.closed.slug])

        LocationFollower.objects.create(user_profile=self.profile, location=self.open)
        self.assertEqual(self.slugs(suggested='1'), [self.open.slug, self.closed.slug])  # by name
