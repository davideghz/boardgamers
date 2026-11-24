from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, EventParticipant, Location, Member, Membership, Table
from webapp.sitemaps import TableSitemap


class OrganizedEventAccessTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory()
        cls.venue_owner = UserProfileFactory()
        cls.member = UserProfileFactory()
        cls.organizer = LocationFactory(creator=UserProfileFactory())
        cls.organizer.managers.add(cls.manager)
        cls.venue = LocationFactory(creator=cls.venue_owner)
        cls.event = Event.objects.create(name='Fiera', description='Giochi', creator=cls.venue_owner,
                                         organizer_location=cls.organizer, venue_location=cls.venue)
        cls.event.managers.add(cls.venue_owner)
        cls.day = timezone.localdate() + timedelta(days=1)
        EventDate.objects.create(event=cls.event, date=cls.day)
        cls.table = Table.objects.create(event=cls.event, date=cls.day, author=cls.manager)

    def test_only_organizer_staff_manage_or_publish_a_draft(self):
        self.client.force_login(self.venue_owner.user)
        manage = reverse('event-manage', args=[self.event.slug])
        publish = reverse('event-manage-publish', args=[self.event.slug])
        self.assertEqual(self.client.get(manage).status_code, 404)
        self.assertEqual(self.client.post(publish).status_code, 403)
        self.assertFalse(Event.objects.managed_by(self.venue_owner).exists())
        self.client.force_login(self.manager.user)
        self.assertEqual(self.client.get(manage).status_code, 200)
        self.assertContains(self.client.get(reverse('account-events')), self.event.name)
        self.organizer.managers.remove(self.manager)
        self.assertEqual(self.client.post(publish).status_code, 403)
        self.assertNotContains(self.client.get(reverse('account-events')), self.event.name)

    def test_table_visibility_applies_to_detail_actions_and_sitemap(self):
        join = reverse('join_table', args=[self.table.slug])
        self.assertNotIn(self.table, TableSitemap().items())
        self.assertEqual(self.client.get(self.table.get_absolute_url()).status_code, 404)
        self.client.force_login(self.venue_owner.user)
        self.assertEqual(self.client.post(join).status_code, 404)
        self.assertEqual(self.client.get(reverse('table-duplicate', args=[self.table.slug])).status_code, 404)
        self.client.force_login(self.manager.user)
        self.assertEqual(self.client.get(self.table.get_absolute_url()).status_code, 200)
        self.assertEqual(self.client.get(reverse('table-delete', args=[self.table.slug])).status_code, 200)
        self.assertFalse(self.table.player_set.exists())
        self.event.status = Event.PUBLISHED
        self.event.save(update_fields=['status'])
        self.assertIn(self.table, TableSitemap().items())
        self.event.table_booking_enabled = False
        self.event.save(update_fields=['table_booking_enabled'])
        self.assertNotIn(self.table, TableSitemap().items())

    def test_membership_dates_and_location_are_checked_for_creation_and_attendance(self):
        self.organizer.event_creation_permission = Location.PERM_MEMBERS_ONLY
        self.organizer.event_join_permission = Location.PERM_MEMBERS_ONLY
        self.organizer.save(update_fields=['event_creation_permission', 'event_join_permission'])
        self.event.status = Event.PUBLISHED
        self.event.save(update_fields=['status'])
        join = reverse('event-join', args=[self.event.slug])
        self.client.force_login(self.member.user)
        member = Member.objects.create(location=self.organizer, user_profile=self.member)
        membership = Membership.objects.create(member=member, status=Membership.ACTIVE,
                                               end_date=timezone.localdate() - timedelta(days=1))
        self.assertFalse(self.organizer.can_create_events(self.member.user))
        self.assertEqual(self.client.post(join).status_code, 403)
        membership.end_date = self.day
        membership.save(update_fields=['end_date'])
        self.assertTrue(self.organizer.can_create_events(self.member.user))
        self.assertEqual(self.client.post(join).status_code, 302)
        self.assertTrue(EventParticipant.objects.filter(event=self.event, user_profile=self.member).exists())
