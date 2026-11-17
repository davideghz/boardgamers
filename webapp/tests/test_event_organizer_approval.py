from datetime import time, timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, LocationEvent


class EventOrganizerApprovalTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.creator = UserProfileFactory(preferred_language='it')
        cls.manager = UserProfileFactory(preferred_language='it')
        cls.other_user = UserProfileFactory(preferred_language='it')
        cls.location = LocationFactory(creator=cls.creator)
        cls.location.managers.add(cls.manager)
        cls.event = LocationEvent.objects.create(
            name='Serata Ludica di Genova', creator=cls.creator, host_location=cls.location,
            date=timezone.localdate() + timedelta(days=7), opening_time=time(20), closing_time=time(23),
        )

    def setUp(self):
        self.enterContext(translation.override('it'))
        self.approval_url = self.event.action_url('approve')
        self.manage_url = self.event.action_url('manage')
        self.detail_url = self.event.get_absolute_url()
        self.search_url = reverse('appointment-search')

    def test_creator_can_publish_pending_event(self):
        visitor = Client()
        self.assertEqual(visitor.get(self.detail_url).status_code, 404)
        self.assertNotContains(visitor.get(self.search_url, {'q': self.event.name}), self.detail_url)

        self.client.force_login(self.creator.user)
        response = self.client.post(self.approval_url)

        self.assertRedirects(response, self.manage_url)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.PUBLISHED)
        self.assertContains(visitor.get(self.detail_url), self.event.name)
        self.assertContains(visitor.get(self.search_url, {'q': self.event.name}), self.detail_url)

    def test_approval_requires_login_and_post(self):
        response = self.client.post(self.approval_url)
        login_url = reverse('login')
        self.assertRedirects(response, f'{login_url}?next={self.approval_url}', fetch_redirect_response=False)

        self.client.force_login(self.creator.user)
        self.assertEqual(self.client.get(self.approval_url).status_code, 405)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.DRAFT)

    def test_only_current_location_staff_can_publish(self):
        self.client.force_login(self.other_user.user)
        self.assertEqual(self.client.post(self.approval_url).status_code, 403)
        self.assertEqual(self.client.get(self.manage_url).status_code, 404)

        self.client.force_login(self.manager.user)
        self.assertRedirects(self.client.post(self.approval_url), self.manage_url)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.PUBLISHED)

    def test_approval_requires_csrf_token(self):
        organizer = Client(enforce_csrf_checks=True)
        organizer.force_login(self.creator.user)

        self.assertEqual(organizer.post(self.approval_url).status_code, 403)
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.DRAFT)

    def test_publish_button_is_for_location_staff_of_pending_event(self):
        form_action = f'action="{self.approval_url}"'

        self.client.force_login(self.creator.user)
        self.assertContains(self.client.get(self.manage_url), form_action)

        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(self.manage_url), form_action)

        self.client.force_login(self.creator.user)
        for status in (Event.PUBLISHED, Event.BLOCKED):
            with self.subTest(status=status):
                LocationEvent.objects.filter(pk=self.event.pk).update(status=status)
                self.assertNotContains(self.client.get(self.manage_url), form_action)

    def test_creator_cannot_approve_rejected_event(self):
        LocationEvent.objects.filter(pk=self.event.pk).update(status=Event.BLOCKED)
        self.client.force_login(self.creator.user)

        self.client.post(self.approval_url)

        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.BLOCKED)

    def test_creator_replaying_approval_leaves_approved_event_unchanged(self):
        original_update = timezone.now() - timedelta(days=1)
        LocationEvent.objects.filter(pk=self.event.pk).update(status=Event.PUBLISHED, updated_at=original_update)
        self.client.force_login(self.creator.user)

        self.client.post(self.approval_url)

        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.PUBLISHED)
        self.assertEqual(self.event.updated_at, original_update)

    def test_publication_requires_an_upcoming_date(self):
        LocationEvent.objects.filter(pk=self.event.pk).update(date=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.creator.user)
        self.assertNotContains(self.client.get(self.manage_url), f'action="{self.approval_url}"')

        response = self.client.post(self.approval_url)

        self.assertRedirects(response, self.event.action_url('manage-dates'))
        self.event.refresh_from_db()
        self.assertEqual(self.event.status, Event.DRAFT)

    def test_manifestation_keeps_its_distinct_publication_route(self):
        manifestation = Event.objects.create(name='Festival', description='Giochi in fiera', creator=self.creator)
        EventDate.objects.create(event=manifestation, date=timezone.localdate() + timedelta(days=1))
        self.client.force_login(self.creator.user)
        self.assertEqual(self.client.post(f'/events/{manifestation.slug}/manage/approve/').status_code, 404)
        response = self.client.post(reverse('event-manage-publish', args=[manifestation.slug]))
        self.assertRedirects(response, reverse('event-manage', args=[manifestation.slug]))
        manifestation.refresh_from_db()
        self.assertEqual(manifestation.status, Event.PUBLISHED)
