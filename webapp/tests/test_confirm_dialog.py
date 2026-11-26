from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from webapp.factories import UserProfileFactory
from webapp.models import GuestProfile

TEMPLATES = Path(settings.BASE_DIR) / 'webapp' / 'templates'


class ConfirmDialogTest(TestCase):
    def setUp(self):
        self.profile = UserProfileFactory()
        self.client.force_login(self.profile.user)

    def test_no_template_uses_the_browser_confirm(self):
        offenders = [
            str(path.relative_to(TEMPLATES)) for path in TEMPLATES.rglob('*.html')
            if 'confirm(' in path.read_text().replace('confirmDialog(', '')
        ]
        self.assertEqual(offenders, [])

    def test_every_app_page_carries_the_dialog(self):
        response = self.client.get(reverse('account-index'))
        self.assertContains(response, 'id="confirm-dialog"', count=1)
        self.assertContains(response, 'window.confirmDialog')

    def test_the_message_is_an_escaped_attribute(self):
        GuestProfile.objects.create(owner=self.profile, name='Ann "<b>"')

        response = self.client.get(reverse('account-guests'))

        self.assertContains(response, 'data-confirm="Eliminare l\'ospite Ann &quot;&lt;b&gt;&quot;?"')
        self.assertContains(response, 'data-confirm-label="Elimina"')
