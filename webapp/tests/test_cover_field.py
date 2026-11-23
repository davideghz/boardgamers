from collections import Counter
from html.parser import HTMLParser

from django import forms
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from webapp.forms import LocationForm
from webapp.models import Table
from webapp.tests.test_cover_uploads import cover_upload


class CoverForm(forms.Form):
    custom_cover = forms.ImageField(required=False)
    cover = forms.ImageField(required=False, widget=forms.FileInput(attrs={'data-crop-max-side': 1200}))


class ComponentParser(HTMLParser):
    """Collect the rendered tags and their attributes."""
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append({'tag': tag, 'attrs': dict(attrs)})


@override_settings(MEDIA_URL='/media/', STORAGES={
    **settings.STORAGES,
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
})
class CoverFieldTest(SimpleTestCase):
    def setUp(self):
        self.enterContext(translation.override('en'))
        self.saved_image = Table(custom_cover='covers/existing.png').custom_cover

    def render_component(self, prefix, variant='table', saved=True, **config):
        name = 'custom_cover' if variant == 'table' else 'cover'
        initial = {name: self.saved_image} if saved else {}
        form = CoverForm(prefix=prefix, initial=initial)
        return render_to_string('partials/_cover_field.html', {
            'field': form[name], 'saved_image': initial.get(name), 'variant': variant, **config,
        })

    def test_component_comments_are_not_visible(self):
        for variant in ('table', 'event', 'location'):
            with self.subTest(variant=variant):
                html = self.render_component('first', variant)
                self.assertNotIn('{#', html)
                self.assertNotIn('Shared cover input', html)

    def test_event_image_uses_the_given_alt_text(self):
        html = self.render_component('first', 'event', image_alt='Games "Con"')
        image = next(element['attrs'] for element in ComponentParser(html).elements if element['tag'] == 'img')
        self.assertEqual(image['alt'], 'Games "Con"')

    def test_prefixed_inputs_bind_uploads_and_removals(self):
        html = self.render_component('first')
        elements = ComponentParser(html).elements
        file_input = next(element['attrs'] for element in elements if element['attrs'].get('type') == 'file')
        clear_input = next(element['attrs'] for element in elements if element['attrs'].get('type') == 'checkbox')
        self.assertEqual(file_input['name'], 'first-custom_cover')
        self.assertEqual(clear_input['name'], 'first-custom_cover-clear')
        form = CoverForm(prefix='first', data={}, files={file_input['name']: cover_upload()})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['custom_cover'].name, 'selected.png')
        form = CoverForm(prefix='first', data={clear_input['name']: 'on'}, initial={'custom_cover': self.saved_image})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['custom_cover'], False)

    def test_two_instances_have_unique_ids_and_valid_labels(self):
        html = ''.join(self.render_component(prefix, variant) for prefix, variant in (
            ('first', 'table'), ('second', 'table'), ('event', 'event'),
        ))
        elements = ComponentParser(html).elements
        ids = [element['attrs']['id'] for element in elements if 'id' in element['attrs']]
        self.assertEqual(len(ids), len(set(ids)), Counter(ids))
        for element in elements:
            if element['tag'] == 'label':
                target = element['attrs'].get('for')
                if target:
                    self.assertIn(target, ids)

    def test_location_instances_have_unique_ids_and_accessible_dialogs(self):
        html = ''.join(self.render_component(prefix, 'location', crop_ratio=1) for prefix in ('first', 'second'))
        elements = ComponentParser(html).elements
        ids = [element['attrs']['id'] for element in elements if 'id' in element['attrs']]
        self.assertEqual(len(ids), len(set(ids)), Counter(ids))
        for element in elements:
            for attribute in ('aria-labelledby', 'aria-describedby'):
                for target in element['attrs'].get(attribute, '').split():
                    self.assertIn(target, ids)

    def test_decimal_crop_ratio_uses_a_dot_in_italian(self):
        with translation.override('it'):
            html = self.render_component('first', 'location', crop_ratio=16 / 9)
        selection = next(element['attrs'] for element in ComponentParser(html).elements
                         if element['tag'] == 'cropper-selection')
        self.assertAlmostEqual(float(selection['aspect-ratio']), 16 / 9)

    def test_location_help_uses_the_prefixed_field_id(self):
        form = LocationForm(prefix='first')
        html = render_to_string('partials/_cover_field.html', {'field': form['cover'], 'variant': 'location'})
        elements = ComponentParser(html).elements
        file_input = next(element['attrs'] for element in elements if element['attrs'].get('type') == 'file')
        self.assertEqual(file_input['aria-describedby'], 'id_first-cover-help')
        self.assertIn(file_input['aria-describedby'], [element['attrs'].get('id') for element in elements])
