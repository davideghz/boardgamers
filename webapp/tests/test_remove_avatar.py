from unittest import mock

from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory


class RemoveAvatarTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.user_profile.avatar = 'avatars/me.png'
        self.user_profile.save()
        self.url = reverse('remove-avatar')

        # Deleting would otherwise hit S3.
        patcher = mock.patch('storages.backends.s3.S3Storage.delete')
        self.delete_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_removes_the_avatar_and_its_file(self):
        self.client.force_login(self.user_profile.user)
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('user-profile-edit'), fetch_redirect_response=False)
        self.user_profile.refresh_from_db()
        self.assertFalse(self.user_profile.avatar)
        self.delete_mock.assert_called_once_with('avatars/me.png')

    def test_get_is_not_allowed(self):
        self.client.force_login(self.user_profile.user)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.user_profile.refresh_from_db()
        self.assertTrue(self.user_profile.avatar)

    def test_anonymous_user_is_redirected_to_login(self):
        self.assertEqual(self.client.post(self.url).status_code, 302)
        self.user_profile.refresh_from_db()
        self.assertTrue(self.user_profile.avatar)

    def test_edit_page_shows_the_remove_button_only_with_an_avatar(self):
        self.client.force_login(self.user_profile.user)
        edit_url = reverse('user-profile-edit')
        self.assertContains(self.client.get(edit_url), self.url)
        self.user_profile.avatar = None
        self.user_profile.save()
        self.assertNotContains(self.client.get(edit_url), self.url)
