import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext

from webapp.factories import LocationFactory, SuperUserProfileFactory, UserProfileFactory
from webapp.models import Membership, Table
from webapp.tests.access_matrix import ANYONE, MANAGERS, MEMBERS, PENDING, AccessMatrixMixin, add_membership


def italian(message):
    """`message` as the pages render it: the site language is Italian."""
    with translation.override('it'):
        return gettext(message)


class TableAccessTest(AccessMatrixMixin, TestCase):
    def test_table_creation(self):
        self.assert_matrix('table_creation_permission', 'table_creation_access', [ANYONE, MEMBERS, MANAGERS])

    def test_table_join(self):
        self.assert_matrix('table_join_permission', 'table_join_access', [ANYONE, MEMBERS])

    def test_reports_what_it_looked_up(self):
        self.location.table_creation_permission = MEMBERS
        access = self.location.table_creation_access
        self.assertTrue(access(self.profiles['manager']).is_manager)
        self.assertIsNone(access(self.profiles['manager']).membership)
        self.assertTrue(access(self.profiles['member']).is_active_member)
        self.assertTrue(access(self.profiles['pending']).membership_pending)
        self.assertTrue(access(self.profiles['pending']).needs_membership)
        self.assertIsNone(access(self.profiles['outsider']).membership)

    def test_active_membership_wins_over_a_pending_renewal(self):
        profile = self.profiles['member']
        add_membership(self.location, profile, Membership.PENDING)
        self.location.table_creation_permission = MEMBERS

        access = self.location.table_creation_access(profile)

        self.assertTrue(access.allowed)
        self.assertEqual(access.membership, Membership.ACTIVE)


class TableAccessViewsTest(TestCase):
    def setUp(self):
        self.location = LocationFactory(
            creator=UserProfileFactory(),
            table_creation_permission=MEMBERS, table_join_permission=MEMBERS, enable_membership=True)
        self.profile = UserProfileFactory()

    def login(self, profile):
        self.client.force_login(profile.user)

    def test_create_view_refuses_a_pending_member(self):
        add_membership(self.location, self.profile, Membership.PENDING)
        self.login(self.profile)

        response = self.client.get(reverse('location-table-create', args=[self.location.slug]))

        self.assertRedirects(response, reverse('location-detail', args=[self.location.slug]),
                             fetch_redirect_response=False)

    def test_create_view_lets_an_active_member_in(self):
        add_membership(self.location, self.profile, Membership.ACTIVE)
        self.login(self.profile)

        response = self.client.get(reverse('location-table-create', args=[self.location.slug]))

        self.assertEqual(response.status_code, 200)

    def test_location_page_shows_the_pending_membership(self):
        add_membership(self.location, self.profile, Membership.PENDING)
        self.login(self.profile)

        response = self.client.get(reverse('location-detail', args=[self.location.slug]))

        self.assertEqual(response.context['table_creation'].reason, PENDING)
        self.assertTrue(response.context['has_pending_membership'])
        self.assertContains(response, italian('Only members can create tables here.'))
        self.assertNotContains(response, reverse('location-table-create', args=[self.location.slug]))

    def test_location_page_offers_table_creation_to_a_superuser(self):
        self.login(SuperUserProfileFactory())

        response = self.client.get(reverse('location-detail', args=[self.location.slug]))

        self.assertContains(response, reverse('location-table-create', args=[self.location.slug]))

    def test_table_page_lets_a_renewing_member_join(self):
        add_membership(self.location, self.profile, Membership.ACTIVE)
        add_membership(self.location, self.profile, Membership.PENDING)
        table = Table.objects.create(
            title='Serata', location=self.location, author=self.location.creator,
            date=timezone.localdate() + datetime.timedelta(days=3), time=datetime.time(21))
        self.login(self.profile)

        response = self.client.get(reverse('table-detail', args=[table.slug]))

        self.assertTrue(response.context['table_join'].allowed)
        self.assertNotContains(response, italian('Table reserved for members'))
        self.assertContains(response, reverse('join_table', args=[table.slug]))
