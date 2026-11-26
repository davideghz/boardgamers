import base64
import datetime
from io import BytesIO
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from PIL import Image, ImageDraw

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import Member, Membership, MembershipDocument, SignedMembershipDocument
from webapp.services import member_documents

BODY = (
    '<h2>Domanda di ammissione</h2>'
    '<p>Il sottoscritto <strong>{{first_name}} {{last_name}}</strong>, C.F. {{fiscal_code}}, '
    'nato a {{birth_place}} il {{birth_date}}, chiede di entrare in {{location_name}}.</p>'
    '<ul><li>Accetto lo statuto</li></ul><p>{{date}} Firma {{signature}}</p>'
)

IN_MEMORY_STORAGES = {
    **settings.STORAGES,
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'private': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
}


def a_signature(blank=False):
    image = Image.new('RGBA', (400, 150), (0, 0, 0, 0))
    if not blank:
        ImageDraw.Draw(image).line([(20, 120), (150, 30), (380, 110)], fill=(0, 0, 0, 255), width=5)
    out = BytesIO()
    image.save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


class BodyAndSignatureTest(SimpleTestCase):

    def test_sanitize_keeps_formatting_and_placeholders_only(self):
        body = member_documents.sanitize_body(
            '<p style="color:red" onclick="x()">Ciao {{first_name}}</p><script>alert(1)</script>'
            '<a href="https://evil.example">link</a><img src=x>')
        self.assertEqual(body, '<p>Ciao {{first_name}}</p>link')

    def test_used_placeholders_ignores_unknown_keys(self):
        self.assertEqual(
            member_documents.used_placeholders('{{ last_name }} {{first_name}} {{password}}'),
            ['first_name', 'last_name'])

    def test_render_html_escapes_the_values(self):
        html = member_documents.render_html('<p>{{first_name}}</p>', {'first_name': '<b>Mario</b>'})
        self.assertIn('&lt;b&gt;Mario&lt;/b&gt;', html)
        self.assertNotIn('<b>Mario', html)

    def test_decode_signature_accepts_a_drawing(self):
        png = member_documents.decode_signature(a_signature())
        self.assertTrue(png.startswith(b'\x89PNG'))

    def test_decode_signature_rejects_blank_and_garbage(self):
        for value in ('', 'data:image/png;base64,not-base64!', 'data:image/jpeg;base64,AAAA', a_signature(blank=True)):
            with self.subTest(value=value[:30]), self.assertRaises(ValueError):
                member_documents.decode_signature(value)

    def test_build_pdf_with_and_without_a_signature_placeholder(self):
        png = member_documents.decode_signature(a_signature())
        for body in (BODY, '<p>Senza firma {{first_name}} & <x></p>'):
            with self.subTest(body=body[:20]):
                pdf = member_documents.build_pdf(
                    title='Modulo', location_name='APS', body=body,
                    values={'first_name': 'Mario & Co'}, signature_png=png, signer_name='Mario',
                    audit_lines=['audit'])
                self.assertTrue(pdf.startswith(b'%PDF'))


class OnlineDocumentTestCase(TestCase):

    def setUp(self):
        self.enterContext(override_settings(STORAGES=IN_MEMORY_STORAGES))
        self.client = Client()
        self.owner = UserProfileFactory()
        self.manager = UserProfileFactory()
        self.outsider = UserProfileFactory()
        self.user = UserProfileFactory()
        self.location = LocationFactory(creator=self.owner, enable_membership=True)
        self.location.managers.add(self.manager)
        self.document = MembershipDocument.objects.create(
            location=self.location, name='Modulo 2026', kind=MembershipDocument.ONLINE, body=BODY)

    def _member(self, user_profile=None, status=Membership.PENDING):
        member = Member.objects.create(
            location=self.location, user_profile=user_profile, first_name='Mario', last_name='Rossi')
        membership = Membership.objects.create(member=member, status=status)
        return member, membership

    def _sign_data(self, **overrides):
        data = {
            'first_name': 'Mario', 'last_name': 'Rossi', 'fiscal_code': 'RSSMRA85M01H501Z',
            'birth_place': 'Roma', 'birth_date': '1985-08-01',
            'signature': a_signature(), 'accept': 'on',
        }
        data.update(overrides)
        return data


class EditorTest(OnlineDocumentTestCase):

    def test_manager_writes_a_document(self):
        self.client.force_login(self.manager.user)
        response = self.client.post(reverse('location-membership-document-new', args=[self.location.slug]), {
            'name': 'Privacy', 'is_active': 'on',
            'body': '<p onclick="x()">Io {{first_name}}</p><div>riga</div><script>x</script>',
        })
        self.assertRedirects(response, reverse('location-membership-documents', args=[self.location.slug]))
        document = self.location.membership_documents.get(name='Privacy')
        self.assertEqual(document.kind, MembershipDocument.ONLINE)
        self.assertEqual(document.body, '<p>Io {{first_name}}</p>riga')

    def test_an_empty_text_is_rejected(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(reverse('location-membership-document-new', args=[self.location.slug]), {
            'name': 'Vuoto', 'body': '<p><br></p>',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.location.membership_documents.filter(name='Vuoto').exists())

    def test_outsider_cannot_open_the_editor_or_the_preview(self):
        self.client.force_login(self.outsider.user)
        for url in (reverse('location-membership-document-new', args=[self.location.slug]),
                    reverse('location-membership-document-edit', args=[self.location.slug, self.document.uuid]),
                    reverse('location-membership-document-preview', args=[self.location.slug, self.document.uuid])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_preview_is_a_pdf(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(
            reverse('location-membership-document-preview', args=[self.location.slug, self.document.uuid]))
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_an_uploaded_document_still_needs_a_file(self):
        self.client.force_login(self.owner.user)
        response = self.client.post(reverse('location-membership-documents', args=[self.location.slug]), {
            'name': 'Statuto', 'is_active': 'on',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.location.membership_documents.filter(name='Statuto').exists())


class MemberSignsOnlineTest(OnlineDocumentTestCase):

    def setUp(self):
        super().setUp()
        self.sign_url = reverse('location-sign-document', args=[self.location.slug, self.document.uuid])

    def test_membership_request_leads_to_the_signature(self):
        self.client.force_login(self.user.user)
        response = self.client.post(reverse('location-request-membership', args=[self.location.slug]), {
            'first_name': 'Mario', 'last_name': 'Rossi', 'email': 'mario@example.com',
        })
        self.assertRedirects(response, self.sign_url)

    def test_member_signs_the_document(self):
        member, membership = self._member(self.user)
        self.client.force_login(self.user.user)
        self.assertContains(self.client.get(self.sign_url), 'data-placeholder="first_name"')

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.sign_url, self._sign_data(birth_place='Milano'),
                                        HTTP_X_FORWARDED_FOR='10.0.0.1, 93.184.216.34')
        self.assertRedirects(response, reverse('account-memberships'))

        signed = SignedMembershipDocument.objects.get()
        self.assertEqual(signed.member, member)
        self.assertEqual(signed.membership, membership)
        self.assertEqual(signed.signed_by, self.user)
        self.assertIsNone(signed.collected_by)
        self.assertEqual(signed.ip_address, '93.184.216.34')
        self.assertEqual(len(signed.sha256), 64)
        with signed.pdf.open('rb') as pdf:
            self.assertTrue(pdf.read().startswith(b'%PDF'))
        self.assertEqual(signed.pdf.storage.__class__.__name__, 'InMemoryStorage')

        member.refresh_from_db()
        self.assertEqual(member.birth_place, 'Milano')
        self.assertEqual(member.birth_date, datetime.date(1985, 8, 1))
        membership.refresh_from_db()
        self.assertTrue(membership.signed_document)

        # The owner and the manager are told; the email carries no PDF.
        self.assertEqual(sorted(m.to[0] for m in mail.outbox),
                         sorted([self.owner.user.email, self.manager.user.email]))
        self.assertFalse(mail.outbox[0].attachments)

    def test_paper_documents_keep_the_flag_off(self):
        MembershipDocument.objects.create(
            location=self.location, name='Statuto', file=SimpleUploadedFile('s.pdf', b'%PDF-1.4'))
        _member, membership = self._member(self.user)
        self.client.force_login(self.user.user)
        self.client.post(self.sign_url, self._sign_data())
        membership.refresh_from_db()
        self.assertFalse(membership.signed_document)

    def test_without_a_signature_nothing_is_saved(self):
        self._member(self.user)
        self.client.force_login(self.user.user)
        response = self.client.post(self.sign_url, self._sign_data(signature=a_signature(blank=True)))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SignedMembershipDocument.objects.exists())

    def test_the_fields_used_in_the_text_are_required(self):
        self._member(self.user)
        self.client.force_login(self.user.user)
        response = self.client.post(self.sign_url, self._sign_data(birth_place=''))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(SignedMembershipDocument.objects.exists())

    def test_a_storage_failure_leaves_the_member_untouched(self):
        member, _membership = self._member(self.user)
        self.client.force_login(self.user.user)
        with mock.patch('django.core.files.storage.InMemoryStorage._save', side_effect=OSError('bucket down')):
            with self.assertRaises(OSError):
                self.client.post(self.sign_url, self._sign_data(birth_place='Milano'))
        member.refresh_from_db()
        self.assertEqual(member.birth_place, '')
        self.assertFalse(SignedMembershipDocument.objects.exists())

    def test_without_a_membership_the_user_is_sent_to_request_one(self):
        self.client.force_login(self.user.user)
        response = self.client.get(self.sign_url)
        self.assertRedirects(response, reverse('location-request-membership', args=[self.location.slug]))

    def test_a_signed_document_is_not_signed_twice(self):
        self._member(self.user)
        self.client.force_login(self.user.user)
        self.client.post(self.sign_url, self._sign_data())
        response = self.client.post(self.sign_url, self._sign_data())
        self.assertRedirects(response, reverse('account-memberships'))
        self.assertEqual(SignedMembershipDocument.objects.count(), 1)

    def test_member_downloads_only_their_own_copy(self):
        self._member(self.user)
        self.client.force_login(self.user.user)
        self.client.post(self.sign_url, self._sign_data())
        signed = SignedMembershipDocument.objects.get()
        url = reverse('account-signed-document', args=[signed.uuid])

        response = self.client.get(url)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_memberships_page_links_the_documents(self):
        self._member(self.user)
        self.client.force_login(self.user.user)
        self.assertContains(self.client.get(reverse('account-memberships')), self.sign_url)
        self.client.post(self.sign_url, self._sign_data())
        signed = SignedMembershipDocument.objects.get()
        self.assertContains(self.client.get(reverse('account-memberships')),
                            reverse('account-signed-document', args=[signed.uuid]))


class ManagerCollectsSignatureTest(OnlineDocumentTestCase):

    def setUp(self):
        super().setUp()
        self.member, self.membership = self._member()  # no account
        self.sign_url = reverse('location-member-sign-document',
                                args=[self.location.slug, self.member.uuid, self.document.uuid])
        self.detail_url = reverse('location-member-detail', args=[self.location.slug, self.member.uuid])

    def test_manager_collects_a_signature_in_person(self):
        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(self.detail_url), self.sign_url)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.sign_url, self._sign_data())
        self.assertRedirects(response, self.detail_url)

        signed = SignedMembershipDocument.objects.get()
        self.assertEqual(signed.collected_by, self.manager)
        self.assertIsNone(signed.signed_by)
        # The manager who collected it already knows.
        self.assertEqual([m.to[0] for m in mail.outbox], [self.owner.user.email])

    def test_outsider_cannot_collect_signatures(self):
        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(self.sign_url).status_code, 403)

    def test_a_member_without_a_current_membership_cannot_sign(self):
        self.membership.status = Membership.EXPIRED
        self.membership.save()
        self.client.force_login(self.manager.user)
        self.assertRedirects(self.client.get(self.sign_url), self.detail_url)

    def test_download_and_delete_are_for_managers(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.sign_url, self._sign_data())
        signed = SignedMembershipDocument.objects.get()
        url = reverse('location-member-signed-document', args=[self.location.slug, self.member.uuid, signed.uuid])

        self.assertEqual(self.client.get(url)['Content-Type'], 'application/pdf')

        self.client.force_login(self.outsider.user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)

        self.client.force_login(self.owner.user)
        storage, name = signed.pdf.storage, signed.pdf.name
        self.assertRedirects(self.client.post(url), self.detail_url, fetch_redirect_response=False)
        self.assertFalse(SignedMembershipDocument.objects.exists())
        self.assertFalse(storage.exists(name))

    def test_the_signed_copy_outlives_the_document(self):
        self.client.force_login(self.manager.user)
        self.client.post(self.sign_url, self._sign_data())
        self.document.delete()
        signed = SignedMembershipDocument.objects.get()
        self.assertIsNone(signed.document)
        self.assertEqual(signed.document_name, 'Modulo 2026')
