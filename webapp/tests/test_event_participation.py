from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate, EventParticipant


class EventParticipationTest(TestCase):
    """Joining shows a one-off share modal; participants can leave until the event ends."""

    def setUp(self):
        self.user = UserProfileFactory()
        self.event = Event.objects.create(
            name="Con", slug="con", creator=UserProfileFactory(), status=Event.APPROVED)
        self.date = EventDate.objects.create(
            event=self.event, date=timezone.localdate() + timedelta(days=7))
        self.detail_url = reverse('event_detail', kwargs={'slug': self.event.slug})
        self.join_url = reverse('event-join', kwargs={'slug': self.event.slug})
        self.leave_url = reverse('event-leave', kwargs={'slug': self.event.slug})
        self.client.force_login(self.user.user)

    def _conclude(self):
        self.date.date = timezone.localdate() - timedelta(days=1)
        self.date.save()

    def test_join_shows_the_share_modal_once(self):
        response = self.client.post(self.join_url, follow=True)
        self.assertTrue(response.context['just_joined'])
        self.assertContains(response, 'id="joined-dialog"')
        response = self.client.get(self.detail_url)
        self.assertFalse(response.context['just_joined'])
        self.assertNotContains(response, 'id="joined-dialog"')

    def test_participant_can_leave(self):
        EventParticipant.objects.create(event=self.event, user_profile=self.user)
        self.assertContains(self.client.get(self.detail_url), f'action="{self.leave_url}"')
        self.client.post(self.leave_url)
        self.assertFalse(self.event.participants.filter(user_profile=self.user).exists())

    def test_cannot_leave_a_concluded_event(self):
        EventParticipant.objects.create(event=self.event, user_profile=self.user)
        self._conclude()
        self.assertNotContains(self.client.get(self.detail_url), f'action="{self.leave_url}"')
        self.client.post(self.leave_url)
        self.assertTrue(self.event.participants.filter(user_profile=self.user).exists())

    def test_concluded_event_has_no_join_button(self):
        self._conclude()
        self.assertNotContains(self.client.get(self.detail_url), f'action="{self.join_url}"')
