from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import override, pgettext

from webapp.models import Event
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian


class OwnActivitiesTest(TestCase):
    """What each persona finds of their own: the festival they run or attend, the event a member
    proposed, and no membership request on the locations one manages."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def login(self, persona):
        self.client.force_login(self.data.profile(persona).user)

    def items(self, **params):
        return self.client.get(reverse('account-activities'), params).context['items']

    def test_the_organizer_finds_their_festival(self):
        festival = self.data.manifestation
        self.login('organizer')
        home = self.client.get(reverse('home')).context
        self.assertEqual(home['next_activities'], [('manifestation', festival)])
        self.assertIsNone(home['getting_started'])  # first steps are for players

        self.assertEqual(self.items(), [('manifestation', festival)])
        self.assertEqual(self.items(role='organizer'), [('manifestation', festival)])
        self.assertEqual(self.items(type='tables'), [])

        festival.status = Event.DRAFT
        festival.save(update_fields=['status'])
        with override('it'):
            draft = pgettext('status', 'Draft')
        self.assertContains(self.client.get(reverse('account-activities')), draft)

    def test_the_player_finds_the_festival_day_they_signed_up_for(self):
        festival = self.data.manifestation
        self.login('player')
        self.assertIn(('manifestation', festival), self.items())
        self.assertEqual(self.items(role='organizer'), [])  # they attend, they don't run it
        self.assertTrue(self.client.get(reverse('home')).context['more_activities'])
        self.assertContains(self.client.get(reverse('account-activities'), {'q': festival.name}),
                            italian("You're attending"))

        # Not published (any more): gone for who only attends
        festival.status = Event.DRAFT
        festival.save(update_fields=['status'])
        self.assertNotIn(('manifestation', festival), self.items())

    def test_the_member_finds_the_event_they_proposed(self):
        draft = self.data.draft_event
        self.login('member')
        self.assertIn(('event', draft), self.items(role='organizer'))
        page = self.client.get(draft.get_absolute_url())
        self.assertContains(page, italian('Proposal waiting'))
        self.assertNotContains(page, reverse('event-manage', args=[draft.slug]))
        self.assertNotContains(page, reverse('event-program', args=[draft.slug]))  # closed until published
        self.assertNotContains(page, reverse('event-games', args=[draft.slug]))

        self.login('player')  # anyone else still gets nothing
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)

        Event.objects.filter(pk=draft.pk).update(status=Event.BLOCKED)
        self.login('member')
        self.assertEqual(self.client.get(draft.get_absolute_url()).status_code, 404)
        self.assertNotIn(('event', draft), self.items(role='organizer'))

    def test_a_proposal_leads_to_its_page(self):
        self.login('member')
        location = self.data.associazione
        response = self.client.post(reverse('location-event-create', args=[location.slug]), {
            'name': 'Seconda proposta', 'venue_location': location.pk,
            'date': (timezone.localdate()).isoformat(),
        })
        event = Event.objects.get(name='Seconda proposta')
        self.assertEqual(event.status, Event.DRAFT)
        self.assertRedirects(response, event.get_absolute_url())

    def test_managers_are_not_asked_to_become_members(self):
        page = reverse('location-detail', args=[self.data.circolo.slug])
        request_membership = reverse('location-request-membership', args=[self.data.circolo.slug])
        self.login('manager')
        self.assertNotContains(self.client.get(page), request_membership)
        self.assertContains(self.client.get(page, {'as': 'visitor'}), request_membership)  # the preview
        self.login('newcomer')
        self.assertContains(self.client.get(page), request_membership)
