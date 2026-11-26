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


class OrganizedEventsTest(TestCase):
    """G3: the organized events as result rows, by drafts, upcoming and past."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def events(self, show=None):
        self.client.force_login(self.data.manager.user)
        url = reverse('location-manage-events', args=[self.data.associazione.slug])
        response = self.client.get(url, {'show': show} if show else None)
        self.assertEqual(response.status_code, 200)
        return response, [event.name for event in response.context['events']]

    def test_three_tabs(self):
        response, upcoming = self.events()
        self.assertIn(self.data.night.name, upcoming)
        self.assertNotIn(self.data.draft_event.name, upcoming)
        self.assertNotIn('Serata Demo passata', upcoming)
        self.assertContains(response, f'href="{reverse("location-event-create", args=[self.data.associazione.slug])}"')
        # Rows lead to the event's management
        self.assertContains(response, f'href="{reverse("event-manage", args=[self.data.night.slug])}"')

        response, drafts = self.events('drafts')
        self.assertEqual(drafts, [self.data.draft_event.name])
        self.assertContains(response, italian('Draft'))
        self.assertEqual(self.events('past')[1], ['Serata Demo passata'])

    def test_the_draft_to_do_opens_the_drafts(self):
        self.client.force_login(self.data.manager.user)
        response = self.client.get(reverse('location-manage', args=[self.data.associazione.slug]))
        drafts = reverse('location-manage-events', args=[self.data.associazione.slug], query={'show': 'drafts'})
        self.assertContains(response, f'href="{drafts}"')


class FestivalManagePanelTest(TestCase):
    """G4: the festival's management is a panel of four pages, approval on top."""

    @classmethod
    def setUpTestData(cls):
        cls.data = seed_ui_personas()

    def test_panel_with_its_four_pages(self):
        master = self.data.manifestation
        self.client.force_login(self.data.organizer.user)
        response = self.client.get(reverse('master-event-manage', args=[master.slug]))
        self.assertContains(response, 'Pubblicata')
        for name in ('master-event-manage-data', 'master-event-manage-dates', 'master-event-manage-events',
                     'master-event-manage-people'):
            with self.subTest(name):
                url = reverse(name, args=[master.slug])
                self.assertContains(response, f'href="{url}"')
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                # Each page leads back to the panel
                self.assertContains(page, f'href="{reverse("master-event-manage", args=[master.slug])}"')

    def test_a_draft_says_what_is_missing_and_approvers_approve_here(self):
        from webapp.factories import UserProfileFactory
        from webapp.models import Event, MasterEvent

        master = MasterEvent.objects.create(name='Fiera nuova', status=Event.DRAFT)
        master.managers.add(self.data.organizer)
        self.client.force_login(self.data.organizer.user)
        response = self.client.get(reverse('master-event-manage', args=[master.slug]))
        self.assertContains(response, italian('Waiting for approval'))
        self.assertEqual(len(response.context['pending']), 2)  # no dates, no events
        approve = reverse('master-event-approve', args=[master.slug])
        self.assertNotContains(response, approve)

        admin = UserProfileFactory()
        admin.user.is_staff = admin.user.is_superuser = True
        admin.user.save()
        master.managers.add(admin)
        self.client.force_login(admin.user)
        self.assertContains(self.client.get(reverse('master-event-manage', args=[master.slug])), approve)
