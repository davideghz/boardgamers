import datetime
import json

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.forms import PhysicalTableForm, PlayAreaForm, TableForm
from webapp.models import Event, PhysicalTable, PlayArea, Table

# Management form of the (empty) extra-links formset posted with the table form.
LINKS_MANAGEMENT = {'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0}


class LocationPlayAreaManagementTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.regular_user = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.other_location = LocationFactory(name='Other', slug='other')
        self.url = reverse('location-manage-areas', kwargs={'slug': self.location.slug})

    def test_only_owner_and_managers_can_access(self):
        for profile in (self.owner, self.manager):
            self.client.force_login(profile.user)
            self.assertEqual(self.client.get(self.url).status_code, 200)

        self.client.force_login(self.regular_user.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'name': 'Sala A'}).status_code, 403)
        self.assertFalse(PlayArea.objects.exists())

    def test_manager_adds_areas_in_order(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.url, {'name': 'Sala A'})
        self.client.post(self.url, {'name': 'Sala B'})

        areas = list(self.location.play_areas.values_list('name', 'order'))
        self.assertEqual(areas, [('Sala A', 1), ('Sala B', 2)])
        self.assertIsNone(self.location.play_areas.first().event)

    def test_duplicate_name_is_a_form_error(self):
        PlayArea.objects.create(location=self.location, name='Sala A')
        self.client.force_login(self.owner.user)

        response = self.client.post(self.url, {'name': 'Sala A'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.location.play_areas.count(), 1)

    def test_same_name_allowed_on_another_location(self):
        PlayArea.objects.create(location=self.other_location, name='Sala A')

        form = PlayAreaForm(data={'name': 'Sala A'}, location=self.location)

        self.assertTrue(form.is_valid())

    def test_delete_and_reorder_ignore_areas_of_other_locations(self):
        own = PlayArea.objects.create(location=self.location, name='Sala A', order=1)
        foreign = PlayArea.objects.create(location=self.other_location, name='Sala B', order=1)
        self.client.force_login(self.owner.user)

        self.client.post(
            reverse('location-manage-areas-reorder', kwargs={'slug': self.location.slug}),
            data=json.dumps({'areas': [{'id': own.pk, 'order': 5}, {'id': foreign.pk, 'order': 9}]}),
            content_type='application/json',
        )
        self.client.post(reverse('location-manage-area-delete',
                                 kwargs={'slug': self.location.slug, 'pk': foreign.pk}))

        own.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(own.order, 5)
        self.assertEqual(foreign.order, 1)

    def test_area_belongs_to_exactly_one_of_event_or_location(self):
        event = Event.objects.create(name='Con')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlayArea.objects.create(name='Nowhere')
        with self.assertRaises(IntegrityError), transaction.atomic():
            PlayArea.objects.create(name='Both', event=event, location=self.location)


class LocationTablePlayAreaTest(TestCase):
    def setUp(self):
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.author)
        self.area = PlayArea.objects.create(location=self.location, name='Sala A')
        self.foreign_area = PlayArea.objects.create(
            location=LocationFactory(name='Other', slug='other'), name='Sala B')
        self.event_area = PlayArea.objects.create(event=Event.objects.create(name='Con'), name='Sala C')

    def _data(self, area):
        return {
            'title': 'Serata', 'description': 'Una serata', 'date': '2030-01-10', 'time': '21:00',
            'min_players': 2, 'max_players': 4, 'location': self.location.pk, 'play_area': area.pk,
            **LINKS_MANAGEMENT,
        }

    def test_form_offers_only_the_location_areas(self):
        form = TableForm(location=self.location)

        self.assertQuerySetEqual(form.fields['play_area'].queryset, [self.area])

    def test_form_rejects_areas_of_other_locations_and_events(self):
        for area in (self.foreign_area, self.event_area):
            form = TableForm(data=self._data(area), location=self.location)
            self.assertFalse(form.is_valid())
            self.assertIn('play_area', form.errors)

    def test_create_table_with_area_and_show_it(self):
        self.client.force_login(self.author.user)

        self.client.post(
            reverse('location-table-create', kwargs={'location_slug': self.location.slug}),
            self._data(self.area))

        table = Table.objects.get(location=self.location)
        self.assertEqual(table.play_area, self.area)
        response = self.client.get(reverse('table-detail', kwargs={'slug': table.slug}))
        self.assertContains(response, 'Sala A')

    def test_deleting_an_area_keeps_the_table(self):
        table = Table.objects.create(
            title='Serata', description='Una serata', date=datetime.date(2030, 1, 10),
            time=datetime.time(21, 0), author=self.author, location=self.location, play_area=self.area)

        self.area.delete()

        table.refresh_from_db()
        self.assertIsNone(table.play_area)


class LocationStationManagementTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.regular_user = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.other_location = LocationFactory(name='Other', slug='other')
        self.area = PlayArea.objects.create(location=self.location, name='Sala A')
        self.area_b = PlayArea.objects.create(location=self.location, name='Sala B')
        self.url = reverse('location-manage-stations', kwargs={'slug': self.location.slug})

    def _edit_url(self, station):
        return reverse('location-manage-station-edit', kwargs={'slug': self.location.slug, 'pk': station.pk})

    def test_regular_user_is_forbidden(self):
        station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1')
        self.client.force_login(self.regular_user.user)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {'name': 'Tavolo 2'}).status_code, 403)
        self.assertEqual(self.client.post(self._edit_url(station), {'name': 'X'}).status_code, 403)
        self.assertEqual(PhysicalTable.objects.count(), 1)

    def test_owner_adds_edits_and_deletes_a_station(self):
        self.client.force_login(self.owner.user)

        self.client.post(self.url, {'name': 'Tavolo 1', 'play_area': self.area.pk})
        station = PhysicalTable.objects.get(location=self.location)
        self.assertEqual((station.play_area, station.order), (self.area, 1))

        self.client.post(self._edit_url(station), {'name': 'Tavolo grande', 'play_area': self.area_b.pk})
        station.refresh_from_db()
        self.assertEqual((station.name, station.play_area), ('Tavolo grande', self.area_b))

        self.client.post(reverse('location-manage-station-delete',
                                 kwargs={'slug': self.location.slug, 'pk': station.pk}))
        self.assertFalse(PhysicalTable.objects.exists())

    def test_station_of_another_location_is_not_editable(self):
        foreign = PhysicalTable.objects.create(location=self.other_location, name='Tavolo 1')
        self.client.force_login(self.owner.user)

        self.assertEqual(self.client.get(self._edit_url(foreign)).status_code, 404)

    def test_form_rejects_duplicates_and_foreign_areas(self):
        PhysicalTable.objects.create(location=self.location, name='Tavolo 1')
        foreign_area = PlayArea.objects.create(location=self.other_location, name='Sala X')

        self.assertIn('name', PhysicalTableForm(data={'name': 'Tavolo 1'}, location=self.location).errors)
        form = PhysicalTableForm(data={'name': 'Tavolo 2', 'play_area': foreign_area.pk}, location=self.location)
        self.assertIn('play_area', form.errors)

    def test_moving_a_station_moves_its_tables_to_the_new_area(self):
        station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1', play_area=self.area)
        table = Table.objects.create(
            title='Serata', description='Una serata', date=datetime.date(2030, 1, 10), time=datetime.time(21, 0),
            author=self.owner, location=self.location, play_area=self.area, physical_table=station)
        self.client.force_login(self.owner.user)

        self.client.post(self._edit_url(station), {'name': 'Tavolo 1', 'play_area': self.area_b.pk})

        table.refresh_from_db()
        self.assertEqual((table.play_area, table.physical_table), (self.area_b, station))


class LocationTableStationTest(TestCase):
    def setUp(self):
        self.author = UserProfileFactory()
        self.location = LocationFactory(creator=self.author)
        self.area = PlayArea.objects.create(location=self.location, name='Sala A')
        self.other_area = PlayArea.objects.create(location=self.location, name='Sala B')
        self.station = PhysicalTable.objects.create(location=self.location, name='Tavolo 1', play_area=self.area)

    def _data(self, **extra):
        data = {
            'title': 'Serata', 'description': 'Una serata', 'date': '2030-01-10', 'time': '21:00',
            'min_players': 2, 'max_players': 4, 'location': self.location.pk,
            **LINKS_MANAGEMENT,
        }
        data.update(extra)
        return data

    def test_station_must_match_the_area(self):
        form = TableForm(data=self._data(play_area=self.other_area.pk, physical_table=self.station.pk),
                         location=self.location)

        self.assertIn('physical_table', form.errors)

    def test_station_of_another_location_is_rejected(self):
        foreign = PhysicalTable.objects.create(location=LocationFactory(name='Other', slug='other'), name='T')

        form = TableForm(data=self._data(physical_table=foreign.pk), location=self.location)

        self.assertIn('physical_table', form.errors)

    def test_create_table_with_station_and_show_it(self):
        self.client.force_login(self.author.user)

        self.client.post(
            reverse('location-table-create', kwargs={'location_slug': self.location.slug}),
            self._data(play_area=self.area.pk, physical_table=self.station.pk))

        table = Table.objects.get(location=self.location)
        self.assertEqual(table.physical_table, self.station)
        self.assertContains(self.client.get(reverse('table-detail', kwargs={'slug': table.slug})), 'Tavolo 1')
