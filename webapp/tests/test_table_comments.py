from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Comment, Event, Notification, NotificationType, Player
from webapp.tests.test_telegram_miniapp_bootstrap import make_table


class TableCommentsTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.participant = UserProfileFactory()
        self.stranger = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.table = make_table(location=self.location, author=UserProfileFactory())
        Player.objects.create(table=self.table, user_profile=self.participant)
        self.url = reverse('table-detail', kwargs={'slug': self.table.slug})

    def test_location_staff_can_comment_without_joining_and_notify_players(self):
        for profile in (self.owner, self.manager):
            with self.subTest(profile=profile):
                self.client.force_login(profile.user)
                self.assertContains(self.client.get(self.url), 'name="comment_form"')
                response = self.client.post(self.url, {
                    'comment_form': '', 'content': 'Informazioni importanti',
                })
                self.assertRedirects(response, self.url)
                self.assertTrue(Comment.objects.filter(
                    table=self.table, author=profile, content='Informazioni importanti').exists())
                self.assertFalse(self.table.players.filter(pk=profile.pk).exists())
        self.assertEqual(Notification.objects.filter(
            table=self.table, recipient=self.participant,
            notification_type=NotificationType.NEW_COMMENT).count(), 2)

    def test_participant_can_still_comment(self):
        self.client.force_login(self.participant.user)
        self.assertContains(self.client.get(self.url), 'name="comment_form"')
        self.assertRedirects(self.client.post(self.url, {
            'comment_form': '', 'content': 'Ci sono!',
        }), self.url)
        self.assertTrue(Comment.objects.filter(table=self.table, author=self.participant).exists())

    def test_unauthorized_users_cannot_see_form_or_post(self):
        elsewhere = LocationFactory(creator=UserProfileFactory())
        elsewhere.managers.add(self.stranger)
        for profile in (None, self.stranger, self.table.author):
            with self.subTest(profile=profile):
                self.client.logout()
                if profile:
                    self.client.force_login(profile.user)
                self.assertNotContains(self.client.get(self.url), 'name="comment_form"')
                response = self.client.post(self.url, {
                    'comment_form': '', 'content': 'Non autorizzato',
                })
                self.assertEqual(response.status_code, 403)
        self.assertFalse(Comment.objects.filter(table=self.table).exists())

    def test_event_comments_still_require_participation(self):
        event = Event.objects.create(name='Convention', creator=self.owner, status=Event.APPROVED)
        table = make_table(event=event, author=self.manager)
        url = reverse('event_table_detail', kwargs={
            'event_slug': event.slug, 'table_slug': table.slug,
        })
        self.client.force_login(self.owner.user)
        self.assertNotContains(self.client.get(url), 'name="comment_form"')
        self.assertEqual(self.client.post(url, {
            'comment_form': '', 'content': 'Info',
        }).status_code, 403)
        Player.objects.create(table=table, user_profile=self.owner)
        self.assertContains(self.client.get(url), 'name="comment_form"')
        self.assertRedirects(self.client.post(url, {
            'comment_form': '', 'content': 'Info',
        }), url)
