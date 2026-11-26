from django.test import TestCase
from django.urls import reverse

from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian


class AccountIndexByRoleTest(TestCase):
    """The account page for each demo persona (see `seed_ui_personas`)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, persona):
        self.client.force_login(self.data.profile(persona).user)
        self.response = self.client.get(reverse('account-index'))
        return self.response

    def page(self, persona):
        """The page's own content, without the navigation that links to some of the same pages."""
        html = self.get(persona).content.decode()
        start = html.index(f'{self.data.profile(persona).nickname}</h1>')
        return html[start:html.index('<footer', start)]

    def test_entries_come_in_order(self):
        html = self.page('manager')
        order = ['user-profile-edit', 'account-activities', 'account-memberships', 'account-locations',
                 'account-tables', 'account-guests', 'account-notifications-edit', 'password_change']
        positions = [html.index(f'href="{reverse(name)}"') for name in order]
        self.assertEqual(positions, sorted(positions))

    def test_who_runs_nothing_gets_no_management_entries(self):
        html = self.page('newcomer')

        self.assertNotIn(f">{italian('Management')}</h2>", html)
        self.assertNotIn(reverse('account-locations'), html)
        self.assertNotIn(reverse('account-tables'), html)
        self.assertNotIn(reverse('account-events'), html)
        self.assertIn(reverse('location-create'), html)

    def test_managers_get_their_locations_with_a_count(self):
        html = self.page('manager')

        self.assertIn(f">{italian('Management')}</h2>", html)
        self.assertIn(reverse('account-locations'), html)
        self.assertEqual(self.response.context['managed_locations_count'], 3)
        self.assertTrue(self.response.context['manages_events'])
        self.assertNotIn(reverse('location-create'), html)

    def test_members_see_their_memberships_and_upcoming_activities(self):
        response = self.get('member')

        self.assertEqual(response.context['active_memberships_count'], 2)
        self.assertContains(response, '2 attive')
        # The members-only table they created and the evening they registered for
        self.assertEqual(response.context['upcoming_activities_count'], 2)
        self.assertContains(response, '2 in programma')

    def test_counters_stay_hidden_at_zero(self):
        html = self.page('newcomer')

        self.assertNotIn('in programma', html)
        self.assertNotIn('0 attive', html)
