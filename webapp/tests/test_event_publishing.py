import datetime

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate


class EventPublishingTest(TestCase):
    """Events start as drafts that their managers publish themselves; the admin
    hears about each publication and can block an event, which managers can't undo."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.event = Event.objects.create(
            name="Con", slug="con", creator=self.owner, description="Games all weekend")
        EventDate.objects.create(event=self.event, date=timezone.localdate() + datetime.timedelta(days=5))
        self.client.force_login(self.owner.user)
        mail.outbox = []

    def _url(self, name):
        return reverse(name, kwargs={'slug': self.event.slug})

    def _refresh_status(self):
        self.event.refresh_from_db()
        return self.event.status

    def test_new_event_is_a_draft_and_notifies_nobody(self):
        response = self.client.post(reverse('event-create'), {'name': 'Big Con', 'city': 'Milano'})
        event = Event.objects.get(name='Big Con')
        self.assertEqual(event.status, Event.DRAFT)
        self.assertRedirects(response, reverse('event-manage', kwargs={'slug': event.slug}),
                             fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(ADMIN_PERSONAL_EMAIL='admin@example.com')
    def test_manager_publishes_and_admin_is_notified(self):
        manager = UserProfileFactory()
        self.event.managers.add(manager)
        self.client.force_login(manager.user)
        response = self.client.post(self._url('event-manage-publish'))
        self.assertRedirects(response, self._url('event-manage'), fetch_redirect_response=False)
        self.assertEqual(self._refresh_status(), Event.PUBLISHED)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['admin@example.com'])
        self.assertIn('Con', message.subject)
        self.assertIn(manager.nickname, message.body)
        self.assertIn(reverse('admin:webapp_event_change', args=[self.event.pk]), message.body)

    @override_settings(ADMIN_PERSONAL_EMAIL='')
    def test_no_mail_without_admin_address(self):
        self.client.post(self._url('event-manage-publish'))
        self.assertEqual(self._refresh_status(), Event.PUBLISHED)
        self.assertEqual(len(mail.outbox), 0)

    def test_publishing_needs_a_date_and_a_description(self):
        self.event.dates.all().delete()
        self.event.description = "  "
        self.event.save()
        response = self.client.get(self._url('event-manage'))
        self.assertEqual(len(response.context['missing_publish_requirements']), 2)
        self.client.post(self._url('event-manage-publish'))
        self.assertEqual(self._refresh_status(), Event.DRAFT)

    def test_blocked_event_cannot_be_published(self):
        Event.objects.filter(pk=self.event.pk).update(status=Event.BLOCKED)
        self.client.post(self._url('event-manage-publish'))
        self.assertEqual(self._refresh_status(), Event.BLOCKED)
        self.client.post(self._url('event-manage-unpublish'))
        self.assertEqual(self._refresh_status(), Event.BLOCKED)

    def test_outsider_cannot_publish_or_unpublish(self):
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.post(self._url('event-manage-publish')).status_code, 403)
        self.assertEqual(self._refresh_status(), Event.DRAFT)
        Event.objects.filter(pk=self.event.pk).update(status=Event.PUBLISHED)
        self.assertEqual(self.client.post(self._url('event-manage-unpublish')).status_code, 403)
        self.assertEqual(self._refresh_status(), Event.PUBLISHED)

    def test_back_to_draft_hides_the_event(self):
        Event.objects.filter(pk=self.event.pk).update(status=Event.PUBLISHED)
        self.client.post(self._url('event-manage-unpublish'))
        self.assertEqual(self._refresh_status(), Event.DRAFT)
        self.client.logout()
        self.assertEqual(self.client.get(self._url('event_detail')).status_code, 404)

    def test_draft_banner_only_while_unpublished(self):
        for name in ('event_detail', 'event-program', 'event-games'):
            with self.subTest(page=name):
                response = self.client.get(self._url(name))
                self.assertContains(response, self._url('event-manage'))
                self.assertContains(response, "Bozza")
        Event.objects.filter(pk=self.event.pk).update(status=Event.PUBLISHED)
        response = self.client.get(self._url('event-program'))
        self.assertNotContains(response, "non è ancora visibile al pubblico")
