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


class EventManagePanelTest(TestCase):
    """G2: the event's panel with the same groups, the program within reach, and the hosting
    location's spaces marked as such."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def panel(self):
        self.client.force_login(self.data.manager.user)
        return self.client.get(reverse('event-manage', args=[self.data.event.slug]))

    def test_every_management_page_is_reachable(self):
        response, slug = self.panel(), self.data.event.slug
        posted = {'event-manage', 'event-manage-publish', 'event-manage-unpublish', 'event-manage-areas-reorder',
                  'event-manage-categories-reorder', 'event-manage-games-toggle', 'event-manage-game-add',
                  'event-manage-game-tag-add', 'event-manage-game-tags-reorder', 'event-manage-stations-reorder'}
        # Staff and sponsors belong to the organizing location when there is one
        by_location = {'event-manage-managers', 'event-manage-table-creators', 'event-manage-locations'}
        for name in sorted(set(page_names('event-manage')) - posted - by_location) + ['event-program']:
            with self.subTest(name):
                self.assertContains(response, f'href="{reverse(name, args=[slug])}"')
        for group in ('Details and publication', 'Dates and program', 'Spaces', 'Participants and staff'):
            self.assertContains(response, italian(group))

    def test_the_hosting_locations_spaces_say_whose_they_are(self):
        event = self.data.event
        type(event).objects.filter(pk=event.pk).update(layout_mode='venue')
        response = self.panel()
        managed_by = italian('Managed by %(name)s') % {'name': event.venue_location.name}
        self.assertContains(response, managed_by, count=2)
        self.assertContains(response, f'href="{reverse("location-manage-areas", args=[event.venue_location.slug])}"')
