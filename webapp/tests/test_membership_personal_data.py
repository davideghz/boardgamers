import datetime
from importlib import import_module
from unittest import mock

from django.core.exceptions import ValidationError
from django.test import TestCase, SimpleTestCase, Client
from django.urls import reverse

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import Member, Membership


PERSONAL_DATA = {
    'fiscal_code': 'RSSMRA85M01H501Z',
    'birth_date': '1985-08-01',
    'birth_place': 'Roma',
    'nationality': 'Italiana',
    'address': 'Via Roma 1',
    'zip_code': '00100',
    'city': 'Roma',
    'province': 'RM',
}


class FiscalCodeValidationTest(TestCase):
    """The fiscal code is validated softly: shape only, and only when filled."""

    def setUp(self):
        self.location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)

    def _member(self, fiscal_code):
        return Member(location=self.location, first_name='Mario', last_name='Rossi',
                      fiscal_code=fiscal_code)

    def test_blank_fiscal_code_is_allowed(self):
        self._member('').full_clean(exclude=['uuid'])

    def test_valid_fiscal_code_is_allowed(self):
        self._member('RSSMRA85M01H501Z').full_clean(exclude=['uuid'])

    def test_omocodia_fiscal_code_is_allowed(self):
        # Homocode: digits replaced by letters keep the code valid.
        self._member('RSSMRA85M01H50NZ').full_clean(exclude=['uuid'])

    def test_lowercase_is_accepted_and_stored_uppercase(self):
        member = self._member('rssmra85m01h501z')
        member.full_clean(exclude=['uuid'])
        member.save()
        member.refresh_from_db()
        self.assertEqual(member.fiscal_code, 'RSSMRA85M01H501Z')

    def test_malformed_fiscal_code_is_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            self._member('NOT-A-CODE-12345').full_clean(exclude=['uuid'])
        self.assertIn('fiscal_code', ctx.exception.error_dict)

    def test_province_is_stored_uppercase(self):
        member = self._member('')
        member.province = 'rm'
        member.save()
        member.refresh_from_db()
        self.assertEqual(member.province, 'RM')


class PersonalDataHelpersTest(TestCase):
    def setUp(self):
        self.user_profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)

    def test_has_complete_personal_data(self):
        member = Member.objects.create(
            location=self.location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi',
        )
        self.assertFalse(member.has_complete_personal_data)

        for field, value in PERSONAL_DATA.items():
            setattr(member, field, value)
        member.save()
        self.assertTrue(member.has_complete_personal_data)

    def test_personal_data_from_latest_copies_the_most_recent_record(self):
        other_location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        Member.objects.create(
            location=other_location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi', city='Milano',
            **{k: v for k, v in PERSONAL_DATA.items() if k not in ('birth_date', 'city')},
        )
        data = Member.personal_data_from_latest(self.user_profile)
        self.assertEqual(data['fiscal_code'], PERSONAL_DATA['fiscal_code'])
        self.assertEqual(data['city'], 'Milano')

    def test_personal_data_from_latest_without_records(self):
        self.assertEqual(Member.personal_data_from_latest(self.user_profile), {})


class RequestMembershipPersonalDataTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        self.url = reverse('location-request-membership', kwargs={'slug': self.location.slug})
        self.client.force_login(self.user_profile.user)

    def _payload(self, **overrides):
        payload = {'first_name': 'Mario', 'last_name': 'Rossi', 'email': 'mario@example.com'}
        payload.update(PERSONAL_DATA)
        payload.update(overrides)
        return payload

    def test_request_stores_the_personal_data(self):
        response = self.client.post(self.url, self._payload(notes='Ciao'))
        self.assertEqual(response.status_code, 302)

        member = Member.objects.get(location=self.location, user_profile=self.user_profile)
        self.assertEqual(member.fiscal_code, PERSONAL_DATA['fiscal_code'])
        self.assertEqual(member.birth_date, datetime.date(1985, 8, 1))
        self.assertEqual(member.province, 'RM')
        self.assertTrue(member.has_complete_personal_data)

        membership = member.memberships.get()
        self.assertEqual(membership.status, Membership.PENDING)
        self.assertEqual(membership.notes, 'Ciao')

    def test_invalid_fiscal_code_does_not_create_a_membership(self):
        response = self.client.post(self.url, self._payload(fiscal_code='XX'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Member.objects.filter(location=self.location).exists())
        self.assertFalse(Membership.objects.exists())

    def test_form_is_prefilled_from_another_location(self):
        other_location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        Member.objects.create(
            location=other_location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi', **PERSONAL_DATA,
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form']['fiscal_code'].value(), PERSONAL_DATA['fiscal_code'])
        self.assertEqual(response.context['form']['city'].value(), 'Roma')

    def test_a_rejected_member_can_request_again_and_update_their_data(self):
        member = Member.objects.create(
            location=self.location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi', city='Milano',
        )
        Membership.objects.create(member=member, status=Membership.REJECTED)

        response = self.client.post(self.url, self._payload())
        self.assertEqual(response.status_code, 302)

        member.refresh_from_db()
        self.assertEqual(member.city, 'Roma')
        self.assertEqual(Member.objects.filter(location=self.location).count(), 1)
        self.assertTrue(member.memberships.filter(status=Membership.PENDING).exists())


class MemberDataEditTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user_profile = UserProfileFactory()
        self.location = LocationFactory(creator=UserProfileFactory(), enable_membership=True)
        self.member = Member.objects.create(
            location=self.location, user_profile=self.user_profile,
            first_name='Mario', last_name='Rossi',
        )
        self.membership = Membership.objects.create(member=self.member, status=Membership.PENDING)
        self.url = reverse('account-member-data', kwargs={'member_uuid': self.member.uuid})

    def test_member_can_edit_their_own_data(self):
        self.client.force_login(self.user_profile.user)
        response = self.client.post(self.url, {
            'first_name': 'Mario', 'last_name': 'Rossi', 'email': 'mario@example.com',
            **PERSONAL_DATA,
        })
        self.assertRedirects(response, reverse('account-memberships'))
        self.member.refresh_from_db()
        self.assertTrue(self.member.has_complete_personal_data)

    def test_form_page_renders_the_personal_data_block(self):
        self.client.force_login(self.user_profile.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="personal-data-body"')

    def test_memberships_page_links_to_the_form(self):
        self.client.force_login(self.user_profile.user)
        response = self.client.get(reverse('account-memberships'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)
        self.assertContains(response, 'Dati da completare')

    def test_another_user_cannot_reach_the_form(self):
        self.client.force_login(UserProfileFactory().user)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_data_is_not_editable_once_the_membership_is_over(self):
        self.membership.status = Membership.REJECTED
        self.membership.save()
        self.client.force_login(self.user_profile.user)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_anonymous_user_is_redirected_to_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)


class MembersCSVTest(TestCase):
    def test_csv_contains_the_personal_data_columns(self):
        owner = UserProfileFactory()
        location = LocationFactory(creator=owner, enable_membership=True)
        Member.objects.create(
            location=location, first_name='Mario', last_name='Rossi', **PERSONAL_DATA,
        )
        client = Client()
        client.force_login(owner.user)
        response = client.get(reverse('location-members-csv', kwargs={'slug': location.slug}))

        self.assertEqual(response.status_code, 200)
        body = response.content.decode('utf-8')
        self.assertIn(PERSONAL_DATA['fiscal_code'], body)
        self.assertIn('1985-08-01', body)
        self.assertIn('Via Roma 1', body)


class ManageMemberDetailRenderTest(TestCase):
    def test_manager_sees_the_personal_data_block(self):
        owner = UserProfileFactory()
        location = LocationFactory(creator=owner, enable_membership=True)
        member = Member.objects.create(location=location, first_name='Mario', last_name='Rossi')

        client = Client()
        client.force_login(owner.user)
        response = client.get(reverse('location-member-detail', kwargs={
            'slug': location.slug, 'member_uuid': member.uuid,
        }))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="personal-data-body"')


class FiscalCodeMigrationGuardTest(SimpleTestCase):
    """
    The 0068 data migration shrinks the column from 50 to 16 characters. It
    must normalize what fits and refuse rather than drop what does not.
    """

    migration = import_module('webapp.migrations.0068_member_fiscal_code_and_personal_data')

    def _apps(self, values):
        members = [mock.Mock(id=index, fiscal_code=value)
                   for index, value in enumerate(values, start=1)]
        manager = mock.Mock()
        manager.exclude.return_value.only.return_value.iterator.return_value = iter(members)
        apps = mock.Mock()
        apps.get_model.return_value.objects = manager
        return apps, members

    def test_values_that_fit_are_normalized(self):
        apps, members = self._apps([' rssmra85m01h501z '])
        self.migration.normalize_fiscal_code(apps, None)
        self.assertEqual(members[0].fiscal_code, 'RSSMRA85M01H501Z')
        members[0].save.assert_called_once_with(update_fields=['fiscal_code'])

    def test_untouched_values_are_not_rewritten(self):
        apps, members = self._apps(['RSSMRA85M01H501Z'])
        self.migration.normalize_fiscal_code(apps, None)
        members[0].save.assert_not_called()

    def test_a_value_that_would_be_lost_stops_the_migration(self):
        apps, members = self._apps(['SOCIO-2024-000000123'])
        with self.assertRaises(RuntimeError) as ctx:
            self.migration.normalize_fiscal_code(apps, None)
        self.assertIn('SOCIO-2024-000000123', str(ctx.exception))
        members[0].save.assert_not_called()
