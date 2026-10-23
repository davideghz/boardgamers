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
