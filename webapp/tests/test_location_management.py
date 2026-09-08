from django.test import TestCase, Client
from django.urls import reverse
from webapp.models import Location, UserProfile
from webapp.factories import UserProfileFactory, LocationFactory, UserFactory


class LocationManagementTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.regular_user = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner)
        self.location.managers.add(self.manager)

    def test_manage_index_access(self):
        # Owner access
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('location-manage', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)

        # Manager access
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse('location-manage', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)

        # Regular user access (forbidden)
        self.client.force_login(self.regular_user.user)
        response = self.client.get(reverse('location-manage', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 403)

        # Anonymous user (redirect to login)
        self.client.logout()
        response = self.client.get(reverse('location-manage', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 302)

    def test_manage_managers_access(self):
        url = reverse('location-manage-managers', kwargs={'slug': self.location.slug})
        # The transfer form's action is owner-only and, unlike its label, does
        # not change with the active language.
        transfer_url = reverse('location-transfer-ownership', kwargs={'slug': self.location.slug})

        # Owner access
        self.client.force_login(self.owner.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, transfer_url)

        # Manager access: no way to transfer ownership
        self.client.force_login(self.manager.user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, transfer_url)

        # Regular user access
        self.client.force_login(self.regular_user.user)
        response = self.client.get(reverse('location-manage-managers', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 403)

    def test_manage_data_access(self):
        # Owner access
        self.client.force_login(self.owner.user)
        response = self.client.get(reverse('location-manage-data', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)

        # Manager access
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse('location-manage-data', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)

        # Regular user access
        self.client.force_login(self.regular_user.user)
        response = self.client.get(reverse('location-manage-data', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 403)

    def test_add_manager(self):
        new_manager = UserProfileFactory()
        self.client.force_login(self.manager.user)

        response = self.client.post(reverse('location-add-manager', kwargs={'slug': self.location.slug}), {
            'manager': new_manager.id
        })

        self.assertRedirects(response, reverse('location-manage-managers', kwargs={'slug': self.location.slug}))
        self.assertTrue(self.location.managers.filter(id=new_manager.id).exists())

    def test_remove_manager(self):
        other_manager = UserProfileFactory()
        self.location.managers.add(other_manager)

        # Manager removing another manager
        self.client.force_login(self.manager.user)
        response = self.client.post(reverse('location-remove-manager', kwargs={'slug': self.location.slug, 'manager_id': other_manager.id}))

        self.assertRedirects(response, reverse('location-manage-managers', kwargs={'slug': self.location.slug}))
        self.assertFalse(self.location.managers.filter(id=other_manager.id).exists())

    def test_cannot_remove_owner(self):
        self.client.force_login(self.manager.user)
        response = self.client.post(reverse('location-remove-manager', kwargs={'slug': self.location.slug, 'manager_id': self.owner.id}))

        # Should redirect back
        self.assertRedirects(response, reverse('location-manage-managers', kwargs={'slug': self.location.slug}))
        # Owner should still be creator (and obviously not in managers list as M2M, but permissions check relies on creator field)
        self.location.refresh_from_db()
        self.assertEqual(self.location.creator, self.owner)

    def _location_data(self, **overrides):
        return {
            'name': "New Location Name",
            'description': 'New description',
            'address': 'New Address',
            'city': 'New City',
            'latitude': '45.0',
            'longitude': '9.0',
            'is_public': True,
            **overrides,
        }

    def test_update_location_data(self):
        self.client.force_login(self.manager.user)
        data = self._location_data()
        self.client.post(
            reverse('location-manage-data', kwargs={'slug': self.location.slug}), data)

        self.location.refresh_from_db()
        self.assertEqual(self.location.name, data['name'])
        # Verify creator hasn't changed
        self.assertEqual(self.location.creator, self.owner)

    def test_a_manager_cannot_take_over_the_location(self):
        """Ownership only moves through the owner-only transfer flow."""
        self.client.force_login(self.manager.user)
        self.client.post(
            reverse('location-manage-data', kwargs={'slug': self.location.slug}),
            self._location_data(creator=self.manager.id))

        self.location.refresh_from_db()
        self.assertEqual(self.location.creator, self.owner)

    def test_updating_a_location_cannot_blank_the_owner(self):
        self.client.force_login(self.manager.user)
        self.client.post(
            reverse('location-manage-data', kwargs={'slug': self.location.slug}),
            self._location_data(creator=''))

        self.location.refresh_from_db()
        self.assertEqual(self.location.creator, self.owner)
