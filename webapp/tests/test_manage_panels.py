from django.test import TestCase
from django.urls import URLPattern, get_resolver, reverse

from webapp.services.ui_personas import seed_ui_personas
from webapp.tests.test_location_table_access import italian


def page_names(prefix):
    """The URL names of the management pages under `prefix` that take only the slug."""
    names = []
    for pattern in get_resolver().url_patterns:
        if isinstance(pattern, URLPattern) and pattern.name and pattern.name.startswith(prefix):
            if list(pattern.pattern.regex.groupindex) == ['slug']:
                names.append(pattern.name)
    return names


class LocationManagePanelTest(TestCase):
    """G1: the location's panel by task, with what waits on top."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def setUp(self):
        self.client.force_login(self.data.manager.user)
        self.circolo = self.data.circolo
        self.response = self.client.get(reverse('location-manage', args=[self.circolo.slug]))

    def test_every_management_page_is_reachable(self):
        slug = self.circolo.slug
        excluded = {'location-manage', 'location-manage-areas-reorder', 'location-manage-stations-reorder'}
        names = set(page_names('location-manage')) - excluded
        names |= {'location-membership-documents', 'location-venue-layout-requests'}
        for name in sorted(names):
            with self.subTest(name):
                self.assertContains(self.response, f'href="{reverse(name, args=[slug])}"')

    def test_groups_and_what_waits(self):
        for group in ('Details and visibility', 'Spaces', 'People', 'Library', 'Integrations'):
            self.assertContains(self.response, italian(group))
        # The member's pending renewal of the seed is waiting here
        self.assertEqual([item.key for item in self.response.context['todo']], ['membership_requests'])
        self.assertContains(self.response, italian('Waiting for you'))
