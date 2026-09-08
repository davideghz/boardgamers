from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import Member, Membership, MembershipDocument


def a_pdf(name='modulo.pdf', size=1024):
    return SimpleUploadedFile(name, b'%PDF-1.4' + b'0' * size, content_type='application/pdf')


class MembershipDocumentManagementTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner, enable_membership=True)
        self.location.managers.add(self.manager)
        self.list_url = reverse('location-membership-documents', kwargs={'slug': self.location.slug})

        # Uploads would otherwise hit S3.
        patcher = mock.patch('storages.backends.s3.S3Storage._save', side_effect=lambda name, content: name)
        self.save_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def _document(self, name='Modulo di adesione', is_active=True):
        return MembershipDocument.objects.create(
            location=self.location, name=name, is_active=is_active,
            file='membership-documents/modulo.pdf',
        )

    def test_manager_can_upload_a_document(self):
        self.client.force_login(self.manager.user)
        response = self.client.post(self.list_url, {
            'name': 'Modulo di adesione', 'file': a_pdf(), 'is_active': 'on',
        })
        self.assertRedirects(response, self.list_url)

        document = self.location.membership_documents.get()
        self.assertEqual(document.name, 'Modulo di adesione')
        self.assertTrue(document.is_active)

    def test_unsupported_file_type_is_rejected(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(self.list_url, {
            'name': 'Modulo', 'is_active': 'on',
            'file': SimpleUploadedFile('modulo.exe', b'MZ', content_type='application/octet-stream'),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MembershipDocument.objects.exists())

    def test_oversized_file_is_rejected(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(self.list_url, {
            'name': 'Modulo', 'is_active': 'on', 'file': a_pdf(size=6 * 1024 * 1024),
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(MembershipDocument.objects.exists())

    def test_outsider_cannot_list_or_upload(self):
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.post(self.list_url, {'name': 'X', 'file': a_pdf()}).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.assertEqual(self.client.get(self.list_url).status_code, 302)

    def test_documents_require_membership_to_be_enabled(self):
        # Consistent with the other member management views: a location with
        # membership turned off has no such page at all.
        self.location.enable_membership = False
        self.location.save()
        self.client.force_login(self.owner.user)
        self.assertEqual(self.client.get(self.list_url).status_code, 404)

    def test_rename_toggle_and_delete(self):
        document = self._document()
        action_url = reverse('location-membership-document-action', kwargs={
            'slug': self.location.slug, 'document_uuid': document.uuid,
        })
        self.client.force_login(self.manager.user)

        self.client.post(action_url, {'name': 'Statuto'})
        document.refresh_from_db()
        self.assertEqual(document.name, 'Statuto')

        self.client.post(action_url, {'action': 'toggle'})
        document.refresh_from_db()
        self.assertFalse(document.is_active)

        self.client.post(action_url, {'action': 'delete'})
        self.assertFalse(MembershipDocument.objects.filter(pk=document.pk).exists())

    def test_a_document_of_another_location_is_not_reachable(self):
        other_location = LocationFactory(creator=self.owner, enable_membership=True)
        document = MembershipDocument.objects.create(
            location=other_location, name='Altro', file='membership-documents/altro.pdf')
        self.client.force_login(self.owner.user)
        response = self.client.post(reverse('location-membership-document-action', kwargs={
            'slug': self.location.slug, 'document_uuid': document.uuid,
        }), {'action': 'delete'})
        self.assertEqual(response.status_code, 404)


class MembershipDocumentVisibilityTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        self.active = MembershipDocument.objects.create(
            location=self.location, name='Modulo di adesione',
            file='membership-documents/modulo.pdf')
        self.hidden = MembershipDocument.objects.create(
            location=self.location, name='Vecchio modulo', is_active=False,
            file='membership-documents/vecchio.pdf')
        self.client.force_login(self.user_profile.user)

    def test_request_page_lists_only_active_documents(self):
        response = self.client.get(
            reverse('location-request-membership', kwargs={'slug': self.location.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Modulo di adesione')
        self.assertNotContains(response, 'Vecchio modulo')

    def test_memberships_page_lists_only_active_documents(self):
        member = Member.objects.create(
            location=self.location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi')
        Membership.objects.create(member=member, status=Membership.PENDING)

        response = self.client.get(reverse('account-memberships'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Modulo di adesione')
        self.assertNotContains(response, 'Vecchio modulo')

    def test_requesting_a_membership_points_at_the_documents(self):
        response = self.client.post(
            reverse('location-request-membership', kwargs={'slug': self.location.slug}),
            {'first_name': 'Mario', 'last_name': 'Rossi'}, follow=True)
        texts = [str(message) for message in response.context['messages']]
        self.assertTrue(any('firmare' in text or 'sign' in text for text in texts), texts)
