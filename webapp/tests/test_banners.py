from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from webapp.factories import UserProfileFactory
from webapp.models import Banner
from webapp.services.images import BANNER_COVER_MAX_BYTES, COVER_MAX_SIDE, validate_banner_cover


class BannerTest(TestCase):
    def setUp(self):
        Banner.objects.update(is_active=False)
        self.banner = Banner.objects.create(key='test-banner', title='A new feature', message='Try it.', is_active=True)

    def test_home_renders_hidden_candidates_for_anonymous_and_authenticated_users(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                if authenticated:
                    self.client.force_login(UserProfileFactory().user)
                response = self.client.get(reverse('home'))
                self.assertContains(response, 'data-banner-key="test-banner"', count=1)
                self.assertContains(response, '<section hidden data-banner')
                self.assertNotContains(response, 'data-dismiss-url=')

    def test_new_banners_are_inactive_until_enabled(self):
        Banner.objects.create(key='draft', message='Not ready')
        self.assertNotContains(self.client.get(reverse('home')), 'data-banner-key="draft"')

    def test_audience_is_filtered_before_rendering(self):
        Banner.objects.create(key='members', message='Members', is_active=True, audience=Banner.Audience.AUTHENTICATED)
        Banner.objects.create(key='visitors', message='Visitors', is_active=True, audience=Banner.Audience.ANONYMOUS)
        response = self.client.get(reverse('home'))
        self.assertNotContains(response, 'data-banner-key="members"')
        self.assertContains(response, 'data-banner-key="visitors"')
        self.client.force_login(UserProfileFactory().user)
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'data-banner-key="members"')
        self.assertNotContains(response, 'data-banner-key="visitors"')

    def test_home_and_site_wide_placements(self):
        Banner.objects.create(key='everywhere', message='Everywhere', is_active=True, placement=Banner.Placement.SITE)
        response = self.client.get(reverse('about'))
        self.assertNotContains(response, 'data-banner-key="test-banner"')
        self.assertContains(response, 'data-banner-key="everywhere"')

    def test_scheduling_includes_start_and_excludes_end(self):
        now = timezone.now()
        self.banner.starts_at = now
        self.banner.ends_at = now + timedelta(hours=1)
        self.banner.save()
        visible = lambda at: Banner.objects.visible(authenticated=False, home=True, at=at).filter(pk=self.banner.pk).exists()
        self.assertFalse(visible(now - timedelta(seconds=1)))
        self.assertTrue(visible(now))
        self.assertFalse(visible(self.banner.ends_at))

    def test_priority_orders_candidates(self):
        high = Banner.objects.create(key='urgent', message='Urgent', is_active=True, priority=100)
        self.assertEqual(list(Banner.objects.visible(authenticated=False, home=True)), [high, self.banner])

    def test_content_is_translated_and_internal_link_follows_language(self):
        self.banner.message_en = 'English message'
        self.banner.message_it = 'Messaggio italiano'
        self.banner.action_label = 'More'
        self.banner.action_url = '/contacts'
        self.banner.save()
        with translation.override('en'):
            response = self.client.get(reverse('home'))
            self.assertContains(response, 'English message')
            self.assertContains(response, 'href="/en/contacts"')
        with translation.override('it'):
            self.assertContains(self.client.get(reverse('home')), 'Messaggio italiano')

    def test_message_is_escaped_and_unsafe_links_are_not_rendered(self):
        self.banner.message = '<script>alert(1)</script>'
        self.banner.action_url = 'javascript:alert(2)'
        self.banner.action_label = 'Click'
        self.banner.save()
        response = self.client.get(reverse('home'))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, 'javascript:alert(2)')
        with self.assertRaises(ValidationError):
            self.banner.full_clean()

    def test_relative_external_and_unsafe_links(self):
        for url in ('/contacts', 'https://example.com/news'):
            self.banner.action_url = url
            self.banner.action_label = 'More'
            self.banner.full_clean()
        for url in ('//example.com', '/\\example.com', 'data:text/html,test'):
            self.banner.action_url = url
            with self.subTest(url=url), self.assertRaises(ValidationError):
                self.banner.full_clean()

    def test_invalid_schedule_and_closing_settings_are_rejected(self):
        self.banner.starts_at = timezone.now()
        self.banner.ends_at = self.banner.starts_at
        self.banner.dismissal = Banner.Dismissal.DAYS
        self.banner.dismissal_scope = Banner.Scope.ACCOUNT
        with self.assertRaises(ValidationError) as caught:
            self.banner.full_clean()
        self.assertTrue({'ends_at', 'dismissal_days', 'dismissal_scope'} <= caught.exception.message_dict.keys())

    def test_account_scope_uses_the_current_user_and_browser_storage(self):
        self.banner.audience = Banner.Audience.AUTHENTICATED
        self.banner.dismissal_scope = Banner.Scope.ACCOUNT
        self.banner.full_clean()
        self.banner.save()
        profile = UserProfileFactory()
        self.client.force_login(profile.user)
        self.assertContains(self.client.get(reverse('home')), f'data-banner-scope="user:{profile.user_id}"')

    def test_cover_is_optional_and_uses_translated_alternative_text(self):
        self.assertNotContains(self.client.get(reverse('home')), 'src="/media/banners/')
        self.banner.cover = 'banners/cover.jpg'
        self.banner.cover_alt_it = 'Una serata di giochi'
        self.banner.save()
        with translation.override('it'):
            response = self.client.get(reverse('home'))
        self.assertContains(response, 'alt="Una serata di giochi"')
        self.assertContains(response, '/media/banners/cover.jpg')

    def test_banner_admin_requires_model_permissions(self):
        url = reverse('admin:webapp_banner_changelist')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(UserProfileFactory(user__is_staff=True).user)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(UserProfileFactory(user__is_staff=True, user__is_superuser=True).user)
        self.assertContains(self.client.get(reverse('admin:index')), url)
        response = self.client.get(reverse('admin:webapp_banner_change', args=[self.banner.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="file"')
        self.assertContains(response, 'name="message_it"')
        self.assertContains(response, 'name="message_en"')


class BannerCoverTest(TestCase):
    def setUp(self):
        self.enterContext(override_settings(MEDIA_ROOT=self.enterContext(TemporaryDirectory()), STORAGES={
            **settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        }))

    def test_uploaded_cover_is_resized_before_storage(self):
        output = BytesIO()
        Image.effect_noise((2400, 1600), 100).convert('RGB').save(output, 'JPEG', quality=95)
        upload = SimpleUploadedFile('cover.jpg', output.getvalue(), 'image/jpeg')
        banner = Banner(key='with-cover', message='A cover', cover=upload)
        banner.full_clean()
        banner.save()
        with banner.cover.open('rb') as content, Image.open(content) as image:
            self.assertLessEqual(max(image.size), COVER_MAX_SIDE)

    def test_oversized_or_invalid_covers_are_rejected(self):
        for upload in (SimpleUploadedFile('bad.png', b'not an image'),
                       SimpleUploadedFile('huge.png', b'x' * (BANNER_COVER_MAX_BYTES + 1))):
            with self.subTest(name=upload.name), self.assertRaises(ValidationError):
                validate_banner_cover(upload)

    def test_editing_text_does_not_reopen_or_reprocess_an_existing_cover(self):
        banner = Banner.objects.create(key='old-cover', message='Old', cover='banners/old.jpg')
        with mock.patch('webapp.signals.shrink_content_file') as shrink:
            banner.message = 'New'
            banner.full_clean()
            banner.save()
        shrink.assert_not_called()
