from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from webapp.views.static_page_views import PRESS_LOGOS


class PressPageTest(TestCase):
    def setUp(self):
        translation.activate('en')
        self.addCleanup(translation.deactivate)

    def test_renders(self):
        response = self.client.get(reverse('press'))
        self.assertContains(response, "Press kit")
        self.assertContains(response, "info@board-gamers.com")

    def test_every_logo_file_exists_and_is_offered(self):
        response = self.client.get(reverse('press'))
        for logo in PRESS_LOGOS:
            for _label, name in logo['files'] + [('preview', logo['preview'])]:
                self.assertIsNotNone(finders.find(f'images/logo/{name}'), name)
                self.assertContains(response, f'images/logo/{name}')

    def test_footer_links(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, f'href="{reverse("press")}"')
        self.assertNotContains(response, "Add your location")

    def test_in_sitemap(self):
        self.assertContains(self.client.get('/sitemap.xml'), reverse('press'))
