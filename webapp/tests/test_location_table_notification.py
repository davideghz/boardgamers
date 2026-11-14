import datetime
import io
import json
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import LocationFollower, Notification, NotificationType, PhysicalTable, PlayArea, Table


class NewTableNotificationRecipientsTest(TestCase):
    """A new table queues a NEW_TABLE notification for the followers and, when the
    table could get a station, for the location owner and managers too."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.follower = UserProfileFactory()
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        LocationFollower.objects.create(location=self.location, user_profile=self.follower)
        self.url = reverse('location-table-create', kwargs={'location_slug': self.location.slug})

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

    def _recipients(self, table):
        return sorted(Notification.objects.filter(
            table=table, notification_type=NotificationType.NEW_TABLE).values_list('recipient_id', flat=True))

    def test_without_stations_only_the_followers_are_notified(self):
        table = self._create_table()

        self.assertEqual(self._recipients(table), [self.follower.id])

    def test_with_stations_the_staff_is_notified_too(self):
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')

        table = self._create_table()

        self.assertEqual(self._recipients(table), sorted([self.owner.id, self.manager.id, self.follower.id]))

    def test_the_author_is_not_added_as_staff(self):
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')

        table = self._create_table(author=self.manager)

        self.assertEqual(self._recipients(table), sorted([self.owner.id, self.follower.id]))

    def test_a_manager_who_follows_gets_a_single_notification(self):
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')
        LocationFollower.objects.create(location=self.location, user_profile=self.manager)

        table = self._create_table()

        self.assertEqual(self._recipients(table), sorted([self.owner.id, self.manager.id, self.follower.id]))

    def test_no_staff_when_a_station_is_already_assigned(self):
        area = PlayArea.objects.create(location=self.location, name='Sala A')
        station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1', play_area=area)

        table = self._create_table(play_area=area.pk, physical_table=station.pk)

        self.assertEqual(table.physical_table, station)
        self.assertEqual(self._recipients(table), [self.follower.id])


@override_settings(AWS_SES_REGION_NAME='eu', AWS_SES_ACCESS_KEY_ID='key', AWS_SES_SECRET_ACCESS_KEY='secret')
class NewTableMailStationSuggestionTest(TestCase):
    """The queued mail carries the "assign a station" link, for location staff only."""

    def setUp(self):
        self.manager = UserProfileFactory()
        self.follower = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory())
        self.location.managers.add(self.manager)
        LocationFollower.objects.create(location=self.location, user_profile=self.follower)
        self.station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1')
        self.table = Table.objects.create(
            title='Serata', description='Una serata', author=UserProfileFactory(), location=self.location,
            date=datetime.date(2030, 1, 10), time=datetime.time(21, 0),
        )
        self.edit_url = reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': self.table.slug})

    def _template_data(self):
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

    def test_only_the_staff_gets_the_station_link(self):
        data = self._template_data()

        self.assertTrue(data[self.manager.user.email]['assign_station_href'].endswith(self.edit_url))
        self.assertTrue(data[self.location.creator.user.email]['assign_station_href'].endswith(self.edit_url))
        self.assertEqual(data[self.follower.user.email]['assign_station_href'], '')

    def test_no_link_when_a_station_was_assigned_before_sending(self):
        Table.objects.filter(pk=self.table.pk).update(physical_table=self.station)

        data = self._template_data()

        self.assertEqual(data[self.manager.user.email]['assign_station_href'], '')

    def test_the_query_count_does_not_grow_with_the_followers(self):
        with CaptureQueriesContext(connection) as few:
            self._template_data()
        for _ in range(10):
            LocationFollower.objects.create(location=self.location, user_profile=UserProfileFactory())
        Table.objects.create(
            title='Altra', author=UserProfileFactory(), location=self.location,
            date=datetime.date(2030, 1, 11), time=datetime.time(21, 0),
        )

        with CaptureQueriesContext(connection) as many:
            self._template_data()

        self.assertEqual(len(many), len(few))
