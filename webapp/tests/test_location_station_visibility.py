import datetime

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.forms import PhysicalTableForm, TableForm
from webapp.models import PhysicalTable, Table


class LocationStationVisibilityTest(TestCase):
    def setUp(self):
        self.owner = UserProfileFactory()
        self.player = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.station = PhysicalTable.objects.create(
            location=self.location, name='Private station', is_visible=False)
        self.table = Table.objects.create(
            title='Game', location=self.location, author=self.player, game=GameFactory(),
            physical_table=self.station, date=datetime.date.today(), time=datetime.time(20, 30))
        self.edit_url = reverse('location-manage-station-edit',
                                kwargs={'slug': self.location.slug, 'pk': self.station.pk})

    def test_existing_stations_are_public_by_default(self):
        station = PhysicalTable.objects.create(location=self.location, name='Public station')
        self.assertTrue(station.is_visible)
        self.assertTrue(station.is_visible_to(AnonymousUser()))

    def test_only_staff_can_see_a_hidden_station(self):
        self.assertFalse(self.station.is_visible_to(AnonymousUser()))
        self.assertFalse(self.station.is_visible_to(self.player.user))
        self.assertTrue(self.station.is_visible_to(self.owner.user))
        self.location.managers.add(self.player)
        self.assertTrue(self.station.is_visible_to(self.player.user))

    def test_manager_can_change_visibility_and_regular_user_cannot(self):
        self.client.force_login(self.player.user)
        self.assertEqual(self.client.post(self.edit_url, {
            'name': self.station.name, 'is_visible': 'on'}).status_code, 403)
        self.station.refresh_from_db()
        self.assertFalse(self.station.is_visible)
        self.client.force_login(self.owner.user)
        response = self.client.post(self.edit_url, {
            'name': self.station.name, 'is_visible': 'on'})
        self.assertEqual(response.status_code, 302)
        self.station.refresh_from_db()
        self.assertTrue(self.station.is_visible)
        self.client.post(self.edit_url, {'name': self.station.name})
        self.station.refresh_from_db()
        self.assertFalse(self.station.is_visible)

    def test_hidden_station_is_not_a_valid_public_choice(self):
        form = TableForm(location=self.location, user=self.player.user)
        self.assertNotIn(self.station, form.fields['physical_table'].queryset)
        with self.assertRaises(ValidationError):
            form.fields['physical_table'].clean(self.station.pk)
        form = TableForm(location=self.location, user=self.owner.user)
        self.assertIn(self.station, form.fields['physical_table'].queryset)

    def test_author_edit_preserves_the_hidden_assignment(self):
        form = TableForm(instance=self.table, location=self.location, user=self.player.user)
        self.assertNotIn('physical_table', form.fields)
        self.assertNotIn('play_area', form.fields)
        data = {'title': 'Updated', 'location': self.location.pk, 'game': self.table.game_id,
                'date': self.table.date.isoformat(), 'time': '20:30', 'duration': 60,
                'min_players': 1, 'max_players': 4, 'description': 'Description',
                'physical_table': ''}
        form = TableForm(data, instance=self.table, location=self.location, user=self.player.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.table.refresh_from_db()
        self.assertEqual(self.table.physical_table_id, self.station.pk)

    def test_card_and_detail_hide_station_from_visitors(self):
        card = Template('{% load custom_tags %}{% table_card table %}')
        for user in (AnonymousUser(), self.player.user):
            self.assertNotIn(self.station.name, card.render(Context({'table': self.table, 'user': user})))
        self.assertIn(self.station.name, card.render(Context({'table': self.table, 'user': self.owner.user})))
        self.client.logout()
        url = reverse('table-detail', kwargs={'slug': self.table.slug})
        self.assertNotContains(self.client.get(url), self.station.name)
        self.client.force_login(self.owner.user)
        self.assertContains(self.client.get(url), self.station.name)

    def test_new_station_is_public_unless_unchecked(self):
        self.client.force_login(self.owner.user)
        url = reverse('location-manage-stations', kwargs={'slug': self.location.slug})
        page = self.client.get(url).content.decode()
        self.assertEqual(page.count('name="is_visible"'), 1)
        self.client.post(url, {'name': 'Public station', 'is_visible': 'on'})
        self.client.post(url, {'name': 'Staff station'})
        self.assertTrue(PhysicalTable.objects.get(name='Public station').is_visible)
        self.assertFalse(PhysicalTable.objects.get(name='Staff station').is_visible)

    def test_author_sees_a_read_only_note_for_a_hidden_station(self):
        url = reverse('location-table-update',
                      kwargs={'location_slug': self.location.slug, 'table_slug': self.table.slug})
        self.client.force_login(self.player.user)
        response = self.client.get(url)
        self.assertContains(response, _('Station assigned by the staff'))
        self.assertNotContains(response, self.station.name)
        self.client.force_login(self.owner.user)
        self.assertNotContains(self.client.get(url), _('Station assigned by the staff'))
