from django.test import TestCase
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import Event


class EventTableBookingTest(TestCase):
    """With table booking off the program is reserved to managers and superusers,
    and the event page drops the program link and "Your tables"."""

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

    def test_event_page_hides_program_link(self):
        self.client.force_login(UserProfileFactory().user)
        response = self.client.get(self.detail_url)
        self.assertIsNone(response.context['program_url'])
        self.assertNotContains(response, f'href="{self.program_url}"')
        self.assertNotContains(response, 'Your tables')

    def test_custom_button_shown_first(self):
        self.event.table_booking_enabled = True
        self.event.custom_button_title = 'Tickets'
        self.event.custom_button_subtitle = 'Buy them online'
        self.event.custom_button_url = 'https://example.com/tickets'
        self.event.save()
        content = self.client.get(self.detail_url).content.decode()
        self.assertIn('href="https://example.com/tickets" target="_blank"', content)
        self.assertIn('Buy them online', content)
        # After the hero CTA, the first card is the custom button, then the program card
        hero_cta = content.index(f'href="{self.program_url}"')
        program_card = content.index(f'href="{self.program_url}"', hero_cta + 1)
        self.assertLess(content.index('https://example.com/tickets'), program_card)

    def test_custom_button_hidden_without_url(self):
        self.event.custom_button_title = 'Tickets'
        self.event.save()
        response = self.client.get(self.detail_url)
        self.assertFalse(response.context['show_custom_button'])
        self.assertNotContains(response, 'Tickets')

    def _post_data(self, **extra):
        return {'name': self.event.name, 'leaderboard_enabled': 'on', **extra}

    def test_manager_toggles_booking_and_sets_button(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(reverse('event-manage-data', kwargs={'slug': self.event.slug}), self._post_data(
            custom_button_title='Tickets', custom_button_url='https://example.com/tickets'))
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertFalse(self.event.table_booking_enabled)
        self.assertEqual(self.event.custom_button_title, 'Tickets')
        self.assertEqual(self.event.custom_button_url, 'https://example.com/tickets')

    def test_button_needs_title_and_url(self):
        self.client.force_login(self.owner.user)
        url = reverse('event-manage-data', kwargs={'slug': self.event.slug})
        response = self.client.post(url, self._post_data(custom_button_url='https://example.com'))
        self.assertIn('custom_button_title', response.context['form'].errors)
        response = self.client.post(url, self._post_data(custom_button_title='Tickets'))
        self.assertIn('custom_button_url', response.context['form'].errors)
