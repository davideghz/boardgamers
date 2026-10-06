from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import Location


class MembershipToggleTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)
        self.members_url = reverse('location-manage-members', kwargs={'slug': self.location.slug})
        self.toggle_url = reverse('location-toggle-membership', kwargs={'slug': self.location.slug})
        self.request_url = reverse('location-request-membership', kwargs={'slug': self.location.slug})

    def test_membership_is_off_by_default(self):
        self.assertFalse(self.location.enable_membership)

    def test_management_area_is_available_while_off(self):
        self.client.force_login(self.manager.user)
        self.assertEqual(self.client.get(self.members_url).status_code, 200)
        self.assertEqual(self.client.get(reverse('location-add-member', kwargs={'slug': self.location.slug})).status_code, 200)

    def test_manage_index_always_links_to_members(self):
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('location-manage', kwargs={'slug': self.location.slug}))
        self.assertContains(response, self.members_url)

    def test_visitors_cannot_request_membership_while_off(self):
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(self.request_url).status_code, 403)
        detail = self.client.get(reverse('location-detail', kwargs={'slug': self.location.slug}))
        self.assertNotContains(detail, self.request_url)

    def test_manager_can_turn_it_on_and_off(self):
        self.client.force_login(self.manager.user)

        self.client.post(self.toggle_url, {'enabled': 'on'})
        self.location.refresh_from_db()
        self.assertTrue(self.location.enable_membership)

        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(self.request_url).status_code, 200)

        self.client.force_login(self.manager.user)
        self.client.post(self.toggle_url, {})
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_membership)

    def test_turning_off_resets_members_only_permissions(self):
        self.location.enable_membership = True
        self.location.table_creation_permission = Location.PERM_MEMBERS_ONLY
        self.location.table_join_permission = Location.PERM_MEMBERS_ONLY
        self.location.save()

        self.client.force_login(self.owner.user)
        self.client.post(self.toggle_url, {})
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_membership)
        self.assertEqual(self.location.table_creation_permission, Location.PERM_ANYONE)
        self.assertEqual(self.location.table_join_permission, Location.PERM_ANYONE)

    def test_managers_only_permission_is_kept_when_turning_off(self):
        self.location.enable_membership = True
        self.location.table_creation_permission = Location.PERM_MANAGERS_ONLY
        self.location.save()

        self.client.force_login(self.owner.user)
        self.client.post(self.toggle_url, {})
        self.location.refresh_from_db()
        self.assertEqual(self.location.table_creation_permission, Location.PERM_MANAGERS_ONLY)

    def test_outsider_cannot_toggle(self):
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.post(self.toggle_url, {'enabled': 'on'}).status_code, 403)
        self.location.refresh_from_db()
        self.assertFalse(self.location.enable_membership)
