from datetime import timedelta

from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, Location, LocationAccess, Membership
from webapp.tests.test_location_table_access import AccessMatrixMixin, add_membership

ANYONE, MEMBERS, MANAGERS = Location.PERM_ANYONE, Location.PERM_MEMBERS_ONLY, Location.PERM_MANAGERS_ONLY


class EventAccessTest(AccessMatrixMixin, TestCase):
    def test_event_creation(self):
        self.assert_matrix('event_creation_permission', 'event_creation_access', [MANAGERS, MEMBERS])

    def test_event_join(self):
        self.assert_matrix('event_join_permission', 'event_join_access', [ANYONE, MEMBERS])

    def test_shortcuts_and_queryset_agree_with_the_access(self):
        for permission in (MANAGERS, MEMBERS):
            self.location.event_creation_permission = permission
            self.location.event_join_permission = ANYONE if permission == MANAGERS else MEMBERS
            self.location.save(update_fields=['event_creation_permission', 'event_join_permission'])
            for name, profile in self.profiles.items():
                user = profile.user if profile else AnonymousUser()
                with self.subTest(permission=permission, profile=name):
                    allowed = self.location.event_creation_access(profile).allowed
                    self.assertEqual(self.location.can_create_events(user), allowed)
                    self.assertEqual(
                        Location.event_creation_locations(user).filter(pk=self.location.pk).exists(), allowed)
                    self.assertEqual(
                        self.location.can_join_events(profile), self.location.event_join_access(profile).allowed)


class EventAccessViewsTest(TestCase):
    def setUp(self):
        self.organizer = LocationFactory(
            creator=UserProfileFactory(), enable_membership=True,
            event_creation_permission=MEMBERS, event_join_permission=MEMBERS)
        self.event = Event.objects.create(
            name='Serata', description='Giochi', creator=self.organizer.creator, status=Event.PUBLISHED,
            organizer_location=self.organizer, venue_location=self.organizer)
        EventDate.objects.create(event=self.event, date=timezone.localdate() + timedelta(days=3))
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)

    def test_event_page_refuses_a_pending_member(self):
        add_membership(self.organizer, self.profile, Membership.PENDING)

        response = self.client.get(reverse('event_detail', args=[self.event.slug]))

        self.assertEqual(response.context['event_join'].reason, LocationAccess.MEMBERSHIP_PENDING)
        self.assertNotContains(response, reverse('event-join', args=[self.event.slug]))

    def test_event_page_offers_joining_to_an_active_member(self):
        add_membership(self.organizer, self.profile, Membership.ACTIVE)

        response = self.client.get(reverse('event_detail', args=[self.event.slug]))

        self.assertTrue(response.context['event_join'].allowed)

    def test_location_page_offers_event_creation_to_members_only(self):
        url = reverse('location-detail', args=[self.organizer.slug])
        create = reverse('location-event-create', args=[self.organizer.slug])

        response = self.client.get(url)
        self.assertEqual(response.context['event_creation'].reason, LocationAccess.MEMBERS_ONLY)
        self.assertNotContains(response, create)

        add_membership(self.organizer, self.profile, Membership.ACTIVE)
        self.assertContains(self.client.get(url), create)
