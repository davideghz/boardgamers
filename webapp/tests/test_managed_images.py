from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import transaction
from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from webapp.factories import GameFactory, LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Game, Location
from webapp.services.image_files import same_storage
from webapp.services.images import COVER_MAX_SIDE, resized_image_name, shrink_content_file, shrink_image_bytes


def upload(name='cover.png', *, size=(40, 30), mode='RGBA', color=(20, 80, 120, 128)):
    output = BytesIO()
    Image.new(mode, size, color).save(output, 'PNG')
    return SimpleUploadedFile(name, output.getvalue(), 'image/png')


class TransparentImageTest(SimpleTestCase):
    def test_rgba_and_grayscale_alpha_survive_resizing(self):
        for mode, color in [('RGBA', (20, 80, 120, 128)), ('LA', (100, 128))]:
            with self.subTest(mode=mode):
                name, content = shrink_content_file(upload('logo.webp', size=(1600, 1200), mode=mode, color=color).read(),
                                                    'folder/logo.webp', 100)
                self.assertEqual(name, 'logo.png')
                with Image.open(content) as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, (100, 75))
                    self.assertEqual(image.getpixel((50, 50))[3], 128)

    def test_palette_and_rgb_transparency_are_kept(self):
        for mode in ('P', 'RGB'):
            with self.subTest(mode=mode):
                image = Image.new(mode, (1500, 1500), 0)
                if mode == 'P':
                    image.putpalette([20, 80, 120] + [0] * 765)
                output = BytesIO()
                image.save(output, 'PNG', transparency=0 if mode == 'P' else (0, 0, 0))
                resized = shrink_image_bytes(output.getvalue(), 100)
                self.assertEqual(resized_image_name('logo.gif', resized), 'logo.png')
                with Image.open(BytesIO(resized)) as result:
                    self.assertEqual(result.getpixel((50, 50))[3], 0)

    def test_opaque_rgba_can_still_be_saved_as_jpeg(self):
        image = upload(size=(1600, 1200), color=(20, 80, 120, 255))
        name, content = shrink_content_file(image.read(), image.name, 100)
        self.assertEqual(name, 'cover.jpg')
        with Image.open(content) as result:
            self.assertEqual(result.mode, 'RGB')
            self.assertEqual(result.format, 'JPEG')

    def test_unchanged_small_original_keeps_its_name_and_alpha(self):
        image = upload()
        data = image.read()
        name, content = shrink_content_file(data, image.name, COVER_MAX_SIDE)
        self.assertEqual(name, image.name)
        self.assertEqual(content.read(), data)

    def test_oversized_images_are_resized_even_without_the_target_saving_ratio(self):
        image = upload(size=(1600, 1200))
        with mock.patch('webapp.services.images.MIN_SAVING_RATIO', 0):
            result = shrink_image_bytes(image.read(), 100)
        with Image.open(BytesIO(result)) as resized:
            self.assertEqual(resized.size, (100, 75))


class ManagedImagesTest(TestCase):
    def setUp(self):
        self.media_root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root, STORAGES={
            **settings.STORAGES, 'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        }))
        self.game = GameFactory(image=upload())
        self.storage = self.game.image.storage

    def test_replacement_keeps_original_until_commit_then_removes_it(self):
        old_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True):
            self.game.image = upload('replacement.png')
            self.game.save(update_fields=['image'])
            self.assertTrue(self.storage.exists(old_name))
        self.assertFalse(self.storage.exists(old_name))
        self.assertTrue(self.storage.exists(self.game.image.name))

    def test_clear_keeps_original_on_rollback(self):
        old_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                self.game.image.delete()
                self.assertTrue(self.storage.exists(old_name))
                transaction.set_rollback(True)
        self.assertEqual(callbacks, [])
        self.game.refresh_from_db()
        self.assertEqual(self.game.image.name, old_name)
        self.assertTrue(self.storage.exists(old_name))

    def test_replace_keeps_original_on_rollback(self):
        old_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                self.game.image = upload('new.png')
                self.game.save(update_fields=['image'])
                transaction.set_rollback(True)
        self.assertEqual(callbacks, [])
        self.game.refresh_from_db()
        self.assertEqual(self.game.image.name, old_name)
        self.assertTrue(self.storage.exists(old_name))

    def test_direct_field_delete_waits_for_the_model_save(self):
        old_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.game.image.delete(save=False)
        self.assertEqual(callbacks, [])
        self.assertTrue(self.storage.exists(old_name))
        with self.captureOnCommitCallbacks(execute=True):
            self.game.save(update_fields=['image'])
        self.assertFalse(self.storage.exists(old_name))

    def test_delete_and_queryset_delete_remove_files_after_commit(self):
        for use_queryset in (False, True):
            with self.subTest(queryset=use_queryset):
                game = GameFactory(image=upload())
                name = game.image.name
                with self.captureOnCommitCallbacks(execute=True):
                    if use_queryset:
                        Game.objects.filter(pk=game.pk).delete()
                    else:
                        game.delete()
                    self.assertTrue(self.storage.exists(name))
                self.assertFalse(self.storage.exists(name))

    def test_delete_on_rollback_keeps_the_image(self):
        old_name, pk = self.game.image.name, self.game.pk
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                self.game.delete()
                transaction.set_rollback(True)
        self.assertEqual(callbacks, [])
        self.assertTrue(Game.objects.filter(pk=pk).exists())
        self.assertTrue(self.storage.exists(old_name))

    def test_references_in_another_model_protect_the_file(self):
        name = self.game.image.name
        location = LocationFactory(cover=name)
        with self.captureOnCommitCallbacks(execute=True):
            self.game.delete()
        self.assertTrue(self.storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            location.cover = None
            location.save(update_fields=['cover'])
        self.assertFalse(self.storage.exists(name))

    def test_shared_table_cover_is_removed_only_after_the_last_copy(self):
        location = LocationFactory()
        owner = UserProfileFactory()
        first = TableFactory(location=location, author=owner, custom_cover=upload())
        second = TableFactory(location=location, author=owner, custom_cover=first.custom_cover.name)
        name = first.custom_cover.name
        with self.captureOnCommitCallbacks(execute=True):
            first.custom_cover.delete()
        self.assertTrue(self.storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            second.delete()
        self.assertFalse(self.storage.exists(name))

    def test_returning_to_original_before_commit_preserves_it(self):
        old_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True):
            self.game.image = upload('replacement.png')
            self.game.save(update_fields=['image'])
            unused = self.game.image.name
            self.game.image = old_name
            self.game.save(update_fields=['image'])
        self.assertTrue(self.storage.exists(old_name))
        self.assertFalse(self.storage.exists(unused))

    def test_partial_save_does_not_save_or_remove_a_pending_upload(self):
        old_name = self.game.image.name
        self.game.image = upload('pending.png')
        self.game.description = 'Changed description'
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            self.game.save(update_fields=['description'])
        self.assertEqual(callbacks, [])
        self.assertEqual(Game.objects.get(pk=self.game.pk).image.name, old_name)
        self.assertEqual(len(list(Path(self.media_root).rglob('*.png'))), 1)

    def test_deferred_image_is_not_read_during_an_unrelated_save(self):
        game = Game.objects.defer('image').get(pk=self.game.pk)
        game.description = 'Changed description'
        with mock.patch.object(self.storage, 'open') as storage_open:
            game.save()
        storage_open.assert_not_called()
        self.assertIn('image', game.get_deferred_fields())

    def test_stale_replacement_uses_the_actual_previous_file(self):
        stale = Game.objects.get(pk=self.game.pk)
        with self.captureOnCommitCallbacks(execute=True):
            self.game.image = upload('second.png')
            self.game.save(update_fields=['image'])
        second_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True):
            stale.image = upload('third.png')
            stale.save(update_fields=['image'])
        self.assertFalse(self.storage.exists(second_name))
        self.assertTrue(self.storage.exists(stale.image.name))

    def test_stale_deletion_uses_the_actual_current_file(self):
        stale = Game.objects.get(pk=self.game.pk)
        with self.captureOnCommitCallbacks(execute=True):
            self.game.image = upload('second.png')
            self.game.save(update_fields=['image'])
        second_name = self.game.image.name
        with self.captureOnCommitCallbacks(execute=True):
            stale.delete()
        self.assertFalse(self.storage.exists(second_name))

    def test_replacement_failure_keeps_original_reference_and_file(self):
        old_name = self.game.image.name
        self.game.image = upload('cannot-save.png')
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with mock.patch.object(self.storage, '_save', side_effect=OSError('Storage unavailable')):
                with self.assertRaises(OSError):
                    self.game.save(update_fields=['image'])
        self.assertEqual(callbacks, [])
        self.assertEqual(Game.objects.get(pk=self.game.pk).image.name, old_name)
        self.assertTrue(self.storage.exists(old_name))

    def test_storage_delete_failure_does_not_undo_the_successful_save(self):
        old_name = self.game.image.name
        with mock.patch.object(self.storage, 'delete', side_effect=OSError('Storage unavailable')):
            with self.assertLogs(level='ERROR'), self.captureOnCommitCallbacks(execute=True):
                self.game.image = upload('new.png')
                self.game.save(update_fields=['image'])
        self.game.refresh_from_db()
        self.assertNotEqual(self.game.image.name, old_name)
        self.assertTrue(self.storage.exists(self.game.image.name))
        self.assertTrue(self.storage.exists(old_name))

    def test_same_filename_in_another_storage_does_not_count_as_a_reference(self):
        name = self.game.image.name
        other_root = self.enterContext(TemporaryDirectory())
        other_storage = FileSystemStorage(location=other_root)
        other_storage.save(name, ContentFile(b'other storage'))
        with mock.patch.object(Location._meta.get_field('cover'), 'storage', other_storage):
            LocationFactory(cover=name)
            with self.captureOnCommitCallbacks(execute=True):
                self.game.image.delete()
        self.assertFalse(self.storage.exists(name))
        self.assertTrue(other_storage.exists(name))

    def test_direct_field_save_uses_the_shared_resize_pipeline(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.game.image.save('transparent.png', upload(size=(1600, 1200)))
        with self.game.image.open('rb') as content, Image.open(content) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(image.size, (1200, 900))
            self.assertEqual(image.getpixel((500, 500))[3], 128)

    def test_resize_command_preserves_alpha_and_cleans_unreferenced_originals(self):
        name = self.storage.save('games/large-original.png', upload(size=(1600, 1200)))
        self.game.image = name
        self.game.save(update_fields=['image'])
        with self.captureOnCommitCallbacks(execute=True):
            call_command('resize_images', model='game', stdout=StringIO())
            self.assertTrue(self.storage.exists(name))
        self.game.refresh_from_db()
        self.assertNotEqual(self.game.image.name, name)
        self.assertFalse(self.storage.exists(name))
        with self.game.image.open('rb') as content, Image.open(content) as image:
            self.assertEqual(image.format, 'PNG')
            self.assertEqual(max(image.size), COVER_MAX_SIDE)

    def test_game_merge_removes_the_replaced_image_and_preserves_the_adopted_image(self):
        from webapp.services.games import merge_games
        duplicate = GameFactory(image=upload('adopted.png'))
        old_name, adopted_name = self.game.image.name, duplicate.image.name
        with self.captureOnCommitCallbacks(execute=True):
            merge_games(self.game, duplicate, {'image': 'duplicate'})
            self.assertTrue(self.storage.exists(old_name))
            self.assertTrue(self.storage.exists(adopted_name))
        self.game.refresh_from_db()
        self.assertEqual(self.game.image.name, adopted_name)
        self.assertFalse(self.storage.exists(old_name))
        self.assertTrue(self.storage.exists(adopted_name))


class StorageNamespaceTest(SimpleTestCase):
    def test_equivalent_filesystem_storages_share_references(self):
        with TemporaryDirectory() as root:
            self.assertTrue(same_storage(FileSystemStorage(location=root), FileSystemStorage(location=root)))

    def test_s3_buckets_and_prefixes_are_separate(self):
        from types import SimpleNamespace
        first = SimpleNamespace(bucket_name='one', location='media', endpoint_url=None)
        equal = SimpleNamespace(bucket_name='one', location='media', endpoint_url=None)
        other_prefix = SimpleNamespace(bucket_name='one', location='private', endpoint_url=None)
        other_bucket = SimpleNamespace(bucket_name='two', location='media', endpoint_url=None)
        self.assertTrue(same_storage(first, equal))
        self.assertFalse(same_storage(first, other_prefix))
        self.assertFalse(same_storage(first, other_bucket))
