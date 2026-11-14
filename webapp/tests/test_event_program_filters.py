import datetime

from django.test import TestCase
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate, EventTableCategory, PlayArea


class EventProgramFiltersTest(TestCase):
    """Below lg the program filters live in a bottom panel; the active ones are
    shown as chips whose X drops just that filter."""

    def setUp(self):
        self.event = Event.objects.create(
            name="Con", slug="con", creator=UserProfileFactory(), status=Event.APPROVED)
        EventDate.objects.create(event=self.event, date=datetime.date(2030, 9, 13))
        self.area = PlayArea.objects.create(event=self.event, name="Cortile")
        self.category = EventTableCategory.objects.create(event=self.event, name="Wargames")
        self.url = reverse('event-program', kwargs={'slug': self.event.slug})

    def test_no_active_filters(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['active_filter_count'], 0)
        self.assertContains(response, 'id="program-filters"')

    def test_active_filters_become_removable_chips(self):
        response = self.client.get(self.url, {'area': self.area.id, 'category': self.category.id})
        self.assertEqual(response.context['active_filter_count'], 2)
        self.assertContains(response, f'href="?category={self.category.id}"')
        self.assertContains(response, f'href="?area={self.area.id}"')
        self.assertContains(response, 'href="?"')  # clear all
