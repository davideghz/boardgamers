from datetime import timedelta
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.translation import override

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Event, EventDate


class EventNotFoundTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory(preferred_language='it')
        cls.visitor = UserProfileFactory(preferred_language='it')
        organizer = LocationFactory(creator=cls.manager)
        cls.draft = Event.objects.create(
            name='Secret Draft Name', slug='draft-event', organizer_location=organizer,
        )
        cls.blocked = Event.objects.create(
            name='Secret Blocked Name', slug='blocked-event', organizer_location=organizer,
            status=Event.BLOCKED,
        )
        cls.published = Event.objects.create(
            name='Published Event', organizer_location=organizer, status=Event.PUBLISHED,
            table_booking_enabled=False, enable_public_games=False,
        )
        for event in (cls.draft, cls.blocked, cls.published):
            EventDate.objects.create(event=event, date=timezone.localdate() + timedelta(days=2))

    def test_unknown_draft_and_blocked_events_have_the_same_public_message(self):
        events_url = reverse('event-index')
        login_url = reverse('login')
        for user in (None, self.visitor.user):
            if user:
                self.client.force_login(user)
            for slug in ('unknown-event', self.draft.slug, self.blocked.slug):
                for view in ('event_detail', 'event-program', 'event-games'):
                    with self.subTest(user=user, slug=slug, view=view):
                        path = reverse(view, args=[slug])
                        response = self.client.get(path)
                        self.assertTemplateUsed(response, 'events/event_not_found.html')
                        self.assertContains(response, 'Ritrovo non disponibile', status_code=404)
                        self.assertContains(response, f'href="{events_url}"', status_code=404)
                        self.assertNotContains(response, self.draft.name, status_code=404)
                        self.assertNotContains(response, self.blocked.name, status_code=404)
                        self.assertIsNone(response.context['public_event'])
                        login_link = login_url + '?' + urlencode({'next': path})
                        if user:
                            self.assertNotContains(response, login_link, status_code=404)
                        else:
                            self.assertContains(response, login_link, status_code=404)

    def test_hidden_sections_link_back_to_the_public_event(self):
        for view, title in (('event-program', 'Programma non disponibile'),
                            ('event-games', 'Catalogo non disponibile')):
            with self.subTest(view=view):
                response = self.client.get(reverse(view, args=[self.published.slug]))
                self.assertContains(response, title, status_code=404)
                self.assertContains(response, "Torna al ritrovo", status_code=404)
                self.assertContains(response, f'href="{self.published.get_absolute_url()}"',
                                    status_code=404)
        self.assertEqual(self.client.get(self.published.get_absolute_url()).status_code, 200)

    def test_english_error_links_to_the_english_event_list(self):
        with override('en'):
            response = self.client.get(reverse('event_detail', args=['unknown-event']))
            self.assertContains(response, 'Gathering unavailable', status_code=404)
            self.assertContains(response, f'href="{reverse("event-index")}"', status_code=404)

    def test_managers_keep_access_to_previews_and_hidden_sections(self):
        self.client.force_login(self.manager.user)
        for event in (self.draft, self.blocked):
            response = self.client.get(event.get_absolute_url())
            self.assertTemplateUsed(response, 'events/_status_banner.html')
            self.assertContains(response, event.name)
        for view in ('event-program', 'event-games'):
            self.assertEqual(self.client.get(reverse(view, args=[self.published.slug])).status_code, 200)

    @override_settings(SOCIAL_AUTH_GOOGLE_OAUTH2_KEY='test-key', SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET='test-secret')
    def test_login_retains_the_original_url_including_filters(self):
        password = 'LocalEventLogin123'
        user = self.manager.user
        user.set_password(password)
        user.save(update_fields=['password'])
        original = reverse('event-program', args=[self.draft.slug]) + '?date=all&show_past=1'
        login_url = reverse('login') + '?' + urlencode({'next': original})
        self.assertContains(self.client.get(original), login_url, status_code=404)

        login_page = self.client.get(login_url)
        self.assertContains(login_page, f'action="{login_url}"')
        self.assertContains(login_page, f'name="next" value="{escape(original)}"')
        google_start = self.client.post('/login/google-oauth2/?lang=it', {'next': original})
        self.assertEqual(google_start.status_code, 302)
        self.assertEqual(self.client.session['next'], original)

        response = self.client.post(login_url, {'username': user.username, 'password': password})
        self.assertRedirects(response, original)
