import re

from django.test import TestCase
from django.urls import reverse

from webapp.services.ui_personas import seed_ui_personas


class FormErrorsTest(TestCase):
    """F4: a form sent with errors opens with a summary linking each field, and every message
    sits by its field, tied to it by aria-describedby and aria-invalid."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def assert_readable_errors(self, persona, url, data=None):
        self.client.force_login(self.data.profile(persona).user)
        response = self.client.post(url, data or {})
        self.assertEqual(response.status_code, 200, url)
        html = response.content.decode()
        self.assertIn('data-error-summary', html)
        self.assertIn('id="error-summary" tabindex="-1" role="alert"', html)
        form = response.context['form']
        fields = [name for name in form.errors if name != '__all__' and not form[name].is_hidden]
        self.assertTrue(fields, url)
        for name in fields:
            auto_id = form[name].auto_id
            with self.subTest(url=url, field=name):
                self.assertIn(f'href="#{auto_id}"', html)
                self.assertIn(f'id="{auto_id}_error"', html)
                widget = re.search(rf'<(?:input|select|textarea)[^>]*\bid="{auto_id}"[^>]*>', html)
                if widget:  # composite widgets (pickers, covers) have no element with the id
                    self.assertIn('aria-invalid="true"', widget.group(0))
                    self.assertIn(f'{auto_id}_error', widget.group(0))

    def test_location_forms(self):
        circolo = self.data.circolo
        self.assert_readable_errors('newcomer', reverse('location-create'))
        self.assert_readable_errors('manager', reverse('location-manage-data', args=[circolo.slug]))
        self.assert_readable_errors('newcomer', reverse('location-request-membership', args=[circolo.slug]))

    def test_table_forms(self):
        self.assert_readable_errors('manager', reverse('location-table-create', args=[self.data.negozio.slug]))
        self.assert_readable_errors('manager', reverse('event-table-create', args=[self.data.event.slug]))

    def test_event_and_festival_forms(self):
        self.assert_readable_errors('manager', reverse('location-event-create', args=[self.data.negozio.slug]))
        self.assert_readable_errors('manager', reverse('event-manage-data', args=[self.data.event.slug]))
        self.assert_readable_errors('organizer', reverse('master-event-create'))
