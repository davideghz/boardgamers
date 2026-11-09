from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from webapp.factories import UserProfileFactory, LocationFactory, GameFactory
from webapp.models import LocationGame, LocationGameTag
from webapp.services.games import merge_games


class LocationGameTagsTest(TestCase):
    def setUp(self):
        translation.activate('en')
        self.addCleanup(translation.deactivate)
        self.owner = UserProfileFactory(preferred_language='en')
        self.outsider = UserProfileFactory(preferred_language='en')
        self.location = LocationFactory(creator=self.owner)
        self.slug = {'slug': self.location.slug}
        self.manage_url = reverse('location-manage-games', kwargs=self.slug)
        self.add_url = reverse('location-add-game', kwargs=self.slug)
        self.loan = LocationGameTag.objects.create(location=self.location, name="On loan")
        self.repair = LocationGameTag.objects.create(location=self.location, name="To repair")
        self.client.force_login(self.owner.user)

    def entry(self, name, *tags):
        entry = LocationGame.objects.create(location=self.location, game=GameFactory(name=name))
        entry.tags.add(*tags)
        return entry

    def test_outsider_is_refused_everywhere(self):
        self.client.force_login(self.outsider.user)
        urls = [
            reverse('location-game-tag-add', kwargs=self.slug),
            reverse('location-game-tag-update', kwargs={**self.slug, 'pk': self.loan.pk}),
            reverse('location-game-tag-delete', kwargs={**self.slug, 'pk': self.loan.pk}),
            reverse('location-game-tags-reorder', kwargs=self.slug),
        ]
        for url in urls:
            self.assertEqual(self.client.post(url, {'name': 'X'}).status_code, 403)
        self.assertEqual(self.location.game_tags.count(), 2)
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.name, "On loan")

    def test_tag_lifecycle(self):
        add = reverse('location-game-tag-add', kwargs=self.slug)
        self.client.post(add, {'name': 'Italian'})
        tag = self.location.game_tags.get(name='Italian')
        self.assertEqual(tag.order, 1)

        self.client.post(add, {'name': 'italian'})  # same name, other case
        self.assertEqual(self.location.game_tags.filter(name__iexact='italian').count(), 1)

        update = reverse('location-game-tag-update', kwargs={**self.slug, 'pk': tag.pk})
        self.client.post(update, {'name': 'Language independent'})
        tag.refresh_from_db()
        self.assertEqual(tag.name, 'Language independent')

        self.client.post(reverse('location-game-tag-delete', kwargs={**self.slug, 'pk': tag.pk}))
        self.assertFalse(self.location.game_tags.filter(pk=tag.pk).exists())

    def test_same_name_is_allowed_in_another_location(self):
        other = LocationFactory()
        LocationGameTag.objects.create(location=other, name="Italian")
        self.client.post(reverse('location-game-tag-add', kwargs=self.slug), {'name': 'Italian'})
        self.assertTrue(self.location.game_tags.filter(name='Italian').exists())

    def test_tag_of_another_location_is_not_reachable(self):
        foreign = LocationGameTag.objects.create(location=LocationFactory(), name="X")
        for name in ('location-game-tag-update', 'location-game-tag-delete'):
            self.client.post(reverse(name, kwargs={**self.slug, 'pk': foreign.pk}), {'name': 'Y'})
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "X")

    def test_reorder_only_touches_this_location(self):
        foreign = LocationGameTag.objects.create(location=LocationFactory(), name="X", order=7)
        self.client.post(
            reverse('location-game-tags-reorder', kwargs=self.slug),
            data={'tags': [{'id': self.loan.pk, 'order': 9}, {'id': foreign.pk, 'order': 9}]},
            content_type='application/json')
        self.loan.refresh_from_db()
        foreign.refresh_from_db()
        self.assertEqual(self.loan.order, 9)
        self.assertEqual(foreign.order, 7)

    def test_add_and_edit_game_with_tags(self):
        game = GameFactory(name="Azul")
        self.client.post(self.add_url, {
            'game': game.pk, 'tags': [self.loan.pk],
            'ownership': LocationGame.OWNED_BY_LOCATION, 'physical_location': LocationGame.AT_ASSOCIATION})
        entry = LocationGame.objects.get(location=self.location, game=game)
        self.assertEqual(list(entry.tags.all()), [self.loan])

        detail = reverse('location-game-detail', kwargs={**self.slug, 'game_uuid': entry.uuid})
        self.client.post(detail, {
            'game': game.pk, 'tags': [self.repair.pk],
            'ownership': LocationGame.OWNED_BY_LOCATION, 'physical_location': LocationGame.AT_ASSOCIATION})
        self.assertEqual(list(entry.tags.all()), [self.repair])

    def test_tags_of_another_location_are_refused(self):
        foreign = LocationGameTag.objects.create(location=LocationFactory(), name="X")
        response = self.client.post(self.add_url, {
            'game': GameFactory(name="Azul").pk, 'tags': [foreign.pk],
            'ownership': LocationGame.OWNED_BY_LOCATION, 'physical_location': LocationGame.AT_ASSOCIATION})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LocationGame.objects.exists())

    def test_manage_pages_show_tags(self):
        entry = self.entry("Azul", self.loan)
        response = self.client.get(self.manage_url)
        self.assertContains(response, "On loan")
        self.assertContains(response, "To repair")
        detail = reverse('location-game-detail', kwargs={**self.slug, 'game_uuid': entry.uuid})
        self.assertContains(self.client.get(detail), "To repair")
        self.assertEqual(self.client.get(self.add_url).status_code, 200)

    def test_csv_lists_the_tags(self):
        self.entry("Azul", self.loan, self.repair)
        response = self.client.get(reverse('location-games-csv', kwargs=self.slug))
        self.assertIn("On loan, To repair", response.content.decode())

    def test_tags_stay_out_of_the_public_library(self):
        self.entry("Azul", self.loan)
        self.client.logout()
        response = self.client.get(reverse('location-games', kwargs=self.slug))
        self.assertContains(response, "Azul")
        self.assertNotContains(response, "On loan")

    def test_merge_folds_the_tags(self):
        kept = self.entry("Keeper", self.loan)
        dup = self.entry("Dup", self.repair)
        merge_games(kept.game, dup.game, {})
        entry = LocationGame.objects.get(location=self.location)
        self.assertEqual(entry.pk, kept.pk)
        self.assertEqual(set(entry.tags.all()), {self.loan, self.repair})
