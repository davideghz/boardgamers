import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Table


class TableCoverAltTest(TestCase):
    def test_a_table_without_a_game_has_an_empty_alt_not_none(self):
        location = LocationFactory(creator=UserProfileFactory())
        table = Table.objects.create(
            title='Serata', location=location, author=location.creator,
            date=timezone.localdate() + datetime.timedelta(days=2), time=datetime.time(21))

        for url in (reverse('table-detail', args=[table.slug]), reverse('location-detail', args=[location.slug])):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertNotContains(response, 'alt="None"')
                self.assertContains(response, f'src="{table.cover_url}" alt=""')
