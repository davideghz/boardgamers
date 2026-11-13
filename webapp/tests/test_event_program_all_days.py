import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate, Table


class EventProgramAllDaysTest(TestCase):
    """"All days" (date=all) lists every day's agenda one after the other; it's the
    default before the event starts and never shows the grid."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.event = Event.objects.create(
            name="Con", slug="con", creator=self.owner, status=Event.APPROVED)
        self.today = timezone.localdate()
        self.url = reverse('event-program', kwargs={'slug': self.event.slug})

    def add_days(self, *offsets):
        days = [self.today + datetime.timedelta(days=o) for o in offsets]
        for day in days:
            EventDate.objects.create(event=self.event, date=day)
        return days

    def table(self, date, hour=20):
        return Table.objects.create(
            title="T", event=self.event, author=self.owner, date=date, time=datetime.time(hour, 0))

    def test_default_before_the_event_starts(self):
        first, second = self.add_days(1, 2)
        self.table(second, 18)
        self.table(first, 21)
        response = self.client.get(self.url)
        self.assertTrue(response.context['all_days'])
        self.assertIsNone(response.context['selected_date'])
        self.assertEqual([d['date'] for d in response.context['agenda_days']], [first, second])

    def test_default_is_today_once_started(self):
        _, today = self.add_days(-1, 0)
        response = self.client.get(self.url)
        self.assertFalse(response.context['all_days'])
        self.assertEqual(response.context['selected_date'], today)

    def test_single_day_event_has_no_all_days(self):
        day, = self.add_days(3)
        response = self.client.get(self.url, {'date': 'all'})
        self.assertFalse(response.context['all_days'])
        self.assertEqual(response.context['selected_date'], day)
        self.assertFalse(response.context['has_many_dates'])  # no "All days" pill

    def test_all_days_forces_the_agenda(self):
        first, _ = self.add_days(1, 2)
        self.table(first)
        response = self.client.get(self.url, {'date': 'all', 'view': 'grid'})
        self.assertEqual(response.context['view_mode'], 'list')
        self.assertIsNone(response.context['grid'])

    def test_all_days_hides_past_days_unless_asked(self):
        past, future = self.add_days(-1, 1)
        self.table(past)
        self.table(future)
        response = self.client.get(self.url, {'date': 'all'})
        self.assertEqual([d['date'] for d in response.context['agenda_days']], [future])
        response = self.client.get(self.url, {'date': 'all', 'show_past': '1'})
        self.assertEqual([d['date'] for d in response.context['agenda_days']], [past, future])

    def test_empty_day_message(self):
        first, _ = self.add_days(1, 2)
        response = self.client.get(self.url, {'date': first.isoformat()})
        self.assertContains(
            response, 'Nel giorno selezionato non ci sono tavoli prenotabili per i filtri selezionati.')
