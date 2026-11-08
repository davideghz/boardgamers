from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import Event


class EventAdminNotificationTest(TestCase):
    """Creating an event sends a mail to ADMIN_PERSONAL_EMAIL, who approves it."""

    def setUp(self):
        self.creator = UserProfileFactory()
        self.client.force_login(self.creator.user)
        mail.outbox = []

    def _create_event(self):
        return self.client.post(reverse('event-create'), {'name': 'Big Con', 'city': 'Milano'})

    @override_settings(ADMIN_PERSONAL_EMAIL='admin@example.com')
    def test_admin_is_notified(self):
        response = self._create_event()
        event = Event.objects.get(name='Big Con')
        self.assertRedirects(response, reverse('event-manage', kwargs={'slug': event.slug}),
                             fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['admin@example.com'])
        self.assertIn('Big Con', message.subject)
        self.assertIn(reverse('admin:webapp_event_change', args=[event.pk]), message.body)

    @override_settings(ADMIN_PERSONAL_EMAIL='')
    def test_no_mail_without_address(self):
        self._create_event()
        self.assertTrue(Event.objects.filter(name='Big Con').exists())
        self.assertEqual(len(mail.outbox), 0)
