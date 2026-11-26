from io import BytesIO

from django.contrib.auth.models import Permission
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, MasterEvent, Sponsor
from webapp.services.images import NETWORK_LOGO_MAX_BYTES


def png_logo():
    content = BytesIO()
    Image.new('RGBA', (600, 300), (20, 80, 120, 128)).save(content, 'PNG')
    return SimpleUploadedFile('logo.png', content.getvalue(), content_type='image/png')


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MasterSponsorTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager, cls.other_manager = [UserProfileFactory() for _ in range(2)]
        cls.master = MasterEvent.objects.create(name='Spring Festival', status=Event.PUBLISHED)
        cls.other = MasterEvent.objects.create(name='Summer Festival', status=Event.PUBLISHED)
        cls.master.managers.add(cls.manager)
        cls.other.managers.add(cls.other_manager)
        cls.add = reverse('master-sponsor-add', args=[cls.master.slug])
        cls.manage = reverse('master-event-manage-people', args=[cls.master.slug])

    def edit_url(self, sponsor):
        return reverse('master-sponsor-edit', args=[self.master.slug, sponsor.pk])

    def test_manager_can_add_edit_and_remove_an_independent_sponsor(self):
        self.client.force_login(self.manager.user)
        self.assertRedirects(self.client.post(self.add, {
            'name': 'Independent Publisher', 'website': 'https://example.org/publisher', 'logo': png_logo(),
        }), self.manage + '#master-event-sponsors')
        sponsor = self.master.sponsors.get()
        self.assertIsNone(sponsor.location_id)
        with sponsor.logo.open() as logo, Image.open(logo) as image:
            self.assertEqual((image.format, image.size), ('PNG', (512, 256)))
        self.assertContains(self.client.get(self.master.get_absolute_url()), sponsor.logo.url)
        self.assertContains(self.client.get(self.edit_url(sponsor)), f'<img src="{sponsor.logo.url}"')
        self.client.post(self.edit_url(sponsor), {'name': 'New Publisher Name', 'website': 'https://example.org/new'})
        self.client.logout()
        response = self.client.get(self.master.get_absolute_url())
        self.assertContains(response, 'New Publisher Name')
        self.assertContains(response, 'href="https://example.org/new" rel="sponsored noopener"')

        self.client.force_login(self.manager.user)
        self.client.get(self.edit_url(sponsor), {'remove': '1'})
        self.assertTrue(self.master.sponsors.filter(pk=sponsor.pk).exists())
        self.client.post(self.edit_url(sponsor), {'remove': '1'})
        self.assertFalse(self.master.sponsors.exists())
        self.assertNotContains(self.client.get(self.master.get_absolute_url()), 'New Publisher Name')

    def test_editing_a_shared_sponsor_keeps_the_other_festival_and_its_logo(self):
        sponsor = Sponsor.objects.create(
            name='Orion Books', location=LocationFactory(), website='https://example.org/orion', logo=png_logo(),
        )
        self.master.sponsors.add(sponsor)
        self.other.sponsors.add(sponsor)
        self.client.force_login(self.manager.user)
        url = self.edit_url(sponsor)
        self.client.post(url, {'name': sponsor.name, 'website': sponsor.website})
        self.assertEqual(self.master.sponsors.get().pk, sponsor.pk)

        self.client.post(url, {'name': 'Orion Books for Spring', 'website': sponsor.website})
        copy = self.master.sponsors.get()
        self.assertNotEqual(copy.pk, sponsor.pk)
        self.assertEqual(copy.location_id, sponsor.location_id)
        self.assertEqual(copy.logo.name, sponsor.logo.name)
        self.assertEqual(self.other.sponsors.get().name, 'Orion Books')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.edit_url(copy), {'name': copy.name, 'website': copy.website, 'logo-clear': 'on'})
        copy.refresh_from_db()
        self.assertFalse(copy.logo)
        self.assertTrue(default_storage.exists(sponsor.logo.name))
        self.assertContains(self.client.get(self.other.get_absolute_url()), sponsor.logo.url)
        self.client.post(self.edit_url(copy), {'remove': '1'})
        self.assertTrue(self.other.sponsors.filter(pk=sponsor.pk).exists())

    def test_permission_and_sponsor_membership_are_required(self):
        foreign = Sponsor.objects.create(name='Other sponsor')
        self.other.sponsors.add(foreign)
        self.client.force_login(self.other_manager.user)
        self.assertEqual(self.client.get(self.add).status_code, 403)
        self.assertEqual(self.client.post(self.add, {'name': 'Unauthorized'}).status_code, 403)
        self.assertEqual(self.client.post(self.edit_url(foreign), {'remove': '1'}).status_code, 403)
        self.client.force_login(self.manager.user)
        self.assertEqual(self.client.post(self.edit_url(foreign), {'name': 'Forged edit'}).status_code, 404)
        self.assertEqual(self.client.post(self.edit_url(foreign), {'remove': '1'}).status_code, 404)
        self.assertEqual(self.other.sponsors.get().name, 'Other sponsor')

    def test_logo_and_website_validation(self):
        self.client.force_login(self.manager.user)
        response = self.client.post(self.add, {
            'name': 'Invalid sponsor', 'website': 'ftp://example.org',
            'logo': SimpleUploadedFile('logo.png', b'invalid image', content_type='image/png'),
        })
        self.assertTrue(response.context['form']['logo'].errors)
        self.assertTrue(response.context['form']['website'].errors)
        response = self.client.post(self.add, {
            'name': 'Oversized logo',
            'logo': SimpleUploadedFile('logo.png', b'0' * (NETWORK_LOGO_MAX_BYTES + 1), content_type='image/png'),
        })
        self.assertTrue(response.context['form']['logo'].errors)
        self.assertFalse(Sponsor.objects.exists())

    def test_draft_sponsors_are_visible_only_with_access_to_the_draft(self):
        self.master.status = Event.DRAFT
        self.master.save(update_fields=['status'])
        sponsor = Sponsor.objects.create(name='Unannounced sponsor')
        self.master.sponsors.add(sponsor)
        self.assertEqual(self.client.get(self.master.get_absolute_url()).status_code, 404)
        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(self.master.get_absolute_url()), sponsor.name)

    def test_admin_reviewer_cannot_modify_sponsors_or_grant_self_management(self):
        reviewer = UserProfileFactory(user__is_staff=True).user
        reviewer.user_permissions.add(Permission.objects.get(
            content_type__app_label='webapp', codename='change_masterevent',
        ))
        change = reverse('admin:webapp_masterevent_change', args=[self.master.pk])
        self.client.force_login(reviewer)
        form = self.client.get(change).context['adminform'].form
        self.assertNotIn('sponsors', form.fields)
        self.assertNotIn('managers', form.fields)

        admin = UserProfileFactory(user__is_superuser=True, user__is_staff=True).user
        self.client.force_login(admin)
        sponsor = Sponsor.objects.create(name='Sponsor for both festivals')
        location = LocationFactory()
        self.other.sponsors.add(sponsor)
        response = self.client.post(change, {
            'name': self.master.name, 'description': 'Local programme', 'venue_location': location.pk,
            'sponsors': [sponsor.pk],
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.master.sponsors.get(), sponsor)
        response = self.client.post(reverse('admin:webapp_sponsor_change', args=[sponsor.pk]), {
            'name': sponsor.name, 'location': location.pk,
        })
        self.assertEqual(response.status_code, 302)
        sponsor.refresh_from_db()
        self.assertEqual(sponsor.location, location)
