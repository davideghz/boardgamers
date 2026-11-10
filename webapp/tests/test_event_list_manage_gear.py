import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate


class EventListManageGearTest(TestCase):
    """On the events page, cards of events the user created or manages carry a
    gear linking to the management page; their pending events are listed among
    the upcoming ones, for them only."""

    def setUp(self):
        self.user_profile = UserProfileFactory()
        self.other = UserProfileFactory()
        future = timezone.localdate() + datetime.timedelta(days=3)
        self.owned = Event.objects.create(
            name="Owned con", slug="owned-con", creator=self.user_profile, status=Event.APPROVED)
        self.managed = Event.objects.create(
            name="Managed con", slug="managed-con", creator=self.other, status=Event.APPROVED)
        self.managed.managers.add(self.user_profile)
        self.foreign = Event.objects.create(
            name="Foreign con", slug="foreign-con", creator=self.other, status=Event.APPROVED)
        self.pending = Event.objects.create(name="Pending con", slug="pending-con", creator=self.user_profile)
        for event in (self.owned, self.managed, self.foreign, self.pending):
            EventDate.objects.create(event=event, date=future)

    def _manage_url(self, event):
        return reverse('event-manage', kwargs={'slug': event.slug})

    def test_gear_only_on_managed_events(self):
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertContains(response, self._manage_url(self.owned))
        self.assertContains(response, self._manage_url(self.managed))
        self.assertNotContains(response, self._manage_url(self.foreign))

    def test_managed_pending_events_are_listed_with_their_status(self):
        undated = Event.objects.create(name="Undated con", slug="undated-con", creator=self.user_profile)
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        upcoming = list(response.context['upcoming_events'])
        self.assertIn(self.pending, upcoming)
        self.assertEqual(upcoming[-1], undated)
        self.assertContains(response, self._manage_url(self.pending))
        self.assertContains(response, "In attesa")

    def test_pending_events_stay_hidden_from_others(self):
        foreign_pending = Event.objects.create(name="Foreign pending", slug="foreign-pending", creator=self.other)
        EventDate.objects.create(event=foreign_pending, date=timezone.localdate())
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Foreign pending")
        self.client.logout()
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Pending con")

    def test_rejected_events_are_not_listed(self):
        self.pending.status = Event.REJECTED
        self.pending.save()
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Pending con")

    def test_no_gear_for_anonymous(self):
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, self._manage_url(self.owned))


class AccountEventsFirstDateTest(TestCase):
    def test_first_date_is_shown_next_to_the_city(self):
        user_profile = UserProfileFactory()
        event = Event.objects.create(name="Con", slug="con", city="Vailate", creator=user_profile)
        EventDate.objects.create(event=event, date=datetime.date(2030, 9, 14))
        EventDate.objects.create(event=event, date=datetime.date(2030, 9, 13))
        self.client.force_login(user_profile.user)
        response = self.client.get(reverse('account-events'))
        self.assertContains(response, "Vailate · 13 ")
