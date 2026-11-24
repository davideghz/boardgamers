import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate, PlayArea, Table


class EventProgramAllDaysTest(TestCase):
    """"All days" (date=all) lists every day's agenda one after the other; it's the
    default before the event starts and never shows the grid."""

    def setUp(self):
        self.owner = UserProfileFactory()
        self.event = Event.objects.create(
            name="Con", slug="con", creator=self.owner, status=Event.PUBLISHED)
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

    def test_empty_today_points_to_first_day_with_tables(self):
        today, tomorrow = self.add_days(0, 1)
        self.table(tomorrow)
        response = self.client.get(self.url)
        self.assertEqual(response.context['selected_date'], today)
        self.assertEqual(response.context['first_table_date'], tomorrow)
        self.assertContains(response, 'In questo giorno non ci sono tavoli prenotabili.')

    def test_empty_day_points_to_first_day_with_tables(self):
        first, second, third = self.add_days(1, 2, 3)
        self.table(third)
        response = self.client.get(self.url, {'date': first.isoformat()})
        self.assertEqual(response.context['first_table_date'], third)
        self.assertContains(response, 'In questo giorno non ci sono tavoli prenotabili.')
        self.assertContains(response, 'Il primo giorno con tavoli prenotabili è')
        self.assertContains(response, f'date={third.isoformat()}')

    def test_empty_event_message(self):
        first, _ = self.add_days(1, 2)
        response = self.client.get(self.url, {'date': first.isoformat()})
        self.assertFalse(response.context['event_has_tables'])
        self.assertContains(response, 'Non ci sono ancora tavoli prenotabili per questo evento.')

    def test_filters_hiding_tables_offer_reset(self):
        first, _ = self.add_days(1, 2)
        self.table(first)
        area = PlayArea.objects.create(event=self.event, name="Sala")
        response = self.client.get(self.url, {'date': first.isoformat(), 'area': area.id})
        self.assertTrue(response.context['filters_hide_tables'])
        self.assertContains(response, 'Nessun tavolo corrisponde ai filtri selezionati.')
