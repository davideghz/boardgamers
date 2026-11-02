import datetime

from django.test import TestCase
from django.urls import reverse

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Table


class EmptySlugTest(TestCase):
    """A title of only emoji slugified to '', saved an empty slug and broke reverse('table-detail')."""

    def make_table(self, title):
        return Table.objects.create(
            title=title, author=UserProfileFactory(), location=LocationFactory(),
            date=datetime.date(2026, 11, 10), time=datetime.time(20, 30),
        )

    def test_emoji_title_gets_fallback_slug(self):
        first = self.make_table('🎲🎲')
        second = self.make_table('🎲')
        self.assertEqual(first.slug, 'table')
        self.assertTrue(second.slug.startswith('table-'))
        reverse('table-detail', kwargs={'slug': first.slug})

    def test_existing_empty_slug_is_regenerated_on_save(self):
        table = self.make_table('🎲')
        Table.objects.filter(pk=table.pk).update(slug='')
        table.refresh_from_db()
        table.save()
        self.assertEqual(table.slug, 'table')
