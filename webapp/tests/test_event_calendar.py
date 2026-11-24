from datetime import date, time

from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import inlineformset_factory
from django.test import TestCase
from django.urls import reverse

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
