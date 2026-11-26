from django.test import TestCase
from django.urls import reverse

from webapp.models import Event, EventParticipant
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian

YOURE_IN = italian("You're in")
ATTENDING = italian("You're attending")
JOINED_DIALOG = 'id="joined-dialog"'


class ParticipationStatusTest(TestCase):
    """"You're in" / "You're attending" look and behave the same on every page (D4)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def login(self, persona):
        self.client.force_login(self.data.profile(persona).user)

    def test_joining_a_table_says_so_once(self):
        table = self.data.tables['upcoming']
        self.login('newcomer')

        response = self.client.post(reverse('join_table', args=[table.slug]), follow=True)
        self.assertContains(response, JOINED_DIALOG, count=1)
        self.assertContains(response, YOURE_IN)
        self.assertNotContains(response, 'Table joined!')

        self.assertNotContains(self.client.get(reverse('table-detail', args=[table.slug])), JOINED_DIALOG)

    def test_joining_an_event_table_says_so_too(self):
        event, table = self.data.event, self.data.tables['event']
        self.login('member')

        response = self.client.post(reverse('join_table', args=[table.slug]), follow=True)
        self.assertEqual(response.redirect_chain[-1][0], reverse('event_table_detail', args=[event.slug, table.slug]))
        self.assertContains(response, JOINED_DIALOG, count=1)

    def test_events_without_an_organizer_offer_leaving_after_a_confirmation(self):
        event = self.data.event
        Event.objects.filter(pk=event.pk).update(organizer_location=None)
        EventParticipant.objects.get_or_create(event=event, user_profile=self.data.player)
        self.login('player')

        response = self.client.get(reverse('event_detail', args=[event.slug]))
        self.assertContains(response, ATTENDING)
        self.assertContains(response, 'id="leave-event-dialog"', count=1)
        self.assertContains(response, "getElementById('leave-event-dialog').showModal()")

    def test_organized_events_show_the_status_and_confirm_leaving(self):
        self.login('member')
        response = self.client.get(reverse('event_detail', args=[self.data.night.slug]))
        self.assertContains(response, ATTENDING)
        self.assertContains(response, f'data-confirm="{italian("Leave the event?")}"')

    def test_my_activities_rows_carry_the_same_badges(self):
        self.login('member')
        upcoming = self.client.get(reverse('account-activities'))
        self.assertContains(upcoming, YOURE_IN)
        self.assertContains(upcoming, ATTENDING)

        past = self.client.get(reverse('account-activities'), {'tab': 'past'})
        self.assertNotContains(past, YOURE_IN)
        self.assertNotContains(past, ATTENDING)
