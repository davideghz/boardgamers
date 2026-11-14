from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Comment, Event, Notification, NotificationType, Player
from webapp.services.tables import COMMENT_BADGE_MANAGER, COMMENT_BADGE_ORGANIZER, comment_badges


class TableCommentsTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.participant = UserProfileFactory()
        self.stranger = UserProfileFactory()
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.table = TableFactory(location=self.location, author=self.author)
        Player.objects.create(table=self.table, user_profile=self.participant)
        self.url = reverse('table-detail', kwargs={'slug': self.table.slug})

    def post_comment(self, url, content='Info'):
        return self.client.post(url, {'comment_form': '', 'content': content})

    def test_author_and_location_staff_can_comment_without_joining_and_notify_players(self):
        for profile in (self.author, self.owner, self.manager):
            with self.subTest(profile=profile):
                self.client.force_login(profile.user)
                self.assertContains(self.client.get(self.url), 'name="comment_form"')
                response = self.post_comment(self.url, 'Informazioni importanti')
                self.assertRedirects(response, self.url)
                self.assertTrue(Comment.objects.filter(
                    table=self.table, author=profile, content='Informazioni importanti').exists())
                self.assertFalse(self.table.players.filter(pk=profile.pk).exists())
        self.assertEqual(Notification.objects.filter(
            table=self.table, recipient=self.participant,
            notification_type=NotificationType.NEW_COMMENT).count(), 3)

    def test_participant_can_still_comment(self):
        self.client.force_login(self.participant.user)
        self.assertContains(self.client.get(self.url), 'name="comment_form"')
        self.assertRedirects(self.post_comment(self.url, 'Ci sono!'), self.url)
        self.assertTrue(Comment.objects.filter(table=self.table, author=self.participant).exists())

    def test_unauthorized_users_cannot_see_form_or_post(self):
        elsewhere = LocationFactory(creator=UserProfileFactory())
        elsewhere.managers.add(self.stranger)
        for profile in (None, self.stranger):
            with self.subTest(profile=profile):
                self.client.logout()
                if profile:
                    self.client.force_login(profile.user)
                self.assertNotContains(self.client.get(self.url), 'name="comment_form"')
                self.assertEqual(self.post_comment(self.url, 'Non autorizzato').status_code, 403)
        self.assertFalse(Comment.objects.filter(table=self.table).exists())

    def test_event_author_and_managers_can_comment_without_joining(self):
        event_creator, event_manager = UserProfileFactory(), UserProfileFactory()
        event = Event.objects.create(name='Convention', creator=event_creator, status=Event.APPROVED)
        event.managers.add(event_manager)
        table = TableFactory(location=None, event=event, author=self.author)
        url = reverse('event_table_detail', kwargs={'event_slug': event.slug, 'table_slug': table.slug})
        for profile in (self.author, event_creator, event_manager):
            with self.subTest(profile=profile):
                self.client.force_login(profile.user)
                self.assertContains(self.client.get(url), 'name="comment_form"')
                self.assertRedirects(self.post_comment(url), url)

        # The location staff has no say on an event table: they have to join it
        self.client.force_login(self.owner.user)
        self.assertNotContains(self.client.get(url), 'name="comment_form"')
        self.assertEqual(self.post_comment(url).status_code, 403)
        Player.objects.create(table=table, user_profile=self.owner)
        self.assertRedirects(self.post_comment(url), url)

    def test_comments_of_organizer_and_managers_have_a_badge(self):
        for profile in (self.author, self.owner, self.manager, self.participant):
            Comment.objects.create(table=self.table, author=profile, content='Ciao')
        badges = comment_badges(self.table, self.table.comments.all())
        self.assertEqual(badges, {
            self.author.id: COMMENT_BADGE_ORGANIZER,
            self.owner.id: COMMENT_BADGE_MANAGER,
            self.manager.id: COMMENT_BADGE_MANAGER,
        })

        response = self.client.get(self.url)
        self.assertEqual({c.author_id: c.badge for c in response.context['comments']}, {
            self.author.id: COMMENT_BADGE_ORGANIZER,
            self.owner.id: COMMENT_BADGE_MANAGER,
            self.manager.id: COMMENT_BADGE_MANAGER,
            self.participant.id: None,
        })

    def test_badges_cost_no_query_when_no_author_may_be_a_manager(self):
        Comment.objects.create(table=self.table, author=self.author, content='Ciao')
        Comment.objects.create(table=self.table, author=self.owner, content='Ciao')
        comments = list(self.table.comments.all())
        table = type(self.table).objects.select_related('location').get(pk=self.table.pk)
        with self.assertNumQueries(0):
            comment_badges(table, comments)
