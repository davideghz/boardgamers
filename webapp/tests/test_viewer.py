import datetime

from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, SuperUserProfileFactory, UserProfileFactory
from webapp.models import Location, LocationFollower, Membership
from webapp.services.ui_personas import seed_ui_personas
from webapp.services.viewer import Viewer, get_viewer
from webapp.tests.test_location_table_access import ANYONE, MANAGERS, MEMBERS, AccessMatrixMixin, add_membership


class RelationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory()
        cls.location = LocationFactory(creator=cls.owner)
        cls.manager, cls.member, cls.pending, cls.follower, cls.visitor, cls.expired = (
            UserProfileFactory() for _ in range(6))
        cls.location.managers.add(cls.manager)
        add_membership(cls.location, cls.member, Membership.ACTIVE)
        add_membership(cls.location, cls.pending, Membership.PENDING)
        add_membership(cls.location, cls.expired, Membership.ACTIVE,
                       end_date=timezone.localdate() - datetime.timedelta(days=1))
        for profile in (cls.follower, cls.member, cls.expired):
            LocationFollower.objects.create(user_profile=profile, location=cls.location)

    def relation(self, profile, **kwargs):
        return Viewer(profile.user if profile else AnonymousUser(), **kwargs).relation(self.location)

    def test_each_relation(self):
        cases = {
            'anonymous': (None, 'anonymous'),
            'owner': (self.owner, 'manager'),
            'manager': (self.manager, 'manager'),
            'member, also following': (self.member, 'member'),
            'pending': (self.pending, 'pending'),
            'follower': (self.follower, 'follower'),
            'expired member, still following': (self.expired, 'follower'),
            'visitor': (self.visitor, 'visitor'),
        }
        for name, (profile, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(self.relation(profile), expected)

    def test_as_visitor_is_honored_for_managers_only(self):
        self.assertEqual(self.relation(self.manager, as_visitor=True), 'visitor')
        self.assertEqual(self.relation(self.member, as_visitor=True), 'member')

    def test_as_visitor_changes_the_relation_not_the_permissions(self):
        viewer = Viewer(self.manager.user, as_visitor=True)
        self.assertTrue(viewer.table_creation_access(self.location).is_manager)

    def test_the_request_shares_one_viewer_read_from_the_query_string(self):
        request = RequestFactory().get('/', {'as': 'visitor'})
        request.user = self.manager.user
        self.assertIs(get_viewer(request), get_viewer(request))
        self.assertTrue(get_viewer(request).sees_as_visitor)

    def test_location_relation_tag(self):
        html = Template('{% load custom_tags %}{% location_relation location as rel %}[{{ rel }}]').render(
            Context({'viewer': Viewer(self.pending.user), 'location': self.location}))
        self.assertEqual(html, '[pending]')

    def test_ties_cost_one_query_whatever_the_number_of_locations(self):
        viewer = Viewer(self.member.user)
        locations = [self.location, *LocationFactory.create_batch(3, creator=self.owner)]
        with CaptureQueriesContext(connection) as ctx:
            for location in locations:
                viewer.relation(location)
                viewer.table_join_access(location)
        self.assertEqual(len(ctx), 1)


class ViewerAccessMatchesLocationTest(AccessMatrixMixin, TestCase):
    """The viewer answers the same as Location.*_access, from its cached sets."""

    def test_every_permission_and_profile(self):
        fields = {
            'table_creation': [ANYONE, MEMBERS, MANAGERS], 'table_join': [ANYONE, MEMBERS],
            'event_creation': [MANAGERS, MEMBERS], 'event_join': [ANYONE, MEMBERS],
        }
        for action, permissions in fields.items():
            for permission in permissions:
                setattr(self.location, f'{action}_permission', permission)
                for name, profile in self.profiles.items():
                    with self.subTest(action=action, permission=permission, profile=name):
                        viewer = Viewer(profile.user if profile else AnonymousUser())
                        self.assertEqual(getattr(viewer, f'{action}_access')(self.location),
                                         getattr(self.location, f'{action}_access')(profile))


class ViewerActivityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def viewer(self, persona):
        return Viewer(self.data.profile(persona).user)

    def test_upcoming_participations(self):
        participations = self.viewer('member').upcoming_participations
        self.assertEqual(participations.table_ids, {self.data.tables['members'].pk})
        self.assertEqual(participations.event_ids, {self.data.night.pk})
        self.assertEqual(self.viewer('newcomer').upcoming_participations, (frozenset(), frozenset()))

    def test_roles_and_activity(self):
        self.assertTrue(self.viewer('manager').manages_events)
        self.assertFalse(self.viewer('member').manages_events)
        self.assertTrue(self.viewer('player').has_activity)
        self.assertFalse(self.viewer('newcomer').has_activity)
        self.assertEqual(self.viewer('manager').created_location_ids,
                         {self.data.circolo.pk, self.data.associazione.pk})


# Queries of each page in A1 (before the UI plan), measured on the demo data: D1 must not
# exceed them.
A1_QUERIES = {
    ('anonymous', 'home'): 17, ('newcomer', 'home'): 21, ('player', 'home'): 28, ('member', 'home'): 26,
    ('manager', 'home'): 21, ('anonymous', 'circolo'): 16, ('newcomer', 'circolo'): 26,
    ('player', 'circolo'): 25, ('member', 'circolo'): 26, ('manager', 'circolo'): 23,
    ('manager', 'associazione'): 22, ('member', 'associazione'): 25,
}


class PageQueriesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def test_home_and_location_pages_stay_within_the_a1_queries(self):
        urls = {'home': reverse('home'),
                'circolo': reverse('location-detail', args=[self.data.circolo.slug]),
                'associazione': reverse('location-detail', args=[self.data.associazione.slug])}
        for (persona, page), budget in A1_QUERIES.items():
            with self.subTest(persona=persona, page=page):
                self.client.logout()
                if persona != 'anonymous':
                    self.client.force_login(self.data.profile(persona).user)
                self.client.get(urls[page])  # the first request warms per-process caches
                with CaptureQueriesContext(connection) as ctx:
                    self.client.get(urls[page])
                self.assertLessEqual(len(ctx), budget)


class SuperuserAccessTest(TestCase):
    def test_superusers_may_act_without_ties(self):
        location = LocationFactory(creator=UserProfileFactory(), table_creation_permission=Location.PERM_MANAGERS_ONLY)
        self.assertTrue(Viewer(SuperUserProfileFactory().user).table_creation_access(location).allowed)
