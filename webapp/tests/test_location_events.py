from datetime import time, timedelta
from io import BytesIO
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation
from PIL import Image

from webapp.factories import GameFactory, LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Event, EventDate, Location, LocationEvent, LocationFollower, Member, Membership, \
    Notification, PhysicalTable, PlayArea, Table


class LocationEventTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory(preferred_language='it')
        cls.manager = UserProfileFactory(preferred_language='it')
        cls.location = LocationFactory(creator=cls.owner, city='Genova', address='Via della Lanterna 10')
        cls.location.managers.add(cls.manager)
        cls.other_location = LocationFactory(creator=cls.owner, city='Savona')
        cls.tomorrow = timezone.localdate() + timedelta(days=1)

    def setUp(self):
        self.enterContext(translation.override('it'))

    def create_location_event(self, **fields):
        fields.setdefault('date', self.tomorrow)
        return LocationEvent.objects.create(
            name='Gioco libero', creator=self.manager, host_location=self.location,
            opening_time=time(20), closing_time=time(1), **fields,
        )

    def create_membership(self, profile, **fields):
        member = Member.objects.create(location=self.location, user_profile=profile, first_name='Test', last_name='Member')
        return Membership.objects.create(member=member, status=Membership.ACTIVE, **fields)

    def test_create_uses_location_from_url_and_stores_one_date(self):
        self.client.force_login(self.manager.user)
        url = reverse('location-event-create', args=[self.location.slug])
        self.assertContains(self.client.get(url), self.location.name)

        response = self.client.post(url, {
            'name': 'Serata GdR', 'date': self.tomorrow.isoformat(), 'opening_time': '20:00',
            'closing_time': '01:00', 'host_location': self.other_location.pk, 'status': Event.PUBLISHED,
        })

        event = LocationEvent.objects.get(name='Serata GdR')
        self.assertRedirects(response, event.action_url('manage'))
        self.assertEqual((event.host_location, event.kind, event.status),
                         (self.location, Event.Kind.LOCATION, Event.DRAFT))
        self.assertFalse(Event.objects.filter(name='Serata GdR').exists())
        self.assertEqual(event.date, self.tomorrow)
        foreign_url = reverse('location-event-create', args=[self.other_location.slug])
        self.assertEqual(self.client.post(foreign_url, {'name': 'Unauthorized'}).status_code, 403)

    def test_revoked_manager_loses_access_even_as_creator(self):
        event = self.create_location_event()
        self.client.force_login(self.manager.user)
        account_url = reverse('account-events')
        manage_url = event.action_url('manage')
        self.assertContains(self.client.get(account_url), manage_url)

        self.location.managers.remove(self.manager)

        self.assertNotContains(self.client.get(account_url), manage_url)
        self.assertEqual(self.client.get(manage_url).status_code, 404)
        self.assertEqual(self.client.post(event.action_url('approve')).status_code, 403)

    def test_event_management_is_in_the_host_location(self):
        event = self.create_location_event()
        other_event = LocationEvent.objects.create(name='Altra sede', host_location=self.other_location)
        self.client.force_login(self.owner.user)
        manage_events = reverse('location-manage-events', args=[self.location.slug])
        manage_games = reverse('location-manage-games', args=[self.location.slug])
        index = self.client.get(reverse('location-manage', args=[self.location.slug]))
        self.assertLess(index.text.index(manage_events), index.text.index(manage_games))
        self.assertContains(self.client.get(manage_events), event.action_url('manage'))
        self.assertNotContains(self.client.get(manage_events), other_event.name)
        wrong_host = reverse('location-event-manage', args=[self.other_location.slug, event.slug])
        self.assertEqual(self.client.get(wrong_host).status_code, 404)
        wrong_approval = reverse('location-event-approve', args=[self.other_location.slug, event.slug])
        self.assertEqual(self.client.post(wrong_approval).status_code, 404)
        self.assertRedirects(self.client.get(f'/location-events/{event.slug}/manage/'), event.action_url('manage'))

    def test_manage_event_cover_previews_saved_upload_and_restores_location_fallback(self):
        media_root = self.enterContext(TemporaryDirectory())
        self.enterContext(self.settings(MEDIA_ROOT=media_root, USE_S3=False))
        self.location.cover = 'location-covers/logo.png'
        self.location.save(update_fields=['cover'])
        event = self.create_location_event()
        self.client.force_login(self.manager.user)
        url = event.action_url('manage-data')

        response = self.client.get(url)
        self.assertContains(response, 'id="event-cover-dialog"')
        self.assertNotContains(response, 'name="cover-clear"')
        self.assertEqual(event.cover_url, self.location.cover_url)

        image = BytesIO()
        Image.new('RGB', (320, 180), 'navy').save(image, format='PNG')
        cover = SimpleUploadedFile('cover.png', image.getvalue(), content_type='image/png')
        response = self.client.post(url, {'name': event.name, 'cover': cover})
        self.assertRedirects(response, event.action_url('manage'))
        event.refresh_from_db()
        self.assertTrue(event.cover)
        response = self.client.get(url)
        self.assertContains(response, f'src="{event.cover.url}"')
        self.assertContains(response, 'name="cover-clear"')

        response = self.client.post(url, {'name': event.name, 'cover-clear': 'on'})
        self.assertRedirects(response, event.action_url('manage'))
        event = LocationEvent.objects.get(pk=event.pk)
        self.assertFalse(event.cover)
        self.assertEqual(event.cover_url, self.location.cover_url)

    def test_members_can_create_and_edit_their_own_draft_with_permission(self):
        self.client.force_login(self.manager.user)
        permissions_url = reverse('location-manage-permissions', args=[self.location.slug])
        self.assertRedirects(self.client.post(permissions_url, {
            'table_creation_permission': Location.PERM_ANYONE, 'table_join_permission': Location.PERM_ANYONE,
            'event_creation_permission': Location.PERM_MEMBERS_ONLY, 'event_join_permission': Location.PERM_MEMBERS_ONLY,
        }), reverse('location-manage', args=[self.location.slug]))

        url = reverse('location-event-create', args=[self.location.slug])
        data = {'name': 'Serata dei soci', 'date': self.tomorrow.isoformat(), 'opening_time': '20:00', 'closing_time': '01:00'}
        self.assertEqual(self.client.post(url, data).status_code, 403)
        member = UserProfileFactory(preferred_language='it')
        expired = UserProfileFactory(preferred_language='it')
        self.create_membership(member)
        self.create_membership(expired, end_date=timezone.localdate() - timedelta(days=1))
        self.client.force_login(expired.user)
        self.assertEqual(self.client.post(url, data).status_code, 403)

        self.client.force_login(member.user)
        self.assertContains(self.client.get(reverse('location-detail', args=[self.location.slug])), url)
        response = self.client.post(url, data)
        event = LocationEvent.objects.get(name=data['name'])
        self.assertEqual(event.status, Event.DRAFT)
        self.assertRedirects(response, event.action_url('manage'))
        self.assertContains(self.client.get(reverse('account-events')), event.action_url('manage'))
        self.assertEqual(self.client.get(event.action_url('manage-data')).status_code, 200)
        self.assertEqual(self.client.get(event.action_url('manage-participants')).status_code, 403)
        self.assertEqual(self.client.post(event.action_url('approve')).status_code, 403)

        self.client.force_login(self.owner.user)
        self.assertRedirects(self.client.post(event.action_url('approve')), event.action_url('manage'))
        self.client.force_login(member.user)
        self.assertEqual(self.client.get(event.action_url('manage-data')).status_code, 403)

    def test_only_active_members_can_join_a_restricted_event(self):
        self.location.event_join_permission = Location.PERM_MEMBERS_ONLY
        self.location.save(update_fields=['event_join_permission'])
        event = self.create_location_event(status=Event.PUBLISHED)
        join_url = event.action_url('join')
        self.assertEqual(self.client.post(join_url).status_code, 302)

        self.client.force_login(self.owner.user)
        self.assertNotContains(self.client.get(event.get_absolute_url()), f'action="{join_url}"')
        self.assertEqual(self.client.post(join_url).status_code, 403)
        self.assertFalse(event.participants.exists())

        membership = self.create_membership(self.owner)
        self.assertContains(self.client.get(event.get_absolute_url()), f'action="{join_url}"')
        self.assertRedirects(self.client.post(join_url), event.get_absolute_url())
        self.assertEqual(event.participants.get().user_profile, self.owner)
        membership.status = Membership.EXPIRED
        membership.save(update_fields=['status'])
        self.assertRedirects(self.client.post(event.action_url('leave')), event.get_absolute_url())
        self.assertFalse(event.participants.exists())

    def test_location_page_and_search_distinguish_hosted_and_sponsored_events(self):
        hosted = self.create_location_event(status=Event.PUBLISHED)
        hosted.participants.create(user_profile=self.owner)
        manifestation = Event.objects.create(name='Fiera', status=Event.PUBLISHED, city='Genova')
        manifestation.sponsor_locations.add(self.location)
        EventDate.objects.create(event=manifestation, date=self.tomorrow)
        table = TableFactory(location=self.location, date=self.tomorrow)

        detail = self.client.get(reverse('location-detail', args=[self.location.slug]))
        self.assertEqual(list(detail.context['hosted_events']), [hosted])
        self.assertEqual(detail.context['hosted_events'][0].participant_count, 1)
        self.assertEqual(list(detail.context['sponsored_events']), [manifestation])
        self.assertTemplateUsed(detail, 'tags/location_event_card.html')
        self.assertTemplateUsed(detail, 'tags/manifestation_card.html')
        self.assertTemplateUsed(detail, 'tags/table_card.html')
        self.assertLess(detail.text.index(f'href="{hosted.get_absolute_url()}"'),
                        detail.text.index(f'href="{table.get_absolute_url()}"'))
        self.assertContains(self.client.get(hosted.get_absolute_url()), self.location.address)

        search_url = reverse('appointment-search')
        self.assertContains(detail, f'href="{search_url}?type=events&amp;location={self.location.slug}"')
        exact = self.client.get(search_url, {'location': self.location.slug})
        self.assertCountEqual(exact.context['items'], [('event', hosted), ('table', table)])
        self.assertContains(exact, '?type=manifestations"')
        only_events = self.client.get(search_url, {'type': 'events', 'location': self.location.slug})
        self.assertEqual(only_events.context['items'], [('event', hosted)])
        by_kind = self.client.get(search_url, {'type': 'manifestations'})
        self.assertEqual(by_kind.context['items'], [('manifestation', manifestation)])
        self.assertNotContains(self.client.get(reverse('event-index')), hosted.get_absolute_url())

    def test_home_displays_published_location_events_and_their_tables(self):
        published = self.create_location_event(status=Event.PUBLISHED)
        without_tables = self.create_location_event(status=Event.PUBLISHED)
        without_tables.participants.create(user_profile=self.owner)
        draft = self.create_location_event()
        self.create_location_event(status=Event.PUBLISHED, date=timezone.localdate() - timedelta(days=2))
        manifestation = Event.objects.create(name='Fiera', status=Event.PUBLISHED)
        EventDate.objects.create(event=manifestation, date=self.tomorrow)
        table = TableFactory(location=self.location, location_event=published, date=self.tomorrow)
        draft_table = TableFactory(location=self.location, location_event=draft, date=self.tomorrow)

        for user, expected_tables in ((None, [table]), (self.owner.user, [table]), (UserProfileFactory().user, [])):
            with self.subTest(user=user):
                if user:
                    self.client.force_login(user)
                home = self.client.get(reverse('home'))
                self.assertEqual(list(home.context['upcoming_location_events']), [published, without_tables])
                self.assertEqual([event.participant_count for event in home.context['upcoming_location_events']], [0, 1])
                self.assertEqual(list(home.context['upcoming_events']), [manifestation])
                self.assertEqual(list(home.context['future_tables']), expected_tables)
                self.assertTemplateUsed(home, 'tags/location_event_card.html')
                self.assertTemplateUsed(home, 'tags/manifestation_card.html')
                if expected_tables:
                    self.assertTemplateUsed(home, 'tags/table_card.html')
                    self.assertLess(home.text.index(f'href="{published.get_absolute_url()}"'),
                                    home.text.index(f'href="{table.get_absolute_url()}"'))
                self.assertContains(home, without_tables.get_absolute_url())
                self.assertContains(home, '20:00 – 01:00')
                self.assertNotContains(home, draft.get_absolute_url())
                self.assertNotContains(home, draft_table.get_absolute_url())

    def test_home_respects_the_locations_events_setting(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        self.client.force_login(self.owner.user)
        self.assertContains(self.client.get(reverse('home')), event.get_absolute_url())
        url = reverse('location-manage-data', args=[self.location.slug])
        self.assertContains(self.client.get(url), 'name="show_events_in_homepage"')
        self.assertRedirects(self.client.post(url, {
            'name': self.location.name, 'description': self.location.description,
            'address': self.location.address, 'city': self.location.city,
            'latitude': self.location.latitude, 'longitude': self.location.longitude,
            'leaderboard_edit_days': self.location.leaderboard_edit_days,
            'show_tables_in_homepage': 'on',
        }), reverse('location-detail', args=[self.location.slug]))
        self.location.refresh_from_db()
        self.assertFalse(self.location.show_events_in_homepage)
        self.assertNotContains(self.client.get(reverse('home')), event.get_absolute_url())
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('home')), event.get_absolute_url())
        self.assertContains(self.client.get(reverse('location-detail', args=[self.location.slug])), event.get_absolute_url())
        self.assertContains(self.client.get(reverse('appointment-search'), {'type': 'events'}), event.get_absolute_url())

    def test_event_card_uses_event_cover_then_location_logo_then_placeholder(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        placeholder = settings.STATIC_URL + settings.DEFAULT_LOCATION_COVER_URL
        search = reverse('appointment-search')
        self.assertEqual(event.cover_url, placeholder)

        self.location.cover = 'location-covers/event-logo.png'
        self.location.save(update_fields=['cover'])
        self.assertContains(self.client.get(search), f'src="{self.location.cover.url}"')
        self.assertEqual(LocationEvent.objects.get(pk=event.pk).cover_url, self.location.cover.url)

        event.cover = 'event-covers/own-cover.png'
        event.save(update_fields=['cover'])
        self.assertContains(self.client.get(search), f'src="{event.cover.url}"')
        self.assertEqual(LocationEvent.objects.get(pk=event.pk).cover_url, event.cover.url)

    def test_editing_date_reschedules_the_same_occurrence(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        table = TableFactory(location=self.location, location_event=event, date=self.tomorrow, time=time(21))
        table.players.add(self.manager)
        other_table = TableFactory(location=self.location, date=self.tomorrow)
        self.client.force_login(self.owner.user)
        revised = self.tomorrow + timedelta(days=7)

        response = self.client.post(event.action_url('manage-dates'), {
            'date': revised.isoformat(), 'opening_time': '20:00', 'closing_time': '01:00',
        })

        self.assertRedirects(response, event.action_url('manage'))
        event.refresh_from_db()
        self.assertEqual(event.date, revised)
        table.refresh_from_db()
        other_table.refresh_from_db()
        self.assertEqual((table.date, table.time), (revised, time(21)))
        self.assertEqual(list(table.players.all()), [self.manager])
        self.assertEqual(other_table.date, self.tomorrow)

    def test_manager_creates_a_location_table_from_the_event(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        other_event = self.create_location_event(status=Event.PUBLISHED)
        other_table = TableFactory(location=self.location, location_event=other_event, date=self.tomorrow)
        self.client.force_login(self.manager.user)
        url = event.action_url('table-create')
        manage_url = event.action_url('manage')
        self.assertContains(self.client.get(manage_url), url)
        form = self.client.get(url).context['form']
        self.assertTrue(form.fields['date'].disabled)
        self.assertEqual(form['date'].value(), self.tomorrow)
        self.assertEqual(form['time'].value(), time(20))

        data = {
            'title': 'Tavolo introduttivo', 'description': 'Per chi vuole provare',
            'time': '21:00', 'min_players': 2, 'max_players': 5, 'duration': 90,
            'date': (self.tomorrow + timedelta(days=3)).isoformat(), 'location': self.other_location.pk,
            'event': other_event.pk, 'location_event': other_event.pk,
            'join_table': 'on', 'links-TOTAL_FORMS': 1, 'links-INITIAL_FORMS': 0,
            'links-0-label': 'Regolamento', 'links-0-url': 'https://example.com/rules',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, response.context and response.context['form'].errors)
        table = Table.objects.get(title=data['title'])
        self.assertRedirects(response, table.get_absolute_url())
        self.assertEqual((table.location, table.location_event, table.date, table.time),
                         (self.location, event, self.tomorrow, time(21)))
        self.assertIsNone(table.event_id)
        self.assertEqual(table.get_absolute_url(), reverse('table-detail', args=[table.slug]))
        self.assertEqual(table.links.get().label, 'Regolamento')
        self.assertEqual(list(table.players.all()), [self.manager])
        self.assertFalse(event.participants.exists())
        self.assertContains(self.client.get(manage_url), table.get_absolute_url())

        edit_url = reverse('location-table-update', args=[self.location.slug, table.slug])
        data.update({'time': '22:00', 'links-INITIAL_FORMS': 1, 'links-0-id': table.links.get().pk})
        self.assertRedirects(self.client.post(edit_url, data), table.get_absolute_url())
        table.refresh_from_db()
        self.assertEqual((table.location, table.location_event, table.date, table.time),
                         (self.location, event, self.tomorrow, time(22)))

        self.client.logout()
        detail = self.client.get(event.get_absolute_url())
        self.assertContains(detail, table.get_absolute_url())
        self.assertNotContains(detail, other_table.get_absolute_url())
        self.assertContains(self.client.get(table.get_absolute_url()), event.get_absolute_url())
        location_detail = self.client.get(reverse('location-detail', args=[self.location.slug]))
        self.assertIn(table, location_detail.context['future_tables'])
        search = self.client.get(reverse('appointment-search'), {'location': self.location.slug, 'type': 'tables'})
        self.assertIn(('table', table), search.context['items'])

    def test_location_event_program_groups_tables_and_only_shows_useful_filters(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        room = PlayArea.objects.create(location=self.location, name='Sala')
        garden = PlayArea.objects.create(location=self.location, name='Giardino')
        station = PhysicalTable.objects.create(location=self.location, play_area=room, name='Postazione 1')
        game = GameFactory()
        first = TableFactory(location=self.location, location_event=event, date=self.tomorrow, time=time(20),
                             game=game, physical_table=station)
        second = TableFactory(location=self.location, location_event=event, date=self.tomorrow, time=time(20),
                              game=game, play_area=garden)
        url = event.get_absolute_url()

        detail = self.client.get(url)
        self.assertContains(detail, 'name="area"')
        self.assertNotContains(detail, 'name="game"')
        self.assertEqual(detail.context['location_program']['slots'], [{'time': time(20), 'tables': [first, second]}])

        other_game = GameFactory()
        third = TableFactory(location=self.location, location_event=event, date=self.tomorrow, time=time(21),
                             game=other_game, play_area=garden)
        matching = self.client.get(url, {'area': garden.pk, 'game': other_game.pk})
        self.assertContains(matching, 'name="game"')
        self.assertContains(matching, third.get_absolute_url())
        self.assertNotContains(matching, first.get_absolute_url())
        self.assertNotContains(matching, second.get_absolute_url())

        by_station_area = self.client.get(url, {'area': room.pk, 'game': 'invalid'})
        self.assertEqual(by_station_area.context['location_program']['slots'], [{'time': time(20), 'tables': [first]}])
        empty = self.client.get(url, {'area': room.pk, 'game': other_game.pk})
        self.assertEqual(empty.context['location_program']['slots'], [])
        self.assertContains(empty, f'{url}#location-table-program')

    def test_adding_a_table_requires_current_location_staff(self):
        event = self.create_location_event()
        url = event.action_url('table-create')
        manage_url = event.action_url('manage')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(manage_url), url)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.location.managers.remove(self.manager)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(event.tables.exists())

    def test_draft_tables_are_private_until_the_event_is_published(self):
        event = self.create_location_event()
        follower = UserProfileFactory()
        LocationFollower.objects.create(location=self.location, user_profile=follower)
        self.client.force_login(self.manager.user)
        response = self.client.post(event.action_url('table-create'), {
            'title': 'Tavolo in preparazione', 'description': 'Prova in programma',
            'time': '21:00', 'min_players': 2, 'max_players': 5, 'duration': 90,
            'links-TOTAL_FORMS': 0, 'links-INITIAL_FORMS': 0,
        })
        table = event.tables.get()
        table_url = table.get_absolute_url()
        self.assertRedirects(response, table_url)
        self.assertContains(self.client.get(event.get_absolute_url()), table_url)
        self.assertFalse(Notification.objects.filter(table=table).exists())

        self.client.force_login(follower.user)
        search_url = reverse('appointment-search') + f'?location={self.location.slug}&type=tables'
        location_url = reverse('location-detail', args=[self.location.slug])
        widget_url = reverse('tables-by-location', args=[self.location.slug])
        join_url = reverse('join_table', args=[table.slug])
        manifestation_url = reverse('event_table_detail', args=[event.slug, table.slug])
        self.assertNotContains(self.client.get(search_url), table_url)
        self.assertNotContains(self.client.get(location_url), table_url)
        self.assertNotContains(self.client.get(widget_url), table.title)
        self.assertEqual(self.client.get(table_url).status_code, 404)
        self.assertEqual(self.client.get(manifestation_url).status_code, 404)
        self.assertEqual(self.client.post(join_url).status_code, 404)

        self.client.force_login(self.manager.user)
        self.client.post(event.action_url('approve'))

        self.client.force_login(follower.user)
        self.assertContains(self.client.get(search_url), table_url)
        self.assertIn(table, self.client.get(location_url).context['future_tables'])
        self.assertContains(self.client.get(widget_url), table.title)
        self.assertContains(self.client.get(table_url), event.get_absolute_url())
        self.assertEqual(self.client.get(manifestation_url).status_code, 404)
        self.assertRedirects(self.client.post(join_url), table_url)
        self.assertEqual(list(table.players.all()), [follower])
        self.assertFalse(event.participants.exists())

    def test_linked_table_requires_the_event_host_location(self):
        event = self.create_location_event()
        with self.assertRaises(ValidationError):
            TableFactory(location=self.other_location, location_event=event, date=self.tomorrow)
        with self.assertRaises(ValidationError):
            TableFactory(location=None, location_event=event, date=self.tomorrow)

    def test_host_relation_is_required_and_protected(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocationEvent.objects.create(name='Missing host', date=self.tomorrow)
        self.create_location_event()
        with self.assertRaises(ProtectedError):
            self.location.delete()

    def test_legacy_urls_redirect_to_the_independent_location_event(self):
        event = self.create_location_event(status=Event.PUBLISHED, legacy_event_slug='vecchia-serata')
        self.assertRedirects(self.client.get(reverse('event_detail', args=[event.legacy_event_slug])),
                             event.get_absolute_url())
        new_manifestation = Event.objects.create(name='Vecchia serata')
        self.assertNotEqual(new_manifestation.slug, event.legacy_event_slug)

        self.client.force_login(self.owner.user)
        old_manage = reverse('event-manage', args=[event.legacy_event_slug])
        new_manage = event.action_url('manage')
        self.assertRedirects(self.client.get(old_manage), new_manage)

    def test_location_event_attendance_uses_its_own_participants(self):
        event = self.create_location_event(status=Event.PUBLISHED)
        self.client.force_login(self.owner.user)
        self.assertRedirects(self.client.post(reverse('location-event-join', args=[event.slug])),
                             event.get_absolute_url())
        self.assertEqual(event.participants.get().user_profile, self.owner)
        self.assertContains(self.client.get(reverse('account-events')), event.get_absolute_url())
        self.assertRedirects(self.client.post(reverse('location-event-leave', args=[event.slug])),
                             event.get_absolute_url())
        self.assertFalse(event.participants.exists())

    def test_manifestation_owner_cannot_delete_last_published_date(self):
        event = Event.objects.create(name='Festival', creator=self.owner, status=Event.PUBLISHED)
        date = EventDate.objects.create(event=event, date=self.tomorrow)
        self.client.force_login(self.owner.user)

        response = self.client.post(reverse('event-manage-date-delete', args=[event.slug, date.pk]))

        self.assertRedirects(response, reverse('event-manage-dates', args=[event.slug]))
        self.assertTrue(event.dates.filter(pk=date.pk).exists())
