from django.test import SimpleTestCase

from webapp.forms import EventTableForm, TableForm


class TableFormRequiresDateAndTimeTest(SimpleTestCase):
    """An empty date/time used to reach Table.save() as None and crash lifecycle_phase()."""

    def test_table_form(self):
        form = TableForm(data={'date': '', 'time': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)
        self.assertIn('time', form.errors)

    def test_event_table_form(self):
        form = EventTableForm(data={'date': '', 'time': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('date', form.errors)
        self.assertIn('time', form.errors)


class TableFormBlankPlayersTest(SimpleTestCase):
    """A blank min/max players on a limited table used to reach Table.save() as
    None and violate the NOT NULL constraint."""

    def _assert_players_required(self, form_class):
        form = form_class(data={'min_players': '', 'max_players': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('min_players', form.errors)
        self.assertIn('max_players', form.errors)

    def test_table_form(self):
        self._assert_players_required(TableForm)

    def test_event_table_form(self):
        self._assert_players_required(EventTableForm)

    def test_unlimited_seats_falls_back_to_defaults(self):
        form = TableForm(data={'min_players': '', 'max_players': '', 'unlimited_seats': 'on'})
        form.is_valid()
        self.assertNotIn('min_players', form.errors)
        self.assertNotIn('max_players', form.errors)
        self.assertEqual(form.cleaned_data['min_players'], 2)
        self.assertEqual(form.cleaned_data['max_players'], 5)
