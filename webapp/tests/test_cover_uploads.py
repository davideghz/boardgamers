"""Cover limits and the rendered form after an upload is rejected or lost."""
import datetime
import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile, TemporaryUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from webapp.factories import LocationFactory, TableFactory, UserProfileFactory
from webapp.forms import (
    EventForm, EventManageDataForm, EventTableForm, LocationForm, LocationManageDataForm,
    TableDuplicateForm, TableForm, validate_custom_cover_size,
)
from webapp.models import Event, EventDate, Location, Table
from webapp.services.images import COVER_UPLOAD_MAX_BYTES
from webapp.services.tables import duplicate_draft


def cover_upload(size=None):
    output = BytesIO()
    Image.new('RGB', (32, 24), 'navy').save(output, 'PNG')
    content = output.getvalue()
    if size is not None:
        # Padding keeps a valid, cheap-to-decode image with an exact upload size.
        content = content.ljust(size, b'\0')
    return SimpleUploadedFile('selected.png', content, 'image/png')


class CoverUploadSizeTest(SimpleTestCase):
    def test_new_upload_limit_in_memory_and_on_disk(self):
        for size in (COVER_UPLOAD_MAX_BYTES, COVER_UPLOAD_MAX_BYTES + 1):
            memory_upload = cover_upload(size)
            with TemporaryUploadedFile('selected.png', 'image/png', size, None) as disk_upload:
                disk_upload.write(memory_upload.read())
                disk_upload.seek(0)
                for upload in (memory_upload, disk_upload):
                    with self.subTest(size=size, upload=type(upload).__name__):
                        if size == COVER_UPLOAD_MAX_BYTES:
                            self.assertIs(validate_custom_cover_size(upload), upload)
                        else:
                            with self.assertRaises(ValidationError):
                                validate_custom_cover_size(upload)

    def test_empty_and_clear_values_are_accepted(self):
        for value in (None, False):
            self.assertIs(validate_custom_cover_size(value), value)


class CoverUploadFormsTest(TestCase):
    def setUp(self):
        self.media_root = self.enterContext(TemporaryDirectory())
        self.enterContext(override_settings(MEDIA_ROOT=self.media_root, MEDIA_URL='/media/', STORAGES={
            **settings.STORAGES,
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        }))
        self.enterContext(translation.override('en'))
        self.owner = UserProfileFactory(preferred_language='en')
        self.location = LocationFactory(creator=self.owner)
        self.day = timezone.localdate() + datetime.timedelta(days=7)
        self.event = Event.objects.create(name='Convention', creator=self.owner, status=Event.PUBLISHED)
        EventDate.objects.create(event=self.event, date=self.day)
        self.table = TableFactory(location=self.location, author=self.owner, date=self.day)
        self.event_table = TableFactory(location=None, event=self.event, author=self.owner, date=self.day)
        self.client.defaults['HTTP_ACCEPT_LANGUAGE'] = 'en'
        self.client.force_login(self.owner.user)
        self.table_data = {
            'title': 'An evening game', 'description': 'Play together', 'date': self.day.isoformat(),
            'time': '21:00', 'min_players': 2, 'max_players': 5, 'location': self.location.pk,
            'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0,
        }
        self.event_table_data = {**self.table_data, 'event': self.event.pk}
        self.duplicate_data = {**self.table_data, 'dates': [self.day.isoformat()]}
        self.location_data = {
            'name': 'Game club', 'description': 'Play together', 'address': 'Via Roma 1', 'city': 'Milano',
            'latitude': '45', 'longitude': '9', 'leaderboard_edit_days': 2, 'default_table_time': '21:00',
        }
        self.event_data = {'name': 'Convention', 'description': 'Play together'}

    def form_cases(self):
        return [
            (TableForm, self.table_data, self.table, 'custom_cover', {'location': self.location}),
            (EventTableForm, self.event_table_data, self.event_table, 'custom_cover', {'event': self.event}),
            (TableDuplicateForm, self.duplicate_data, duplicate_draft(self.table), 'custom_cover', {}),
            (LocationForm, self.location_data, self.location, 'cover', {}),
            (LocationManageDataForm, self.location_data, self.location, 'cover', {}),
            (EventForm, self.event_data, self.event, 'cover', {}),
            (EventManageDataForm, self.event_data, self.event, 'cover', {}),
        ]

    def post_cases(self):
        return [
            ('location-table-create', {'location_slug': self.location.slug}, self.table_data, 'custom_cover', None),
            ('location-table-update', {'location_slug': self.location.slug, 'table_slug': self.table.slug},
             self.table_data, 'custom_cover', self.table),
            ('event-table-create', {'event_slug': self.event.slug}, self.event_table_data, 'custom_cover', None),
            ('event-table-update', {'event_slug': self.event.slug, 'table_slug': self.event_table.slug},
             self.event_table_data, 'custom_cover', self.event_table),
            ('table-duplicate', {'slug': self.table.slug}, self.duplicate_data, 'custom_cover', self.table),
            ('location-create', {}, self.location_data, 'cover', None),
            ('location-manage-data', {'slug': self.location.slug}, self.location_data, 'cover', self.location),
            ('event-create', {}, self.event_data, 'cover', None),
            ('event-manage-data', {'slug': self.event.slug}, self.event_data, 'cover', self.event),
        ]

    def test_all_forms_accept_new_images_up_to_five_mb(self):
        for size in (300 * 1024, COVER_UPLOAD_MAX_BYTES):
            for form_class, data, instance, field_name, kwargs in self.form_cases():
                with self.subTest(form=form_class.__name__, size=size):
                    if instance.pk:
                        instance.refresh_from_db()
                    form = form_class(data=data, files={field_name: cover_upload(size)}, instance=instance, **kwargs)
                    self.assertTrue(form.is_valid(), form.errors)

    def test_all_forms_reject_new_images_above_five_mb_and_invalid_contents(self):
        for form_class, data, instance, field_name, kwargs in self.form_cases():
            for upload in (cover_upload(COVER_UPLOAD_MAX_BYTES + 1), SimpleUploadedFile('fake.png', b'not an image')):
                with self.subTest(form=form_class.__name__, size=upload.size):
                    form = form_class(data=data, files={field_name: upload}, instance=instance, **kwargs)
                    self.assertFalse(form.is_valid())
                    self.assertIn(field_name, form.errors)

    def test_existing_covers_are_preserved_without_reading_storage(self):
        for form_class, data, instance, field_name, kwargs in self.form_cases():
            with self.subTest(form=form_class.__name__):
                setattr(instance, field_name, 'covers/existing.png')
                stored_file = getattr(instance, field_name)
                with mock.patch.object(stored_file.storage, 'size', side_effect=AssertionError('Existing file size read')):
                    form = form_class(data=data, instance=instance, **kwargs)
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertEqual(form.cleaned_data[field_name].name, 'covers/existing.png')

    def test_oversized_cover_errors_are_visible_on_new_tables_and_duplicates(self):
        for route, kwargs, data, field_name, instance in self.post_cases()[:5]:
            with self.subTest(route=route):
                response = self.client.post(reverse(route, kwargs=kwargs), {
                    **data, field_name: cover_upload(COVER_UPLOAD_MAX_BYTES + 1),
                })
                self.assertEqual(response.status_code, 200)
                self.assertIn(field_name, response.context['form'].errors)
                body_tag = re.search(r'<div\b[^>]*id="cover-body"[^>]*>', response.text)[0]
                self.assertNotIn('display:none', body_tag)
                self.assertContains(response, 'aria-expanded="true"')
                self.assertContains(response, 'rotate-90')
                self.assertContains(response, response.context['form'].errors[field_name][0])
                self.assertContains(response, filesizeformat(COVER_UPLOAD_MAX_BYTES))

    def test_create_views_save_new_covers_above_the_old_limit(self):
        models = {
            'location-table-create': Table,
            'event-table-create': Table,
            'location-create': Location,
            'event-create': Event,
        }
        for route, kwargs, data, field_name, instance in self.post_cases():
            if instance is not None:
                continue
            with self.subTest(route=route):
                model = models[route]
                previous_count = model.objects.count()
                response = self.client.post(reverse(route, kwargs=kwargs), {
                    **data, field_name: cover_upload(300 * 1024),
                })
                self.assertEqual(response.status_code, 302)
                self.assertEqual(model.objects.count(), previous_count + 1)
                saved_file = getattr(model.objects.latest('pk'), field_name)
                self.assertTrue(saved_file.storage.exists(saved_file.name))

    def test_failed_posts_only_preview_the_saved_cover(self):
        for route, kwargs, data, field_name, instance in self.post_cases():
            for saved_name in ('', 'covers/existing.png'):
                with self.subTest(route=route, existing=bool(saved_name)):
                    if instance is not None:
                        type(instance).objects.filter(pk=instance.pk).update(**{field_name: saved_name})
                    invalid_field = 'max_players' if field_name == 'custom_cover' else 'name'
                    invalid_value = 1 if field_name == 'custom_cover' else ''
                    response = self.client.post(reverse(route, kwargs=kwargs), {
                        **data, invalid_field: invalid_value, field_name: cover_upload(),
                    })
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(invalid_field, response.context['form'].errors)
                    self.assertNotIn(field_name, response.context['form'].errors)
                    self.assertContains(response, 'Select the image again.')
                    self.assertNotRegex(response.text, r'src="[^"]*selected\.png"')
                    file_input = re.search(r'<input\b[^>]*type="file"[^>]*>', response.text)[0]
                    self.assertNotIn('value=', file_input)
                    if instance is not None and saved_name:
                        self.assertContains(response, 'src="/media/covers/existing.png"')
                    if field_name == 'custom_cover':
                        body_tag = re.search(r'<div\b[^>]*id="cover-body"[^>]*>', response.text)[0]
                        self.assertNotIn('display:none', body_tag)
        self.assertEqual(list(Path(self.media_root).rglob('*')), [])

    def test_existing_large_cover_can_be_kept_on_a_successful_table_edit(self):
        self.table.custom_cover = 'covers/old-large.png'
        self.table.save(update_fields=['custom_cover'])
        with mock.patch.object(self.table.custom_cover.storage, 'size', return_value=8 * 1024 * 1024) as size:
            response = self.client.post(reverse('location-table-update', kwargs={
                'location_slug': self.location.slug, 'table_slug': self.table.slug,
            }), {**self.table_data, 'title': 'Updated title'})
        self.assertEqual(response.status_code, 302)
        size.assert_not_called()
        self.table.refresh_from_db()
        self.assertEqual(self.table.title, 'Updated title')
        self.assertEqual(self.table.custom_cover.name, 'covers/old-large.png')

    def test_pending_removal_is_preserved_after_another_field_error(self):
        for route, kwargs, data, field_name, instance in self.post_cases()[1:5]:
            if instance is None:
                continue
            with self.subTest(route=route):
                type(instance).objects.filter(pk=instance.pk).update(custom_cover='covers/existing.png')
                response = self.client.post(reverse(route, kwargs=kwargs), {
                    **data, 'max_players': 1, 'custom_cover-clear': 'on',
                })
                checkbox = re.search(r'<input\b[^>]*name="custom_cover-clear"[^>]*>', response.text)[0]
                preview = re.search(r'<img\b[^>]*id="cover-preview"[^>]*>', response.text)[0]
                self.assertIn('checked', checkbox)
                self.assertIn('hidden', preview)

    def test_clearing_one_copy_preserves_the_shared_file(self):
        cover = cover_upload()
        self.table.custom_cover.save(cover.name, cover)
        shared_name = self.table.custom_cover.name
        copy = TableFactory(location=self.location, author=self.owner, date=self.day, custom_cover=shared_name)
        response = self.client.post(reverse('location-table-update', kwargs={
            'location_slug': self.location.slug, 'table_slug': self.table.slug,
        }), {**self.table_data, 'custom_cover-clear': 'on'})
        self.assertEqual(response.status_code, 302)
        self.table.refresh_from_db()
        copy.refresh_from_db()
        self.assertFalse(self.table.custom_cover)
        self.assertEqual(copy.custom_cover.name, shared_name)
        self.assertTrue(copy.custom_cover.storage.exists(shared_name))
