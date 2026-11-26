from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Location, Membership
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import add_membership, italian

MOBILE_BAR = 'lg:hidden fixed bottom-0'


class LocationPageCtasTest(TestCase):
    """What the location page invites each persona to do (see `seed_ui_personas`)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, location, persona=None, query=''):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(reverse('location-detail', args=[location.slug]) + query)

    def test_follow_box_is_not_offered_to_managers(self):
        follow = reverse('follow-location', args=[self.data.negozio.slug])
        self.assertNotContains(self.get(self.data.negozio, 'manager'), follow)
        self.assertContains(self.get(self.data.negozio, 'newcomer'), follow)

    def test_visitors_are_asked_to_log_in_to_follow(self):
        location = self.data.negozio
        response = self.get(location)

        self.assertNotContains(response, reverse('follow-location', args=[location.slug]))
        self.assertContains(response, italian('Log in to follow'))
        self.assertContains(
            response, f"{reverse('login')}?next={reverse('location-detail', args=[location.slug])}%3Ffollow%3D1")

    def test_after_logging_in_the_follow_button_is_ready(self):
        self.assertContains(self.get(self.data.negozio, 'newcomer', '?follow=1'), 'autofocus')
        self.assertNotContains(self.get(self.data.negozio, 'newcomer'), 'autofocus')

    def test_following_says_so_in_the_user_language(self):
        self.client.force_login(self.data.newcomer.user)
        response = self.client.post(reverse('follow-location', args=[self.data.negozio.slug]))

        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertEqual(messages, [italian('You are now following %(name)s.') % {'name': self.data.negozio.name}])

    def test_managers_find_manage_in_the_header_too(self):
        manage = f'''href="{reverse('location-manage', args=[self.data.circolo.slug])}"'''
        # Header pill for mobile, sidebar button from lg up.
        response = self.get(self.data.circolo, 'manager')
        # Once, in the manager bar at the top of the page (D3), on every screen size
        self.assertContains(response, manage, count=1)
        self.assertNotContains(response, 'hide_membership')  # the partial's comment stays a comment
        self.assertNotContains(self.get(self.data.circolo, 'member'), manage)

    def test_mobile_bar_only_when_it_has_an_action(self):
        # Managers-only tables: nothing to offer a visitor.
        self.assertNotContains(self.get(self.data.associazione, 'newcomer'), MOBILE_BAR)
        self.assertContains(self.get(self.data.associazione, 'manager'), MOBILE_BAR)
        # Members-only tables: the bar invites to join.
        response = self.get(self.data.circolo, 'newcomer')
        self.assertContains(response, MOBILE_BAR)
        self.assertContains(response, reverse('location-request-membership', args=[self.data.circolo.slug]))

    def test_visitors_see_that_tables_are_for_members(self):
        note = italian('Only members of this location can join its tables.')
        self.assertContains(self.get(self.data.circolo), note)
        self.assertContains(self.get(self.data.circolo, 'player'), note)
        self.assertNotContains(self.get(self.data.circolo, 'member'), note)
        self.assertNotContains(self.get(self.data.negozio), note)

    def test_empty_tables_invite_only_who_can_create(self):
        create_first = italian('Create the first table')
        empty = italian('No upcoming tables.')

        response = self.get(self.data.associazione, 'newcomer')
        self.assertContains(response, empty)
        self.assertNotContains(response, create_first)

        response = self.get(self.data.associazione, 'manager')
        self.assertContains(response, create_first)
        self.assertContains(response, reverse('location-calendar', args=[self.data.associazione.slug]))

    def test_events_say_who_can_propose_them(self):
        create = reverse('location-event-create', args=[self.data.associazione.slug])
        note = italian('Only members can propose events here.')

        response = self.get(self.data.associazione, 'newcomer')
        self.assertContains(response, note)
        self.assertNotContains(response, create)

        response = self.get(self.data.associazione, 'member')
        self.assertNotContains(response, note)
        self.assertContains(response, create)


class MembersOnlyEmptyStateTest(TestCase):
    def setUp(self):
        self.location = LocationFactory(
            creator=UserProfileFactory(), enable_membership=True,
            table_creation_permission=Location.PERM_MEMBERS_ONLY)
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)
        self.url = reverse('location-detail', args=[self.location.slug])

    def test_non_members_are_invited_to_join(self):
        response = self.client.get(self.url)

        self.assertContains(response, italian('Become a member to propose tables'))

    def test_pending_members_are_told_to_wait(self):
        add_membership(self.location, self.profile, Membership.PENDING)

        response = self.client.get(self.url)

        self.assertContains(
            response, italian('Your membership request is pending: once it is approved you can propose tables here.'))
        self.assertNotContains(response, italian('Become a member to propose tables'))


class MembersOnlyEventsWithoutEventsTest(TestCase):
    """The events note shows even before the location has organized any event."""

    def setUp(self):
        self.location = LocationFactory(
            creator=UserProfileFactory(), enable_membership=True,
            event_creation_permission=Location.PERM_MEMBERS_ONLY)
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)
        self.url = reverse('location-detail', args=[self.location.slug])

    def test_non_members_are_told_who_can_propose_events(self):
        response = self.client.get(self.url)

        self.assertContains(response, italian('Only members can propose events here.'))
        self.assertContains(response, reverse('location-request-membership', args=[self.location.slug]))
        self.assertNotContains(response, reverse('location-event-create', args=[self.location.slug]))

    def test_pending_members_are_told_to_wait(self):
        add_membership(self.location, self.profile, Membership.PENDING)

        response = self.client.get(self.url)

        self.assertContains(response, italian('Only members can propose events here.'))
        self.assertContains(response, italian('Your membership request is pending.'))
