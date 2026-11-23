import json
import shutil
import subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from unittest import skipUnless

from django import forms
from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils import translation

from webapp.models import Table
from webapp.tests.test_cover_uploads import cover_upload


class CoverForm(forms.Form):
    custom_cover = forms.ImageField(required=False)
    cover = forms.ImageField(required=False, widget=forms.FileInput)


class ComponentParser(HTMLParser):
    """Keep the rendered attributes, text and scripts for behavioral checks."""
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = {'tag': 'document', 'attrs': {}, 'text': '', 'children': []}
        self.stack = [self.root]
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = {'tag': tag, 'attrs': dict(attrs), 'text': '', 'children': []}
        self.stack[-1]['children'].append(element)
        self.elements.append(element)
        if tag not in ('input', 'img', 'path', 'br', 'hr', 'meta', 'link'):
            self.stack.append(element)

    def handle_endtag(self, tag):
        if self.stack[-1]['tag'] == tag:
            self.stack.pop()

    def handle_data(self, text):
        self.stack[-1]['text'] += text


@override_settings(MEDIA_URL='/media/', STORAGES={
    **settings.STORAGES,
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
})
class CoverFieldTest(SimpleTestCase):
    def setUp(self):
        self.enterContext(translation.override('en'))
        self.saved_image = Table(custom_cover='covers/existing.png').custom_cover

    def render_component(self, prefix, variant='table', saved=True, **config):
        name = 'cover' if variant == 'event' else 'custom_cover'
        initial = {name: self.saved_image} if saved else {}
        form = CoverForm(prefix=prefix, initial=initial)
        return render_to_string('partials/_cover_field.html', {
            'field': form[name], 'saved_image': initial.get(name), 'variant': variant, **config,
        })

    def test_component_comments_are_not_visible(self):
        for variant in ('table', 'event'):
            with self.subTest(variant=variant):
                html = self.render_component('first', variant)
                self.assertNotIn('{#', html)
                self.assertNotIn('Componente condiviso', html)

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

    @skipUnless(shutil.which('node'), 'Node.js is required to execute the inline component script.')
    def test_upload_and_removal_only_change_their_own_instance(self):
        components = [ComponentParser(self.render_component(prefix)).root for prefix in ('first', 'second')]
        result = self.run_component_scripts(components, [
            {'type': 'select', 'component': 1, 'filename': 'second.png'},
        ])
        first, second = result['components']
        self.assertEqual(first['src'], self.saved_image.url)
        self.assertNotEqual(second['src'], self.saved_image.url)
        self.assertEqual(second['filename'], 'second.png')
        result = self.run_component_scripts(components, [
            {'type': 'select', 'component': 1, 'filename': 'second.png'},
            {'type': 'clear', 'component': 1, 'checked': True},
            {'type': 'clear', 'component': 1, 'checked': False},
            {'type': 'select', 'component': 0, 'filename': 'first.png'},
        ])
        first, second = result['components']
        self.assertEqual(first['filename'], 'first.png')
        self.assertEqual(second['src'], self.saved_image.url)
        self.assertFalse(second['hidden'])
        self.assertFalse(second['checked'])
        self.assertEqual(result['revoked'], ['blob:1'])

    @skipUnless(shutil.which('node'), 'Node.js is required to execute the inline component script.')
    def test_event_filename_changes_are_independent(self):
        components = [ComponentParser(self.render_component(prefix, 'event')).root for prefix in ('first', 'second')]
        result = self.run_component_scripts(components, [{'type': 'select', 'component': 1, 'filename': 'second.png'}])
        self.assertEqual(result['components'][0]['filename'], 'Choose an image…')
        self.assertEqual(result['components'][1]['filename'], 'second.png')

    def run_component_scripts(self, components, actions):
        result = subprocess.run(
            [shutil.which('node'), str(Path(__file__).with_name('cover_field_runtime.js'))],
            input=json.dumps({'components': components, 'actions': actions}), text=True,
            capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)
