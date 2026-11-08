import datetime

from django.test import TestCase

from webapp.factories import LocationFactory, UserProfileFactory
from webapp.models import Location, Table


class LongSlugTest(TestCase):
    """The random suffix pushed long slugs past max_length=144 and Postgres raised DataError."""

    def make_table(self, title):
        return Table.objects.create(
            title=title, author=UserProfileFactory(), location=LocationFactory(),
            date=datetime.date(2026, 11, 10), time=datetime.time(20, 30),
        )

    def test_same_long_title_twice(self):
        title = 'a' * 144
        first = self.make_table(title)
        second = self.make_table(title)
        self.assertEqual(first.slug, title)
        self.assertEqual(len(second.slug), 144)
        self.assertTrue(second.slug.startswith('a' * 137 + '-'))

    def test_truncation_drops_trailing_hyphen(self):
        # The cut for the suffix falls right after a word: no double hyphen.
        title = 'b' * 136 + ' ' + 'c' * 7
        self.make_table(title)
        second = self.make_table(title)
        self.assertNotIn('--', second.slug)
        self.assertLessEqual(len(second.slug), 144)

    def test_location_name_longer_than_slug(self):
        location = LocationFactory(name='d' * 200)
        self.assertEqual(location.slug, 'd' * 144)
        Location.objects.get(pk=location.pk)
