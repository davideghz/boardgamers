from datetime import time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone, translation

from webapp.factories import GameFactory, LocationFactory, TableFactory, UserProfileFactory
from webapp.models import Event, LocationEvent, Player


class AccountActivitiesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.profile = UserProfileFactory(preferred_language='it')
        cls.other = UserProfileFactory()
        cls.location = LocationFactory(creator=cls.profile)
        cls.other_location = LocationFactory(creator=cls.other)
        cls.today = timezone.localdate()
        cls.yesterday = cls.today - timedelta(days=1)

    def setUp(self):
        self.enterContext(translation.override('it'))
        self.url = reverse('account-activities')

    def test_login_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(f'next={self.url}', response.url)

    def test_combines_personal_activities_and_respects_visibility(self):
        owned_table = TableFactory(author=self.profile, location=self.location, date=self.today, time=time(18))
        Player.objects.create(table=owned_table, user_profile=self.profile)
        joined_event = LocationEvent.objects.create(
            name='Gioco libero', creator=self.other, host_location=self.other_location,
            status=LocationEvent.PUBLISHED, date=self.today, opening_time=time(19),
        )
        joined_event.participants.create(user_profile=self.profile)
        joined_table = TableFactory(author=self.other, location=self.other_location, date=self.today, time=time(20))
        Player.objects.create(table=joined_table, user_profile=self.profile)
        own_draft = LocationEvent.objects.create(name='Da programmare', creator=self.profile, host_location=self.location)
        private_event = LocationEvent.objects.create(
            name='Bozza privata', creator=self.profile, host_location=self.other_location, date=self.today,
        )
        private_event.participants.create(user_profile=self.profile)
        private_table = TableFactory(author=self.profile, location=self.other_location, location_event=private_event)
        managed_only = LocationEvent.objects.create(
            name='Serata di un altro organizzatore', date=self.today,
            host_location=self.location, creator=self.other, status=LocationEvent.PUBLISHED,
        )
        manifestation = Event.objects.create(name='Manifestazione', creator=self.profile, status=Event.PUBLISHED)

        self.client.force_login(self.profile.user)
        response = self.client.get(self.url)
        self.assertEqual(response.context['items'], [
            ('table', owned_table), ('event', joined_event), ('table', joined_table), ('event', own_draft),
        ])
        self.assertContains(response, 'Le mie attività')
        self.assertContains(response, 'Tutte')
        self.assertContains(response, 'In programma')
        self.assertContains(response, 'Vecchi')
        self.assertTemplateUsed(response, 'tags/horizontal_table_card.html')
        self.assertTemplateUsed(response, 'tags/horizontal_location_event_card.html')
        for excluded in (private_table, private_event, managed_only, manifestation):
            self.assertNotContains(response, f'href="{excluded.get_absolute_url()}"')

        only_events = self.client.get(self.url, {'type': 'events'})
        self.assertEqual(only_events.context['items'], [('event', joined_event), ('event', own_draft)])
        only_tables = self.client.get(self.url, {'type': 'tables'})
        self.assertEqual(only_tables.context['items'], [('table', owned_table), ('table', joined_table)])
        original = self.client.get(reverse('account-tables'))
        self.assertEqual(list(original.context['tables']), [owned_table, joined_table])

    def test_period_search_and_location_filters_combine(self):
        game = GameFactory(name='Indagine')
        table = TableFactory(
            author=self.profile, location=self.location, game=game, date=self.yesterday, time=time(21),
        )
        event = LocationEvent.objects.create(
            name='Serata GdR', description='Indagine cooperativa', creator=self.profile,
            host_location=self.location, date=self.yesterday, opening_time=time(19), status=LocationEvent.PUBLISHED,
        )
        LocationEvent.objects.create(
            name='Giochi in un altro club', description='Indagine', creator=self.profile,
            host_location=self.other_location, date=self.yesterday, status=LocationEvent.PUBLISHED,
        )
        TableFactory(author=self.profile, location=self.location, game=game, date=self.today)
        self.client.force_login(self.profile.user)

        filters = {'tab': 'past', 'location': self.location.slug, 'q': 'indagine'}
        response = self.client.get(self.url, filters)
        self.assertEqual(response.context['items'], [('table', table), ('event', event)])
        self.assertContains(response, '2 attività trovate')
        response = self.client.get(self.url, {**filters, 'type': 'events'})
        self.assertEqual(response.context['items'], [('event', event)])
        self.assertContains(response, 'name="tab" value="past"')
        self.assertContains(response, 'name="type" value="events"')

    def test_paginates_the_combined_list_and_preserves_filters(self):
        for index in range(15):
            LocationEvent.objects.create(
                name=f'Partita libera {index}', creator=self.profile, host_location=self.location,
                date=self.today, opening_time=time(index), status=LocationEvent.PUBLISHED,
            )
        table = TableFactory(
            title='Partita al tavolo', author=self.profile, location=self.location, date=self.today, time=time(22),
        )
        self.client.force_login(self.profile.user)

        first = self.client.get(self.url, {'q': 'partita'})
        self.assertEqual(len(first.context['items']), 15)
        self.assertTrue(first.context['is_paginated'])
        self.assertContains(first, '?q=partita&amp;page=2')
        second = self.client.get(self.url, {'q': 'partita', 'page': 2})
        self.assertEqual(second.context['items'], [('table', table)])
