"""Duplicating a table into one or more future copies (campaigns, recurring games).

The main risk is notification spam: a series of copies must not notify the
location followers once per copy, nor fire the per-join notifications for every
copied player. Each copied player gets one TABLES_ADDED notification instead.
"""

import datetime
import io
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import (
    Event, GuestProfile, LocationFollower, Notification, NotificationType, Player, PushSubscription, Table,
    TableLink,
)
from webapp.services.tables import duplicate_draft, duplicate_table


def make_table(location=None, author=None, days_ahead=-3, **kwargs):
    return Table.objects.create(
        title=kwargs.pop('title', 'Campagna Gloomhaven'),
        description=kwargs.pop('description', 'Scenario successivo'),
        location=location,
        author=author,
        date=timezone.localdate() + datetime.timedelta(days=days_ahead),
        time=datetime.time(21, 0),
        **kwargs,
    )


def future(days):
    return timezone.localdate() + datetime.timedelta(days=days)


class DuplicateTableServiceTest(TestCase):
    def setUp(self):
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.source = make_table(
            location=self.location, author=self.author, game=GameFactory(),
            min_players=3, max_players=4, duration=180, external_players=1,
            custom_cover='table-covers/cover.jpg',
        )
        TableLink.objects.create(table=self.source, label='Regole', url='https://example.com/rules')
        self.players = [UserProfileFactory(), UserProfileFactory()]
        for profile in [self.author] + self.players:
            Player.objects.create(table=self.source, user_profile=profile, position=1, score=10)
        self.guest = GuestProfile.objects.create(owner=self.author, name='Zio')
        Player.objects.create(table=self.source, guest_profile=self.guest)
        Notification.objects.all().delete()

    def duplicate(self, dates, copy_players=False, links=(('Regole', 'https://example.com/rules'),)):
        return duplicate_table(
            self.source, duplicate_draft(self.source), dates, list(links), copy_players, by=self.author)

    def test_copies_fields_and_links_with_new_dates(self):
        copies = self.duplicate([future(14), future(7)])

        self.assertEqual([c.date for c in copies], [future(7), future(14)])
        for copy in copies:
            self.assertNotEqual(copy.slug, self.source.slug)
            self.assertEqual(copy.title, self.source.title)
            self.assertEqual(copy.description, self.source.description)
            self.assertEqual(copy.game_id, self.source.game_id)
            self.assertEqual((copy.min_players, copy.max_players, copy.duration), (3, 4, 180))
            self.assertEqual(copy.time, self.source.time)
            self.assertEqual(copy.author, self.author)
            self.assertEqual(copy.series_root, self.source)
            self.assertEqual(copy.custom_cover.name, 'table-covers/cover.jpg')
            self.assertEqual(copy.status, Table.OPEN)
            self.assertEqual(list(copy.links.values_list('label', 'url')),
                             [('Regole', 'https://example.com/rules')])

    def test_copies_of_a_copy_point_to_the_series_root(self):
        first = self.duplicate([future(7)])[0]

        second = duplicate_table(first, duplicate_draft(first), [future(14)], [], False, by=self.author)[0]

        self.assertEqual(second.series_root, self.source)
        self.assertEqual(set(self.source.series_copies.all()), {first, second})

    def test_without_players_nothing_is_copied_or_notified(self):
        copies = self.duplicate([future(7)])

        self.assertFalse(Player.objects.filter(table=copies[0]).exists())
        self.assertEqual(copies[0].external_players, 0)
        self.assertFalse(Notification.objects.exists())

    def test_players_guests_and_external_are_copied_with_fresh_results(self):
        copies = self.duplicate([future(7), future(14)], copy_players=True)

        for copy in copies:
            rows = Player.objects.filter(table=copy)
            self.assertEqual(
                set(rows.exclude(user_profile=None).values_list('user_profile_id', flat=True)),
                {self.author.id} | {p.id for p in self.players})
            self.assertTrue(rows.filter(guest_profile=self.guest).exists())
            self.assertEqual(set(rows.values_list('score', flat=True)), {0})
            self.assertEqual(copy.external_players, 1)

    def test_one_notification_per_added_player_for_the_whole_series(self):
        copies = self.duplicate([future(7), future(14), future(21)], copy_players=True)

        notifications = Notification.objects.all()
        # Only the two other players: neither the duplicating user nor the guest
        self.assertEqual(
            sorted(notifications.values_list('recipient_id', flat=True)), sorted(p.id for p in self.players))
        self.assertEqual(set(notifications.values_list('notification_type', flat=True)),
                         {NotificationType.TABLES_ADDED})
        self.assertEqual(notifications.first().table, copies[0])
        self.assertEqual(notifications.first().message,
                         ', '.join(d.strftime('%d/%m/%Y') for d in (future(7), future(14), future(21))))

    def test_location_followers_are_not_notified(self):
        LocationFollower.objects.create(user_profile=UserProfileFactory(), location=self.location)

        self.duplicate([future(7), future(14)])

        self.assertFalse(Notification.objects.filter(notification_type=NotificationType.NEW_TABLE).exists())

    def test_a_normal_new_table_still_notifies_followers(self):
        LocationFollower.objects.create(user_profile=UserProfileFactory(), location=self.location)

        make_table(location=self.location, author=self.author, days_ahead=7)

        self.assertTrue(Notification.objects.filter(notification_type=NotificationType.NEW_TABLE).exists())


    def test_players_and_location_are_not_queried_once_per_row(self):
        with CaptureQueriesContext(connection) as queries:
            self.duplicate([future(7), future(14), future(21)], copy_players=True)

        selects = [q['sql'] for q in queries if q['sql'].startswith('SELECT')]
        self.assertEqual(len([sql for sql in selects if 'FROM "webapp_player"' in sql]), 1)
        self.assertFalse([sql for sql in selects if 'FROM "webapp_location"' in sql])


@override_settings(AWS_SES_REGION_NAME='eu', AWS_SES_ACCESS_KEY_ID='key', AWS_SES_SECRET_ACCESS_KEY='secret')
class TablesAddedEmailPreferenceTest(TestCase):
    def setUp(self):
        self.table = make_table(location=LocationFactory(creator=UserProfileFactory()), author=UserProfileFactory())
        self.recipient = UserProfileFactory()
        self.notification = Notification.objects.create(
            recipient=self.recipient, table=self.table, location=self.table.location,
            notification_type=NotificationType.TABLES_ADDED, message='07/11/2026, 14/11/2026',
        )

    def send(self):
        client = mock.Mock()
        client.send_bulk_email.return_value = {'BulkEmailEntryResults': []}
        with mock.patch('webapp.management.commands.send_queued_notifications.boto3.client', return_value=client):
            call_command('send_queued_notifications', stdout=io.StringIO())
        self.notification.refresh_from_db()
        return client

    def test_email_is_sent_when_new_table_emails_are_on(self):
        client = self.send()

        client.send_bulk_email.assert_called_once()
        self.assertEqual(
            client.send_bulk_email.call_args.kwargs['DefaultContent']['Template']['TemplateName'],
            'TablesAddedNotification')
        self.assertTrue(self.notification.sent)

    def test_email_is_skipped_when_new_table_emails_are_off(self):
        self.recipient.notification_new_table = False
        self.recipient.save(update_fields=['notification_new_table'])

        client = self.send()

        client.send_bulk_email.assert_not_called()
        self.assertTrue(self.notification.sent)


@override_settings(VAPID_PRIVATE_KEY='private', VAPID_PUBLIC_KEY='public', VAPID_CLAIM_EMAIL='test@example.com')
class TablesAddedPushPreferenceTest(TestCase):
    def setUp(self):
        self.table = make_table(location=LocationFactory(creator=UserProfileFactory()), author=UserProfileFactory())
        self.recipient = UserProfileFactory()
        PushSubscription.objects.create(
            user_profile=self.recipient, endpoint='https://push.example.com/1', p256dh='key', auth='auth')
        self.notification = Notification.objects.create(
            recipient=self.recipient, table=self.table, location=self.table.location,
            notification_type=NotificationType.TABLES_ADDED, message='07/11/2026, 14/11/2026',
        )

    def send(self):
        with mock.patch('webapp.management.commands.send_push_notifications.webpush') as webpush:
            call_command('send_push_notifications', stdout=io.StringIO())
        self.notification.refresh_from_db()
        return webpush

    def test_push_is_sent_when_new_table_pushes_are_on(self):
        self.send().assert_called_once()

    def test_push_is_skipped_when_new_table_pushes_are_off(self):
        self.recipient.push_notification_new_table = False
        self.recipient.save(update_fields=['push_notification_new_table'])

        self.send().assert_not_called()
        self.assertTrue(self.notification.push_sent)


class DuplicateTableViewTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.source = make_table(location=self.location, author=self.author)
        TableLink.objects.create(table=self.source, label='Regole', url='https://example.com/rules')
        self.url = reverse('table-duplicate', kwargs={'slug': self.source.slug})

    def post_data(self, dates, **extra):
        data = {
            'title': self.source.title,
            'description': self.source.description,
            'game': '',
            'min_players': 2,
            'max_players': 5,
            'time': '21:00',
            'dates': [d.isoformat() for d in dates],
            # The prefilled link row, posted as rendered
            'links-TOTAL_FORMS': 1,
            'links-INITIAL_FORMS': 0,
            'links-0-label': 'Regole',
            'links-0-url': 'https://example.com/rules',
        }
        data.update(extra)
        return data

    def test_author_and_location_owner_can_open_the_page(self):
        for profile in (self.author, self.owner):
            self.client.force_login(profile.user)
            response = self.client.get(self.url)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'https://example.com/rules')
            self.assertTrue(response.context['links_formset_open'])

    def test_page_shows_summary_and_copy_option_even_without_players(self):
        self.client.force_login(self.author.user)

        response = self.client.get(self.url)

        self.assertContains(response, 'id="details-summary"')
        self.assertContains(response, 'id="details-fieldset" class="space-y-5 min-w-0 border-0 p-0 m-0" style="display:none"')
        # No participants: the option is shown but cannot be ticked
        self.assertContains(response, 'name="copy_players" id="copy_players" disabled')

    def test_stranger_is_refused(self):
        self.client.force_login(UserProfileFactory().user)

        response = self.client.get(self.url)

        self.assertRedirects(response, reverse('table-detail', kwargs={'slug': self.source.slug}))

    def test_event_tables_cannot_be_duplicated(self):
        event = Event.objects.create(name='Con', creator=self.owner)
        table = make_table(author=self.author, event=event)
        self.client.force_login(self.author.user)

        response = self.client.get(reverse('table-duplicate', kwargs={'slug': table.slug}))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Table.objects.filter(series_root=table).count(), 0)

    def test_post_creates_one_table_per_date_and_keeps_untouched_links(self):
        self.client.force_login(self.author.user)

        response = self.client.post(self.url, self.post_data([future(7), future(14)]))

        copies = Table.objects.filter(series_root=self.source).order_by('date')
        self.assertEqual([c.date for c in copies], [future(7), future(14)])
        self.assertRedirects(response, reverse('table-detail', kwargs={'slug': copies[0].slug}))
        for copy in copies:
            self.assertEqual(copy.links.count(), 1)

    def test_emptied_link_row_is_dropped(self):
        self.client.force_login(self.author.user)

        self.client.post(self.url, self.post_data([future(7)], **{'links-0-label': '', 'links-0-url': ''}))

        self.assertFalse(TableLink.objects.filter(table__series_root=self.source).exists())

    def test_max_below_min_shows_the_error_with_the_details_open(self):
        self.client.force_login(self.author.user)

        response = self.client.post(self.url, self.post_data([future(7)], min_players=5, max_players=2))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['details_unlocked'])
        self.assertContains(response, response.context['form'].errors['max_players'][0])
        self.assertFalse(Table.objects.filter(series_root=self.source).exists())

    def test_create_page_shows_the_max_below_min_error(self):
        self.client.force_login(self.owner.user)

        response = self.client.post(
            reverse('location-table-create', kwargs={'location_slug': self.location.slug}),
            {'title': 'Nuovo tavolo', 'description': 'Descrizione', 'date': future(7).isoformat(), 'time': '21:00',
             'min_players': 5, 'max_players': 2, 'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, response.context['form'].errors['max_players'][0])

    def test_invalid_dates_are_refused(self):
        self.client.force_login(self.author.user)
        cases = [
            [],
            [timezone.localdate() - datetime.timedelta(days=1)],
            [future(i) for i in range(1, 17)],
        ]
        for dates in cases:
            response = self.client.post(self.url, self.post_data(dates))
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors.get('dates'))
        self.assertFalse(Table.objects.filter(series_root=self.source).exists())

    def test_detail_page_shows_the_button_only_to_who_may_duplicate(self):
        detail = reverse('table-detail', kwargs={'slug': self.source.slug})

        self.client.force_login(self.author.user)
        self.assertContains(self.client.get(detail), self.url)

        self.client.force_login(UserProfileFactory().user)
        self.assertNotContains(self.client.get(detail), self.url)
