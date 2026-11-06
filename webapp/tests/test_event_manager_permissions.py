from django.test import TestCase
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import Event, PlayArea


class EventManagerPermissionsTest(TestCase):
    """A user who doesn't manage the event must not be able to change anything:
    the permission check has to run before the view, not after it."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.event = Event.objects.create(name="Con", slug="con", creator=self.owner, status=Event.APPROVED)
        self.client.force_login(self.outsider.user)

    def test_outsider_cannot_become_manager(self):
        response = self.client.post(
            reverse('event-manage-managers', kwargs={'slug': self.event.slug}),
            {'manager': self.outsider.pk})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.event.managers.filter(pk=self.outsider.pk).exists())

    def test_outsider_cannot_delete_data(self):
        area = PlayArea.objects.create(event=self.event, name="Hall")
        response = self.client.post(
            reverse('event-manage-area-delete', kwargs={'slug': self.event.slug, 'pk': area.pk}))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PlayArea.objects.filter(pk=area.pk).exists())

    def test_manager_still_allowed(self):
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('event-manage-areas', kwargs={'slug': self.event.slug}))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse('event-manage-areas', kwargs={'slug': self.event.slug}))
        self.assertEqual(response.status_code, 302)
