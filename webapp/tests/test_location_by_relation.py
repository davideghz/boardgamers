import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.models import LocationFollower, Membership
from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import add_membership, italian

MANAGER_BAR = italian('View as a visitor')
MEMBERSHIP_CARD = 'id="membership-card-title"'
VISITOR_INTRO = italian('At a glance')


class LocationByRelationTest(TestCase):
    """What the top of the location page shows for each relation (see services/viewer.py)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, location, persona=None, query=''):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(reverse('location-detail', args=[location.slug]) + query)

    def assert_top(self, response, relation, shown):
        self.assertEqual(response.context['relation'], relation)
        for marker in (MANAGER_BAR, MEMBERSHIP_CARD, VISITOR_INTRO):
            (self.assertContains if marker == shown else self.assertNotContains)(response, marker)

    def test_six_relations(self):
        cases = [
            ('anonymous', self.data.circolo, None, VISITOR_INTRO),
            ('visitor', self.data.circolo, 'newcomer', VISITOR_INTRO),
            ('follower', self.data.negozio, 'player', VISITOR_INTRO),
            ('pending', self.data.circolo, 'player', MEMBERSHIP_CARD),
            ('member', self.data.circolo, 'member', MEMBERSHIP_CARD),
            ('manager', self.data.circolo, 'manager', MANAGER_BAR),
        ]
        for relation, location, persona, shown in cases:
            with self.subTest(relation):
                self.assert_top(self.get(location, persona), relation, shown)

    def test_members_and_managers_get_the_description_folded(self):
        self.assertContains(self.get(self.data.circolo, 'member'), '<details>')
        self.assertContains(self.get(self.data.circolo, 'manager'), '<details>')
        self.assertNotContains(self.get(self.data.circolo, 'newcomer'), '<details>')

    def test_the_manager_bar_lists_what_waits_here(self):
        response = self.get(self.data.circolo, 'manager')
        self.assertEqual([item.key for item in response.context['location_todo']], ['membership_requests'])
        self.assertContains(response, reverse('location-manage-members', args=[self.data.circolo.slug]))

    def test_managers_can_preview_the_page_as_a_visitor(self):
        response = self.get(self.data.circolo, 'manager', '?as=visitor')

        self.assert_top(response, 'visitor', VISITOR_INTRO)
        self.assertContains(response, italian('Back to your view'))
        # A visitor of this members-only club is not offered to create tables
        self.assertTrue(response.context['table_creation'].needs_membership)
        # ...and the follow box is back, as visitors see it
        self.assertContains(response, reverse('follow-location', args=[self.data.circolo.slug]))

    def test_others_cannot_force_the_preview(self):
        self.assertEqual(self.get(self.data.circolo, 'member', '?as=visitor').context['relation'], 'member')

    def test_joined_tables_are_marked(self):
        response = self.get(self.data.circolo, 'member')
        self.assertContains(response, italian("You're in"), count=1)
        self.assertNotContains(self.get(self.data.circolo, 'newcomer'), italian("You're in"))


class MembershipCardTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def card(self, membership_end):
        member = self.data.member
        Membership.objects.filter(member__user_profile=member, member__location=self.data.circolo).update(
            end_date=membership_end)
        self.client.force_login(member.user)
        return self.client.get(reverse('location-detail', args=[self.data.circolo.slug]))

    def test_active_membership_shows_its_end_date(self):
        response = self.card(timezone.localdate() + datetime.timedelta(days=200))
        self.assertEqual(response.context['membership'].state(), 'active')
        self.assertNotContains(response, italian('Renew'))

    def test_renew_within_thirty_days_and_after_the_end(self):
        for days, state in ((20, 'expiring'), (-3, 'expired')):
            with self.subTest(state):
                response = self.card(timezone.localdate() + datetime.timedelta(days=days))
                self.assertEqual(response.context['membership'].state(), state)
                self.assertContains(response, italian('Renew'))

    def test_an_expiring_member_may_request_the_renewal(self):
        url = reverse('location-request-membership', args=[self.data.circolo.slug])
        self.card(timezone.localdate() + datetime.timedelta(days=200))
        self.assertEqual(self.client.get(url).status_code, 302)  # too early: back to the location

        self.card(timezone.localdate() + datetime.timedelta(days=20))
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_pending_renewal_blocks_further_requests(self):
        self.card(timezone.localdate() + datetime.timedelta(days=20))
        add_membership(self.data.circolo, self.data.member, Membership.PENDING)
        url = reverse('location-request-membership', args=[self.data.circolo.slug])
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_former_members_see_the_card_too(self):
        LocationFollower.objects.filter(user_profile=self.data.member).delete()
        response = self.card(timezone.localdate() - datetime.timedelta(days=40))
        self.assertEqual(response.context['relation'], 'visitor')
        self.assertContains(response, MEMBERSHIP_CARD)
