import datetime
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import UserProfileFactory
from webapp.models import Event, EventDate


class EventListManageGearTest(TestCase):
    """On the events page (the search preset), the drafts of the events the user
    created or manages are listed apart from the results, for them only."""

    def setUp(self):
        self.user_profile = UserProfileFactory()
        self.other = UserProfileFactory()
        future = timezone.localdate() + datetime.timedelta(days=3)
        self.owned = Event.objects.create(
            name="Owned con", slug="owned-con", creator=self.user_profile, status=Event.PUBLISHED)
        self.managed = Event.objects.create(
            name="Managed con", slug="managed-con", creator=self.other, status=Event.PUBLISHED)
        self.managed.managers.add(self.user_profile)
        self.foreign = Event.objects.create(
            name="Foreign con", slug="foreign-con", creator=self.other, status=Event.PUBLISHED)
        self.pending = Event.objects.create(name="Pending con", slug="pending-con", creator=self.user_profile)
        for event in (self.owned, self.managed, self.foreign, self.pending):
            EventDate.objects.create(event=event, date=future)

    def test_managed_drafts_are_listed_with_their_status(self):
        undated = Event.objects.create(name="Undated con", slug="undated-con", creator=self.user_profile)
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertEqual({item for _, item in response.context['drafts']}, {self.pending, undated})
        self.assertNotIn(('event', self.pending), response.context['items'])
        self.assertContains(response, self.pending.get_absolute_url())
        self.assertContains(response, "Bozza")

    def test_drafts_stay_hidden_from_others(self):
        foreign_pending = Event.objects.create(name="Foreign pending", slug="foreign-pending", creator=self.other)
        EventDate.objects.create(event=foreign_pending, date=timezone.localdate())
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Foreign pending")
        self.client.logout()
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Pending con")

    def test_blocked_events_are_not_listed(self):
        self.pending.status = Event.BLOCKED
        self.pending.save()
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('event-index'))
        self.assertNotContains(response, "Pending con")


class AccountEventsFirstDateTest(TestCase):
    def test_first_date_is_shown_next_to_the_city(self):
        user_profile = UserProfileFactory()
        event = Event.objects.create(name="Con", slug="con", city="Vailate", creator=user_profile)
        EventDate.objects.create(event=event, date=datetime.date(2030, 9, 14))
        EventDate.objects.create(event=event, date=datetime.date(2030, 9, 13))
        self.client.force_login(user_profile.user)
        response = self.client.get(reverse('account-events'))
        self.assertContains(response, "Vailate · 13 ")


class EventCardEndedBadgeTest(TestCase):
    def test_multiday_event_card_is_not_ended_on_the_last_day(self):
        last_day = datetime.date(2026, 11, 22)
        event = Event.objects.create(name="Multiday con", slug="multiday-con", status=Event.PUBLISHED)
        EventDate.objects.create(event=event, date=last_day - datetime.timedelta(days=1))
        EventDate.objects.create(event=event, date=last_day)

        with patch.object(timezone, 'localdate', return_value=last_day):
            response = self.client.get(reverse('event-index'))

        self.assertContains(response, event.name)
        self.assertNotContains(response, "Concluso")

    def test_past_events_are_marked(self):
        event = Event.objects.create(name="Old con", slug="old-con", status=Event.PUBLISHED)
        EventDate.objects.create(event=event, date=timezone.localdate() - datetime.timedelta(days=3))
        self.assertNotContains(self.client.get(reverse('event-index')), event.name)
        response = self.client.get(reverse('event-index'), {'past': '1'})  # the old parameter still works
        self.assertContains(response, event.name)
        self.assertContains(response, "Passato")
