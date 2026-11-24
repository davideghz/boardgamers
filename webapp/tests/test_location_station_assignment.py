import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import PhysicalTable, PlayArea, Table


class LocationStationAssignmentTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.regular_user = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.area = PlayArea.objects.create(location=self.location, name='Sala A')
        self.station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1', play_area=self.area)
        self.tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        self.table = self._table('Serata')
        self.url = reverse('location-manage-station-assignment', kwargs={'slug': self.location.slug})

    def _table(self, title, location=None, date=None, time=datetime.time(21, 0), **extra):
        return Table.objects.create(
            title=title, description='Una serata', author=self.owner, location=location or self.location,
            date=date or self.tomorrow, time=time, **extra)

    def test_regular_user_is_forbidden(self):
        self.client.force_login(self.regular_user.user)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.post(self.url, {'table': self.table.pk, 'physical_table': self.station.pk})
        self.table.refresh_from_db()
        self.assertIsNone(self.table.physical_table)

    def test_lists_only_upcoming_tables_of_the_location(self):
        self._table('Ieri', date=timezone.localdate() - datetime.timedelta(days=1))
        self._table('Altrove', location=LocationFactory(name='Other', slug='other'))
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url)

        self.assertContains(response, 'Serata')
        self.assertNotContains(response, 'Ieri')
        self.assertNotContains(response, 'Altrove')

    def test_assigning_a_station_also_sets_its_area(self):
        self.client.force_login(self.owner.user)

        self.client.post(self.url, {'table': self.table.pk, 'physical_table': self.station.pk})

        self.table.refresh_from_db()
        self.assertEqual((self.table.physical_table, self.table.play_area), (self.station, self.area))
        response = self.client.get(reverse('table-detail', kwargs={'slug': self.table.slug}))
        self.assertContains(response, 'Tavolo 1')

    def test_removing_the_station(self):
        self.table.physical_table = self.station
        self.table.save()
        self.client.force_login(self.owner.user)

        self.client.post(self.url, {'table': self.table.pk, 'physical_table': ''})

        self.table.refresh_from_db()
        self.assertIsNone(self.table.physical_table)

    def test_cannot_assign_foreign_stations_or_tables(self):
        other = LocationFactory(name='Other', slug='other')
        foreign_station = PhysicalTable.objects.create(location=other, name='T')
        foreign_table = self._table('Altrove', location=other)
        self.client.force_login(self.owner.user)

        response = self.client.post(self.url, {'table': self.table.pk, 'physical_table': foreign_station.pk})
        self.assertEqual(response.status_code, 404)
        response = self.client.post(self.url, {'table': foreign_table.pk, 'physical_table': self.station.pk})
        self.assertEqual(response.status_code, 404)

    def test_overlapping_bookings_are_flagged_but_allowed(self):
        other = self._table('Altra serata', time=datetime.time(22, 0), physical_table=self.station)
        self.client.force_login(self.owner.user)

        response = self.client.post(self.url, {'table': self.table.pk, 'physical_table': self.station.pk},
                                    follow=True)

        self.table.refresh_from_db()
        self.assertEqual(self.table.physical_table, self.station)
        self.assertEqual({self.table.id, other.id}, response.context['conflict_ids'])

    def test_unassigned_filter(self):
        self._table('Assegnato', physical_table=self.station)
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url + '?unassigned=1')

        self.assertContains(response, 'Serata')
        self.assertNotContains(response, 'Assegnato')

    def test_without_stations_it_links_to_their_creation(self):
        self.station.delete()
        self.client.force_login(self.owner.user)

        response = self.client.get(self.url)

        self.assertContains(response, reverse('location-manage-stations', kwargs={'slug': self.location.slug}))
        self.assertNotContains(response, 'name="physical_table"')
