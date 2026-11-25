from datetime import date, time

from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, MasterEvent, MasterEventDate
from webapp.services.profile_merge import merge_accounts


class MasterEventTest(TestCase):
    def test_venue_picker_switches_modes_and_restores_manual_errors(self):
        manager = UserProfileFactory()
        venue = LocationFactory()
        self.client.force_login(manager.user)
        create = reverse('master-event-create')
        response = self.client.get(create)
        self.assertContains(response, 'data-venue-fields="manual" hidden disabled')
        self.assertNotContains(response, '<select name="venue_location"')

        data = {'name': 'Fiera', 'description': 'Weekend', 'venue_mode': 'manual',
                'venue_location': venue.pk, 'venue_name': 'Sala Civica', 'address': 'Via Roma 1'}
        response = self.client.post(create, {**data, 'latitude': 'invalid'})
        self.assertIn('latitude', response.context['form'].errors)
        self.assertContains(response, 'data-venue-fields="registered" hidden disabled')
        self.assertContains(response, 'value="Sala Civica"')
        self.assertFalse(MasterEvent.objects.exists())

        self.client.post(create, {**data, 'latitude': '45.54', 'longitude': '11.52'})
        master = MasterEvent.objects.get()
        self.assertIsNone(master.venue_location)
        self.assertEqual(master.venue_name, 'Sala Civica')

        edit = reverse('master-event-manage', args=[master.slug])
        self.client.post(edit, {**data, 'venue_mode': 'registered', 'latitude': 'invalid'})
        master.refresh_from_db()
        self.assertEqual(master.venue_location, venue)
        self.assertEqual(master.venue_name, '')
        self.assertIsNone(master.latitude)
        self.assertContains(self.client.get(edit), 'data-venue-fields="manual" hidden disabled')

    def test_draft_calendar_and_admin_approval_before_any_program(self):
        manager, stranger, admin = [UserProfileFactory() for _ in range(3)]
        admin.user.is_staff = admin.user.is_superuser = True
        admin.user.save()
        venue = LocationFactory()
        self.client.force_login(manager.user)
        self.client.post(reverse('master-event-create'), {'name': 'Fiera', 'description': 'Weekend',
                                                         'venue_location': venue.pk, 'status': 'published'})
        master = MasterEvent.objects.get()
        self.assertFalse(master.is_published)
        self.assertTrue(master.can_manage(manager.user))
        manage = reverse('master-event-manage', args=[master.slug])
        approve = reverse('master-event-approve', args=[master.slug])
        calendar = reverse('master-event-calendar', args=[master.slug])
        self.assertContains(self.client.get(manage), 'Weekend')
        self.assertEqual(self.client.post(approve).status_code, 403)
        self.client.force_login(stranger.user)
        self.assertNotContains(self.client.get(reverse('master-event-list')), master.name)
        self.assertEqual(self.client.get(master.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(calendar, {'date': date(2030, 5, 3)}).status_code, 403)
        self.client.force_login(admin.user)
        self.assertContains(self.client.get(reverse('master-event-list')), master.name)
        self.assertContains(self.client.get(master.get_absolute_url()), approve)
        self.client.post(approve)
        master.refresh_from_db()
        self.assertFalse(master.is_published)
        self.client.force_login(manager.user)
        self.client.post(calendar, {'date': date(2030, 5, 3)})
        self.client.force_login(admin.user)
        self.client.post(approve)
        master.refresh_from_db()
        self.assertTrue(master.is_published)
        self.assertEqual(master.approved_by, admin.user)
        self.client.logout()
        self.assertContains(self.client.get(master.get_absolute_url()), 'Fiera')
        self.assertContains(self.client.get(reverse('master-event-list')), 'Fiera')

    def test_staff_permission_controls_draft_review_and_approval(self):
        master = MasterEvent.objects.create(
            name='Festival da approvare', description='Due giornate', venue_location=LocationFactory(),
        )
        MasterEventDate.objects.create(master_event=master, date=date(2030, 5, 3))
        reviewer = UserProfileFactory(user__is_staff=True).user
        self.client.force_login(reviewer)
        index = reverse('master-event-list')
        approve = reverse('master-event-approve', args=[master.slug])
        self.assertNotContains(self.client.get(index), master.name)
        self.assertEqual(self.client.get(master.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(approve).status_code, 403)

        reviewer.user_permissions.add(Permission.objects.get(
            content_type__app_label='webapp', codename='change_masterevent',
        ))
        self.assertContains(self.client.get(index), master.name)
        self.assertContains(self.client.get(master.get_absolute_url()), approve)
        self.assertEqual(self.client.get(reverse('master-event-manage', args=[master.slug])).status_code, 403)
        self.assertEqual(self.client.post(approve).status_code, 302)
        master.refresh_from_db()
        self.assertEqual(master.approved_by, reviewer)

    def test_admin_action_requires_a_complete_venue_and_records_approval(self):
        admin = UserProfileFactory(user__is_staff=True, user__is_superuser=True).user
        master = MasterEvent.objects.create(name='Festa', description='Giochi', venue_name='Sala civica')
        MasterEventDate.objects.create(master_event=master, date=date(2030, 5, 3))
        self.client.force_login(admin)
        action = {'action': 'approve_publication', '_selected_action': [master.pk]}
        index = reverse('admin:webapp_masterevent_changelist')
        self.assertEqual(self.client.post(index, action).status_code, 302)
        master.refresh_from_db()
        self.assertFalse(master.is_published)
        master.address = 'Via Roma'
        master.latitude, master.longitude = 45, 11
        master.save()
        self.assertEqual(self.client.post(index, action).status_code, 302)
        master.refresh_from_db()
        self.assertTrue(master.is_published)
        self.assertEqual(master.approved_by, admin)
        self.assertIsNotNone(master.approved_at)

    def test_admin_can_hide_a_published_manifestation_until_a_new_approval(self):
        admin = UserProfileFactory(user__is_staff=True, user__is_superuser=True).user
        master = MasterEvent.objects.create(name='Festa', description='Giochi', venue_location=LocationFactory())
        MasterEventDate.objects.create(master_event=master, date=date(2030, 5, 3))
        index = reverse('admin:webapp_masterevent_changelist')

        def run(action):
            self.client.force_login(admin)
            self.client.post(index, {'action': action, '_selected_action': [master.pk]})
            self.client.logout()
            master.refresh_from_db()

        for action, status in (('back_to_draft', Event.DRAFT), ('block', Event.BLOCKED)):
            with self.subTest(action=action):
                run('approve_publication')
                self.assertTrue(master.is_published)
                self.assertContains(self.client.get(master.get_absolute_url()), 'Festa')
                run(action)
                self.assertEqual(master.status, status)
                self.assertIsNone(master.approved_by)
                self.assertIsNone(master.approved_at)
                self.assertEqual(self.client.get(master.get_absolute_url()).status_code, 404)
                self.assertNotContains(self.client.get(reverse('master-event-list')), 'Festa')
        run('approve_publication')
        self.assertEqual(master.status, Event.BLOCKED)
        run('back_to_draft')
        run('approve_publication')
        self.assertTrue(master.is_published)

        reviewer = UserProfileFactory(user__is_staff=True).user
        with self.assertRaises(PermissionDenied):
            master.withdraw(reviewer, Event.BLOCKED)

    def test_edit_hours_and_guard_the_last_public_day(self):
        manager = UserProfileFactory()
        admin = UserProfileFactory(user__is_staff=True, user__is_superuser=True).user
        master = MasterEvent.objects.create(name='Festa', description='Giochi', venue_location=LocationFactory())
        master.managers.add(manager)
        day = MasterEventDate.objects.create(master_event=master, date=date(2030, 5, 3), opening_time=time(9))
        master.approve(admin)
        self.client.force_login(manager.user)
        edit = reverse('master-event-manage', args=[master.slug])
        calendar = reverse('master-event-calendar', args=[master.slug])
        response = self.client.get(edit, {'day': day.date.isoformat()})
        self.assertEqual(response.context['date_form'].initial['opening_time'], time(9))
        self.client.post(calendar, {'date': day.date, 'opening_time': '10:30', 'closing_time': '17:00'})
        day.refresh_from_db()
        self.assertEqual((day.opening_time, day.closing_time), (time(10, 30), time(17)))
        self.assertEqual(master.dates.count(), 1)
        self.client.post(calendar, {'remove': day.pk})
        self.assertTrue(master.dates.filter(pk=day.pk).exists())
        with self.assertRaises(ValidationError), transaction.atomic():
            master.dates.all().delete()

    def test_profile_merge_transfers_manifestation_management(self):
        keeper, duplicate = UserProfileFactory(), UserProfileFactory()
        keeper.user.set_password('local-merge-password')
        keeper.user.save(update_fields=['password'])
        master = MasterEvent.objects.create(name='Festa')
        master.managers.add(duplicate)
        merge_accounts(keeper.pk, duplicate.pk)
        self.assertEqual(list(master.managers.all()), [keeper])
