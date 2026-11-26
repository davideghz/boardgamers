from urllib.parse import urlencode

from django.test import TestCase
from django.urls import reverse

from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian

LEAVE_DIALOG = 'id="leave-table-dialog"'


class TableParticipationUiTest(TestCase):
    """What each demo persona sees about joining a table (see `seed_ui_personas`)."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def get(self, url, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(url)

    def table_url(self, key):
        return reverse('table-detail', args=[self.data.tables[key].slug])

    def test_players_see_they_are_in_with_calendar_first(self):
        table = self.data.tables['upcoming']
        response = self.get(self.table_url('upcoming'), 'player')

        self.assertContains(response, italian("You're in"), count=2)  # sidebar and mobile bar
        self.assertContains(response, LEAVE_DIALOG, count=1)
        self.assertContains(response, reverse('leave_table', args=[table.slug]), count=1)
        self.assertNotContains(response, reverse('join_table', args=[table.slug]))
        # The calendar link is the main action, no longer repeated below it
        self.assertContains(response, 'action=TEMPLATE', count=2)

    def test_others_get_the_join_button(self):
        table = self.data.tables['upcoming']
        response = self.get(self.table_url('upcoming'), 'newcomer')

        self.assertContains(response, reverse('join_table', args=[table.slug]), count=2)
        self.assertNotContains(response, LEAVE_DIALOG)
        self.assertNotContains(response, italian("You're in"))

    def test_visitors_learn_whose_members_may_join(self):
        url = self.table_url('members')
        response = self.get(url)

        notice = italian('Reserved for members of %(name)s') % {'name': self.data.circolo.name}
        self.assertContains(response, notice, count=2)
        self.assertContains(response, f"{reverse('login')}?{urlencode({'next': url})}")
        self.assertContains(response, reverse('location-request-membership', args=[self.data.circolo.slug]))
        self.assertNotContains(response, italian('Login to join table'))

    def test_pending_members_are_told_to_wait(self):
        table = self.data.tables['members']
        response = self.get(self.table_url('members'), 'player')

        self.assertContains(response, italian('Membership pending'))
        self.assertNotContains(response, reverse('join_table', args=[table.slug]))
        self.assertNotContains(response, reverse('location-request-membership', args=[self.data.circolo.slug]))

    def test_members_are_in(self):
        self.assertContains(self.get(self.table_url('members'), 'member'), italian("You're in"))

    def test_event_tables_behave_the_same(self):
        table = self.data.tables['event']
        url = reverse('event_table_detail', args=[self.data.event.slug, table.slug])

        response = self.get(url, 'player')
        self.assertContains(response, italian("You're in"), count=2)
        self.assertContains(response, LEAVE_DIALOG, count=1)

        response = self.get(url, 'newcomer')
        self.assertContains(response, reverse('join_table', args=[table.slug]), count=2)


class EventMembersOnlyUiTest(TestCase):
    """«Serata Demo» belongs to «Associazione Demo», whose events are for members only."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()
        cls.url = reverse('event_detail', args=[cls.data.night.slug])
        cls.notice = italian('Reserved for members of %(name)s') % {'name': cls.data.associazione.name}

    def get(self, persona=None):
        self.client.logout()
        if persona:
            self.client.force_login(self.data.profile(persona).user)
        return self.client.get(self.url)

    def test_non_members_learn_why_and_how(self):
        response = self.get('newcomer')

        self.assertContains(response, self.notice)
        self.assertContains(response, reverse('location-request-membership', args=[self.data.associazione.slug]))

    def test_visitors_get_the_notice_instead_of_log_in_to_attend(self):
        response = self.get()

        self.assertContains(response, self.notice)
        self.assertContains(response, f"{reverse('login')}?{urlencode({'next': self.url})}")
        self.assertNotContains(response, italian('Log in to attend'))

    def test_members_see_no_notice(self):
        self.assertNotContains(self.get('member'), self.notice)
