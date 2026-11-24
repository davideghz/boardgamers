from datetime import date, time, timedelta
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from django.forms import inlineformset_factory
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.admin import EventDateInlineFormSet
from webapp.factories import LocationFactory, UserProfileFactory
from webapp.forms import EventTableForm
from webapp.models import Event, EventDate, Table


class EventCalendarTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.location = LocationFactory(creator=UserProfileFactory())
        cls.event = Event.objects.create(name='Weekend', organizer_location=cls.location)
        cls.friday = EventDate.objects.create(event=cls.event, date=date(2030, 5, 3))
        cls.sunday = EventDate.objects.create(event=cls.event, date=date(2030, 5, 5))

    def test_gap_cannot_be_booked_even_by_forging_the_form(self):
        saturday = date(2030, 5, 4)
        with self.assertRaises(ValidationError):
            Table.objects.create(event=self.event, author=self.location.creator, date=saturday)
        other = Event.objects.create(name='Other')
        form = EventTableForm({'date': saturday.isoformat(), 'event': other.pk}, event=self.event)
        self.assertIn('date', form.errors)
        self.assertIn('event', form.errors)
        Table.objects.create(location=self.location, author=self.location.creator, date=saturday)

    def test_scheduled_day_can_change_hours_but_cannot_move_or_disappear(self):
        Table.objects.create(event=self.event, author=self.location.creator, date=self.friday.date)
        self.friday.opening_time = time(17)
        self.friday.save()
        self.friday.date = date(2030, 5, 6)
        with self.assertRaises(ValidationError):
            self.friday.save()
        self.client.force_login(self.location.creator.user)
        self.client.post(reverse('event-manage-date-delete', args=[self.event.slug, self.friday.pk]))
        self.assertTrue(self.event.dates.filter(pk=self.friday.pk, date=date(2030, 5, 3)).exists())
        self.event.delete()

    def test_tables_already_outside_the_calendar_can_still_be_saved(self):
        author = self.location.creator
        author.is_email_verified = True
        author.save(update_fields=['is_email_verified'])
        yesterday = timezone.localdate() - timedelta(days=1)
        event = Event.objects.create(name='Storico', creator=author, status=Event.PUBLISHED)
        EventDate.objects.create(event=event, date=yesterday - timedelta(days=1))
        off_calendar = Table.objects.create(event=event, author=author, date=yesterday, time=time(10), external_players=1)
        regular = Table.objects.create(location=self.location, author=author, date=yesterday, time=time(10))
        Table.objects.filter(pk__in=[off_calendar.pk, regular.pk]).update(status=Table.OPEN)
        event.organizer_location = self.location
        event.save()

        call_command('update_table_status', stdout=StringIO())
        for table in (off_calendar, regular):
            table.refresh_from_db()
            self.assertNotEqual(table.status, Table.OPEN)
        off_calendar.full_clean(exclude=['slug', 'title', 'description'])
        self.client.force_login(author.user)
        response = self.client.post(reverse('clear_external_players', args=[off_calendar.slug]))
        self.assertEqual(response.status_code, 302)
        off_calendar.refresh_from_db()
        self.assertEqual(off_calendar.external_players, 0)

        off_calendar.date = yesterday - timedelta(days=5)
        with self.assertRaises(ValidationError):
            off_calendar.save()
        off_calendar.date = yesterday - timedelta(days=1)
        off_calendar.save()

    def test_moving_a_table_to_another_event_checks_its_calendar(self):
        other = Event.objects.create(name='Altro', organizer_location=self.location)
        EventDate.objects.create(event=other, date=self.sunday.date)
        table = Table.objects.create(event=self.event, author=self.location.creator, date=self.friday.date)
        table.event = other
        with self.assertRaises(ValidationError):
            table.save()

    def test_bulk_removal_cannot_leave_a_published_event_undated(self):
        self.event.status = Event.PUBLISHED
        self.event.save(update_fields=['status'])
        with self.assertRaises(ValidationError), transaction.atomic():
            self.event.dates.all().delete()
        self.assertEqual(self.event.dates.count(), 2)

    def test_admin_can_replace_the_only_day_in_one_save(self):
        self.sunday.delete()
        self.event.status = Event.PUBLISHED
        self.event.save(update_fields=['status'])
        replacement = date(2030, 5, 6)
        formset_class = inlineformset_factory(
            Event, EventDate, formset=EventDateInlineFormSet, fields=['date'], extra=1,
        )
        formset = formset_class({
            'dates-TOTAL_FORMS': '2',
            'dates-INITIAL_FORMS': '1',
            'dates-0-id': self.friday.pk,
            'dates-0-date': self.friday.date.isoformat(),
            'dates-0-DELETE': 'on',
            'dates-1-date': replacement.isoformat(),
        }, instance=self.event)
        self.assertTrue(formset.is_valid(), formset.non_form_errors())
        formset.save()
        self.assertEqual(list(self.event.dates.values_list('date', flat=True)), [replacement])
