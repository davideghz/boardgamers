from datetime import date, time, timedelta

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate, MasterEvent, MasterEventDate, Table
from webapp.services.master_events import set_master


class MasterProgramTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager, cls.organizer = [UserProfileFactory() for _ in range(2)]
        cls.club = LocationFactory(creator=cls.organizer)
        cls.master = MasterEvent.objects.create(name='Spring Festival', status=Event.PUBLISHED)
        cls.master.managers.add(cls.manager)
        cls.day = date(2030, 5, 3)
        cls.second_day = cls.day + timedelta(days=2)
        cls.first = MasterEventDate.objects.create(master_event=cls.master, date=cls.day)
        cls.second = MasterEventDate.objects.create(master_event=cls.master, date=cls.second_day)
        cls.event = Event.objects.create(name='Tournament', organizer_location=cls.club, status=Event.PUBLISHED)
        EventDate.objects.create(event=cls.event, date=cls.day)
        cls.link = reverse('master-event-link', args=[cls.master.slug])
        cls.manage = reverse('master-event-manage', args=[cls.master.slug])

    def test_link_and_unlink_are_controlled_by_the_manifestation_manager(self):
        self.client.force_login(self.organizer.user)
        self.assertEqual(self.client.post(self.link, {'event': self.event.pk}).status_code, 403)
        self.client.force_login(self.manager.user)
        self.assertEqual(self.client.get(self.link).status_code, 405)
        self.assertEqual(self.client.post(self.link, {'event': 'invalid'}).status_code, 404)
        self.assertRedirects(
            self.client.post(self.link, {'event': self.event.pk}), self.manage + '#master-event-events',
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.master_event_id, self.master.pk)
        self.assertEqual(self.client.get(reverse('event-manage-data', args=[self.event.slug])).status_code, 403)

        other = MasterEvent.objects.create(name='Another festival', status=Event.PUBLISHED)
        other.managers.add(self.manager)
        other_link = reverse('master-event-link', args=[other.slug])
        self.assertEqual(self.client.post(other_link, {'event': self.event.pk}).status_code, 404)
        self.assertEqual(self.client.post(other_link, {'remove': self.event.pk}).status_code, 404)
        self.client.post(self.link, {'remove': self.event.pk})
        self.event.refresh_from_db()
        self.assertIsNone(self.event.master_event_id)
        self.assertEqual(self.event.organizer_location, self.club)
        self.assertEqual(self.event.dates.get().date, self.day)

    def test_only_eligible_events_can_be_selected_or_linked(self):
        other_draft = Event.objects.create(name='Private draft', organizer_location=self.club)
        own_draft = Event.objects.create(name='My draft', organizer_location=LocationFactory(creator=self.manager))
        blocked = Event.objects.create(name='Blocked event', organizer_location=self.club, status=Event.BLOCKED)
        legacy = Event.objects.create(name='Legacy event', status=Event.PUBLISHED)

        self.client.force_login(self.manager.user)
        response = self.client.get(self.manage)
        self.assertContains(response, own_draft.name)
        for unavailable in (other_draft, blocked, legacy):
            self.assertNotContains(response, unavailable.name)
            self.assertEqual(self.client.post(self.link, {'event': unavailable.pk}).status_code, 404)
        self.client.post(self.link, {'event': own_draft.pk})
        self.assertTrue(self.master.events.filter(pk=own_draft.pk).exists())
        self.assertNotContains(self.client.get(self.master.get_absolute_url()), own_draft.name)

    def test_unapproved_manifestations_only_link_the_events_of_their_managers(self):
        MasterEvent.objects.filter(pk=self.master.pk).update(status=Event.DRAFT)
        own = Event.objects.create(name='Own event', organizer_location=LocationFactory(creator=self.manager),
                                   status=Event.PUBLISHED)
        self.client.force_login(self.manager.user)
        response = self.client.get(self.manage)
        self.assertContains(response, own.name)
        self.assertNotContains(response, self.event.name)
        self.assertEqual(self.client.post(self.link, {'event': self.event.pk}).status_code, 404)
        with self.assertRaises(ValidationError):
            set_master(self.event, self.master, self.manager.user)
        self.client.post(self.link, {'event': own.pk})
        self.assertEqual(list(self.master.events.all()), [own])

    def test_organizer_sees_the_manifestation_and_can_leave_it(self):
        set_master(self.event, self.master, self.manager.user)
        MasterEvent.objects.filter(pk=self.master.pk).update(status=Event.BLOCKED)
        unlink = reverse('event-master-unlink', args=[self.event.slug])
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.post(unlink, {'master': self.master.pk}).status_code, 403)
        self.client.force_login(self.organizer.user)
        manage = reverse('event-manage', args=[self.event.slug])
        self.assertContains(self.client.get(manage), self.master.name)
        self.assertContains(self.client.get(manage), unlink)

        other = MasterEvent.objects.create(name='Another festival')
        self.client.post(unlink, {'master': other.pk})
        self.assertTrue(self.master.events.exists())
        self.assertRedirects(self.client.post(unlink, {'master': self.master.pk}), manage)
        self.assertFalse(self.master.events.exists())
        self.assertNotContains(self.client.get(manage), unlink)
        outside = self.day + timedelta(days=1)
        EventDate.objects.create(event=self.event, date=outside)
        self.assertEqual(self.client.post(unlink, {'master': self.master.pk}).status_code, 302)

    def test_all_event_dates_must_fit_before_linking(self):
        outside = EventDate.objects.create(event=self.event, date=self.day + timedelta(days=1))
        self.client.force_login(self.manager.user)
        with self.settings(LANGUAGE_CODE='en'):
            self.client.cookies['django_language'] = 'en'
            response = self.client.post(self.link, {'event': self.event.pk}, follow=True)
            self.assertContains(response, 'Add these dates to the festival calendar before linking the event')
        self.assertFalse(self.master.events.exists())
        MasterEventDate.objects.create(master_event=self.master, date=outside.date)
        self.client.post(self.link, {'event': self.event.pk})
        self.assertTrue(self.master.events.filter(pk=self.event.pk).exists())

    def test_linked_event_dates_stay_in_the_manifestation_calendar(self):
        set_master(self.event, self.master, self.manager.user)
        outside = self.day + timedelta(days=1)
        self.client.force_login(self.organizer.user)
        url = reverse('event-manage-dates', args=[self.event.slug])
        response = self.client.post(url, {'date': outside, 'opening_time': '10:00', 'closing_time': '19:00'})
        self.assertTrue(response.context['form']['date'].errors)
        self.assertFalse(self.event.dates.filter(date=outside).exists())
        with self.assertRaises(ValidationError):
            EventDate.objects.create(event=self.event, date=outside)
        self.assertEqual(self.client.post(url, {
            'date': self.second_day, 'opening_time': '10:00', 'closing_time': '19:00',
        }).status_code, 302)
        self.assertTrue(self.event.dates.filter(date=self.second_day).exists())

    def test_used_manifestation_dates_cannot_be_removed_or_moved(self):
        set_master(self.event, self.master, self.manager.user)
        self.client.force_login(self.manager.user)
        calendar = reverse('master-event-calendar', args=[self.master.slug])
        self.client.post(calendar, {'remove': self.first.pk})
        self.assertTrue(self.master.dates.filter(pk=self.first.pk).exists())
        with self.assertRaises(ValidationError), transaction.atomic():
            self.master.dates.filter(pk__in=[self.first.pk, self.second.pk]).delete()
        self.first.date += timedelta(days=1)
        with self.assertRaises(ValidationError):
            self.first.save()
        self.client.post(calendar, {'remove': self.second.pk})
        self.assertFalse(self.master.dates.filter(pk=self.second.pk).exists())

    def test_public_program_uses_public_event_and_table_visibility(self):
        set_master(self.event, self.master, self.manager.user)
        table = Table.objects.create(event=self.event, date=self.day, time=time(10), title='Final round')
        Table.objects.create(event=self.event, date=self.day, time=time(9), title='Opening round')
        Table.objects.create(date=self.day, location=self.club, title='Standalone session')
        page = self.master.get_absolute_url()
        response = self.client.get(page)
        self.assertContains(response, self.event.name)
        self.assertContains(response, self.club.name)
        self.assertContains(response, table.get_absolute_url())
        self.assertLess(response.content.index(b'Opening round'), response.content.index(b'Final round'))
        self.assertNotContains(response, 'Standalone session')
        self.assertContains(self.client.get(self.event.get_absolute_url()), page)

        self.event.table_booking_enabled = False
        self.event.save(update_fields=['table_booking_enabled'])
        self.assertContains(self.client.get(page), self.event.name)
        self.assertNotContains(self.client.get(page), table.title)
        self.event.status = Event.DRAFT
        self.event.save(update_fields=['status'])
        self.assertNotContains(self.client.get(page), self.event.name)

    def test_public_event_does_not_disclose_unpublished_manifestation(self):
        set_master(self.event, self.master, self.manager.user)
        self.master.status = Event.DRAFT
        self.master.save(update_fields=['status'])
        self.assertNotContains(self.client.get(self.event.get_absolute_url()), self.master.name)
        self.assertEqual(self.client.get(self.master.get_absolute_url()).status_code, 404)

    def test_event_admin_save_preserves_a_link_made_after_loading_the_event(self):
        admin_event = Event.objects.get(pk=self.event.pk)
        set_master(self.event, self.master, self.manager.user)
        admin_event.description = 'Updated by an administrator'
        admin.site.get_model_admin(Event).save_model(None, admin_event, None, change=True)
        admin_event.refresh_from_db()
        self.assertEqual(admin_event.master_event_id, self.master.pk)
        self.assertEqual(admin_event.description, 'Updated by an administrator')
