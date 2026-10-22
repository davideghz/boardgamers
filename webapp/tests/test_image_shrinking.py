import datetime
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.services.images import AVATAR_MAX_SIDE, COVER_MAX_SIDE, shrink_image_bytes


def png_bytes(size, mode='RGBA', color=(200, 30, 30, 0)):
    out = BytesIO()
    Image.new(mode, size, color).save(out, 'PNG')
    return out.getvalue()


def noisy_png_bytes(size):
    """PNG incomprimibile, così è anche "pesante" in byte."""
    import os
    img = Image.frombytes('RGB', size, os.urandom(size[0] * size[1] * 3))
    out = BytesIO()
    img.save(out, 'PNG')
    return out.getvalue()


class ShrinkImageBytesTest(TestCase):
    def test_large_image_becomes_jpeg_within_max_side(self):
        result = shrink_image_bytes(noisy_png_bytes((2400, 1200)), COVER_MAX_SIDE)
        img = Image.open(BytesIO(result))
        self.assertEqual(img.format, 'JPEG')
        self.assertEqual(img.size, (COVER_MAX_SIDE, COVER_MAX_SIDE // 2))

    def test_transparency_is_flattened_on_white(self):
        result = shrink_image_bytes(png_bytes((2000, 2000)), 100)
        img = Image.open(BytesIO(result)).convert('RGB')
        r, g, b = img.getpixel((50, 50))
        self.assertGreater(min(r, g, b), 240)

    def test_small_light_image_is_left_alone(self):
        self.assertIsNone(shrink_image_bytes(png_bytes((300, 300), 'RGB', (1, 2, 3)), COVER_MAX_SIDE))

    def test_non_image_is_left_alone(self):
        self.assertIsNone(shrink_image_bytes(b'not an image', COVER_MAX_SIDE))


class ShrinkOnUploadTest(TestCase):
    def setUp(self):
        patcher = mock.patch('storages.backends.s3.S3Storage._save', side_effect=lambda name, content: name)
        self.save_mock = patcher.start()
        self.addCleanup(patcher.stop)
        self.user_profile = UserProfileFactory()

    def test_new_upload_is_shrunk_before_storage(self):
        self.user_profile.avatar = SimpleUploadedFile('me.png', noisy_png_bytes((1000, 800)), 'image/png')
        self.user_profile.save()

        name, content = self.save_mock.call_args.args
        self.assertTrue(name.endswith('me.jpg'))
        content.seek(0)
        img = Image.open(content)
        self.assertEqual(img.format, 'JPEG')
        self.assertEqual(max(img.size), AVATAR_MAX_SIDE)

    def test_saving_without_new_upload_does_not_touch_storage(self):
        self.user_profile.avatar = 'avatars/me.png'
        self.user_profile.save()
        self.user_profile.nickname = 'renamed'
        self.user_profile.save()
        self.save_mock.assert_not_called()


class LocationPastTablesLimitTest(TestCase):
    def test_only_latest_twelve_past_tables_are_rendered(self):
        UserProfileFactory()
        location = LocationFactory()
        today = timezone.localdate()
        for days in range(1, 16):
            TableFactory(location=location, date=today - datetime.timedelta(days=days))

        response = self.client.get(reverse('location-detail', args=[location.slug]))

        self.assertEqual(len(response.context['past_tables']), 12)
        self.assertEqual(response.context['past_tables_count'], 15)
        self.assertEqual(response.context['past_tables'][0].date, today - datetime.timedelta(days=1))
