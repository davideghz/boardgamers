"""TailwindForm must not validate inside __init__: subclasses restrict their
fields (querysets, required, ...) after super().__init__(), and validation has
to see those restrictions."""
from django.test import TestCase

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.forms import (
    _TW_INPUT, _TW_INPUT_ERR, EventTableForm, LocationGameForm, PhysicalTableForm, TableForm,
)
from webapp.models import Event, LocationGame, Member, PhysicalTable, PlayArea


class EventScopedFieldsTest(TestCase):
    def setUp(self):
        self.event = Event.objects.create(name='Con')
        self.other_event = Event.objects.create(name='Other con')
        self.foreign_area = PlayArea.objects.create(event=self.other_event, name='Sala B')

    def test_event_table_form_rejects_a_play_area_of_another_event(self):
        form = EventTableForm(data={'play_area': self.foreign_area.pk}, event=self.event)

        self.assertFalse(form.is_valid())
        self.assertIn('play_area', form.errors)

    def test_physical_table_form_rejects_a_play_area_of_another_event(self):
        form = PhysicalTableForm(
            data={'name': 'T1', 'play_area': self.foreign_area.pk}, event=self.event)

        self.assertFalse(form.is_valid())
        self.assertIn('play_area', form.errors)

    def test_physical_table_form_rejects_a_duplicate_name(self):
        PhysicalTable.objects.create(event=self.event, name='T1')

        form = PhysicalTableForm(data={'name': 'T1'}, event=self.event)

        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)


class LocationGameFormOwnerTest(TestCase):
    def test_rejects_a_member_of_another_location(self):
        location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        other = LocationFactory(creator=UserProfileFactory())
        outsider = Member.objects.create(location=other, first_name='A', last_name='B')

        form = LocationGameForm(data={
            'game': GameFactory().pk,
            'ownership': LocationGame.OWNED_BY_MEMBER,
            'owner_member': outsider.pk,
            'physical_location': LocationGame.AT_ASSOCIATION,
        }, location=location)

        self.assertFalse(form.is_valid())
        self.assertIn('owner_member', form.errors)


class ErrorStyleTest(TestCase):
    def test_only_fields_with_errors_get_the_error_style(self):
        form = TableForm(data={'title': 'x', 'time': '20:30'})
        form.is_valid()

        self.assertIn('title', form.errors)
        self.assertEqual(form.fields['title'].widget.attrs['class'], _TW_INPUT_ERR)
        self.assertEqual(form.fields['time'].widget.attrs['class'], _TW_INPUT)
        self.assertTrue(form.fields['description'].widget.attrs['class'].startswith(_TW_INPUT_ERR))
