import re
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from PIL import Image

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.forms import LocationForm, LocationManageDataForm
from webapp.models import Location


class LocationCreateViewTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)

    def _post(self, **overrides):
        data = {
            'name': 'Circolo Ludico',
            'description': 'Serate di gioco',
            'address': 'Via Roma 1, Milano',
            'city': 'Milano',
            'latitude': '45.4642',
            'longitude': '9.1900',
            'default_table_time': '20:30',
            **overrides,
        }
        return self.client.post(reverse('location-create'), data)

    def test_cover_preview_starts_without_an_image(self):
        with translation.override('it'):
            response = self.client.get(reverse('location-create'))

        self.assertEqual(response.status_code, 200)
        preview = re.search(
            r'<figure\b[^>]*\sid="location-cover-preview"[^>]*>(.*?)</figure>',
            response.text,
            re.DOTALL,
        )
        self.assertIsNotNone(preview)
        self.assertRegex(preview[1], r'<img\b(?![^>]*\ssrc=)[^>]*>')
        self.assertContains(response, "Se è un logo, lascia un po' di spazio attorno.")
        self.assertContains(response, 'id="location-cover-dialog"')
        self.assertContains(response, 'aspect-ratio="1"')
        self.assertContains(response, 'Applica ritaglio')
        self.assertContains(response, "Inquadra tutta l'immagine")

    def test_redirects_to_the_new_location_page(self):
        response = self._post()

        location = Location.objects.get(name='Circolo Ludico')
        self.assertEqual(location.creator, self.profile)
        self.assertRedirects(response, reverse('location-detail', kwargs={'slug': location.slug}))

    @override_settings(MEDIA_URL='/media/', STORAGES={
        **settings.STORAGES,
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    })
    def test_saves_uploaded_cover_to_local_media(self):
        image = BytesIO()
        Image.new('RGB', (10, 10)).save(image, 'PNG')
        cover = SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png')

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self._post(cover=cover)
            location = Location.objects.get(name='Circolo Ludico')

            self.assertRedirects(response, reverse('location-detail', kwargs={'slug': location.slug}))
            self.assertTrue(location.is_manager(self.profile))
            self.assertEqual(location.cover.url, '/media/location-covers/cover.png')
            self.assertEqual((Path(media_root) / location.cover.name).read_bytes(), image.getvalue())

    def test_website_without_scheme_gets_https(self):
        self._post(website='www.circololudico.it')

        location = Location.objects.get(name='Circolo Ludico')
        self.assertEqual(location.website, 'https://www.circololudico.it')

    def test_website_stays_optional(self):
        self._post(website='')

        self.assertFalse(Location.objects.get(name='Circolo Ludico').website)


class LocationFormTranslationTest(TestCase):
    def test_labels_and_address_placeholder_follow_the_language(self):
        with translation.override('it'):
            form = LocationForm()
            labels = [str(form.fields[name].label) for name in ['name', 'description', 'address', 'website']]
            placeholder = str(form.fields['address'].widget.attrs['placeholder'])

        self.assertEqual(labels, ['Nome', 'Descrizione', 'Indirizzo', 'Sito web'])
        self.assertEqual(placeholder, 'Inserisci un indirizzo')


class LocationFormWebsiteTest(TestCase):
    def _clean_website(self, value):
        form = LocationForm(data={'website': value})
        form.is_valid()
        return form.cleaned_data.get('website'), form.errors.get('website')

    def test_accepted_values(self):
        cases = {
            'circololudico.it': 'https://circololudico.it',
            '  www.circololudico.it/soci  ': 'https://www.circololudico.it/soci',
            'https://circololudico.it': 'https://circololudico.it',
            'http://circololudico.it': 'http://circololudico.it',
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                website, errors = self._clean_website(value)
                self.assertIsNone(errors)
                self.assertEqual(website, expected)

    def test_rejected_values(self):
        for value in ['non un sito', 'javascript:alert(1)']:
            with self.subTest(value=value):
                _, errors = self._clean_website(value)
                self.assertTrue(errors)

    def test_browser_url_validation_is_off_on_both_forms(self):
        location = LocationFactory(creator=UserProfileFactory())
        for form in [LocationForm(), LocationManageDataForm(instance=location)]:
            with self.subTest(form=type(form).__name__):
                self.assertEqual(form['website'].field.widget.input_type, 'text')
