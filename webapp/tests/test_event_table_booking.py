from django.test import TestCase
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import Event


class EventTableBookingTest(TestCase):
    """With table booking off the program is reserved to managers and superusers,
    and the event page links to the external program (if any) and drops "Your tables"."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.event = Event.objects.create(
            name="Con", slug="con", creator=self.owner, status=Event.APPROVED,
            table_booking_enabled=False)
        self.program_url = reverse('event-program', kwargs={'slug': self.event.slug})
        self.detail_url = reverse('event_detail', kwargs={'slug': self.event.slug})

    def test_program_hidden_from_visitors(self):
        self.assertEqual(self.client.get(self.program_url).status_code, 404)
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(self.program_url).status_code, 404)

    def test_program_open_to_managers_and_superusers(self):
        self.client.force_login(self.owner.user)
        self.assertEqual(self.client.get(self.program_url).status_code, 200)
        admin = UserProfileFactory()
        admin.user.is_superuser = True
        admin.user.save()
        self.client.force_login(admin.user)
        self.assertEqual(self.client.get(self.program_url).status_code, 200)

    def test_program_public_when_booking_on(self):
        self.event.table_booking_enabled = True
        self.event.save()
        self.assertEqual(self.client.get(self.program_url).status_code, 200)
        response = self.client.get(self.detail_url)
        self.assertContains(response, f'href="{self.program_url}"')

    def test_event_page_without_external_link(self):
        self.client.force_login(UserProfileFactory().user)
        response = self.client.get(self.detail_url)
        self.assertIsNone(response.context['program_url'])
        self.assertNotContains(response, f'href="{self.program_url}"')
        self.assertNotContains(response, 'Your tables')

    def test_event_page_links_external_program(self):
        self.event.external_program_url = 'https://example.com/program'
        self.event.save()
        response = self.client.get(self.detail_url)
        self.assertContains(response, 'href="https://example.com/program" target="_blank"', count=2)
        self.assertNotContains(response, f'href="{self.program_url}"')

    def test_manager_toggles_booking(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(reverse('event-manage-data', kwargs={'slug': self.event.slug}), {
            'name': self.event.name,
            'external_program_url': 'https://example.com/program',
            'leaderboard_enabled': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertFalse(self.event.table_booking_enabled)
        self.assertEqual(self.event.external_program_url, 'https://example.com/program')
