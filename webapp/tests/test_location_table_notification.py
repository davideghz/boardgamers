import datetime
import io
import json
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import LocationFollower, Notification, NotificationType, PhysicalTable, PlayArea, Table


class LocationManagersNewTableEmailTest(TestCase):
    """Creating a table at a location mails its owner and managers (not the author)."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.url = reverse('location-table-create', kwargs={'location_slug': self.location.slug})
        mail.outbox = []

    def _create_table(self, author=None, **extra):
        self.client.force_login((author or self.author).user)
        data = {
            'title': 'Serata', 'description': 'Una serata', 'date': '2030-01-10', 'time': '21:00',
            'min_players': 2, 'max_players': 4, 'location': self.location.pk,
            'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0,
        }
        data.update(extra)
        self.client.post(self.url, data)
        return Table.objects.get(location=self.location)

    def test_owner_and_managers_are_notified(self):
        self._create_table()

        recipients = sorted(address for message in mail.outbox for address in message.to)
        self.assertEqual(recipients, sorted([self.owner.user.email, self.manager.user.email]))
        self.assertIn('Serata', mail.outbox[0].subject)

    def test_the_author_is_not_notified(self):
        self._create_table(author=self.manager)

        self.assertEqual([message.to for message in mail.outbox], [[self.owner.user.email]])

    def test_without_stations_the_mail_links_the_table(self):
        table = self._create_table()

        body = mail.outbox[0].body
        self.assertIn(reverse('table-detail', kwargs={'slug': table.slug}), body)
        self.assertNotIn(reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': table.slug}), body)

    def test_with_stations_the_mail_suggests_assigning_one(self):
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')

        table = self._create_table()

        edit_url = reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': table.slug})
        self.assertIn(edit_url, mail.outbox[0].body)
        self.assertIn(edit_url, mail.outbox[0].alternatives[0][0])

    def test_no_suggestion_when_a_station_is_already_assigned(self):
        area = PlayArea.objects.create(location=self.location, name='Sala A')
        station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1', play_area=area)

        table = self._create_table(play_area=area.pk, physical_table=station.pk)

        self.assertEqual(table.physical_table, station)
        self.assertNotIn(reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': table.slug}), mail.outbox[0].body)
        self.assertIn('Tavolo 1', mail.outbox[0].body)

    def test_a_manager_following_the_location_gets_only_the_follower_mail(self):
        LocationFollower.objects.create(location=self.location, user_profile=self.manager)

        self._create_table()

        self.assertEqual([message.to for message in mail.outbox], [[self.owner.user.email]])
        self.assertTrue(Notification.objects.filter(
            recipient=self.manager, notification_type=NotificationType.NEW_TABLE).exists())

    def test_a_follower_with_new_table_mails_off_gets_the_manager_mail(self):
        LocationFollower.objects.create(location=self.location, user_profile=self.manager)
        self.manager.notification_new_table = False
        self.manager.save()

        self._create_table()

        recipients = sorted(address for message in mail.outbox for address in message.to)
        self.assertEqual(recipients, sorted([self.owner.user.email, self.manager.user.email]))


@override_settings(AWS_SES_REGION_NAME='eu', AWS_SES_ACCESS_KEY_ID='key', AWS_SES_SECRET_ACCESS_KEY='secret')
class FollowerMailStationSuggestionTest(TestCase):
    """The queued follower mail carries the "assign a station" link, for location staff only."""

    def setUp(self):
        self.manager = UserProfileFactory()
        self.follower = UserProfileFactory()
        self.location = LocationFactory()
        self.location.managers.add(self.manager)
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')
        self.table = Table.objects.create(
            title='Serata', description='Una serata', author=UserProfileFactory(), location=self.location,
            date=datetime.date(2030, 1, 10), time=datetime.time(21, 0),
        )

    def _template_data(self):
        for profile in (self.manager, self.follower):
            Notification.objects.create(
                recipient=profile, table=self.table, location=self.location,
                notification_type=NotificationType.NEW_TABLE)
        client = mock.Mock()
        client.send_bulk_email.return_value = {'BulkEmailEntryResults': []}
        with mock.patch('webapp.management.commands.send_queued_notifications.boto3.client', return_value=client):
            call_command('send_queued_notifications', stdout=io.StringIO())
        entries = client.send_bulk_email.call_args.kwargs['BulkEmailEntries']
        return {
            entry['Destination']['ToAddresses'][0]:
                json.loads(entry['ReplacementEmailContent']['ReplacementTemplate']['ReplacementTemplateData'])
            for entry in entries
        }

    def test_only_the_manager_gets_the_station_link(self):
        data = self._template_data()

        edit_url = reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': self.table.slug})
        self.assertTrue(data[self.manager.user.email]['assign_station_href'].endswith(edit_url))
        self.assertEqual(data[self.follower.user.email]['assign_station_href'], '')
