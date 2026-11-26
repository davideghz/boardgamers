from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils.translation import gettext as _, ngettext

from webapp.factories import UserProfileFactory, LocationFactory
from webapp.models import Member, Membership, MembershipDocument
from webapp.views.location_views import LocationManageMembersView

PAGE_SIZE = LocationManageMembersView.paginate_by


class MembersPaginationTest(TestCase):
    def setUp(self):
        self.manager = UserProfileFactory()
        self.location = LocationFactory()
        self.location.managers.add(self.manager)
        self.url = reverse('location-manage-members', kwargs={'slug': self.location.slug})
        self.client.force_login(self.manager.user)

    def _member(self, first_name, last_name, **kwargs):
        return Member.objects.create(
            location=self.location, first_name=first_name, last_name=last_name, **kwargs)

    def _bulk_members(self, count):
        Member.objects.bulk_create(
            Member(location=self.location, first_name='Player', last_name=f'A{i:03d}')
            for i in range(count))

    def test_members_are_split_in_pages(self):
        self._bulk_members(PAGE_SIZE + 5)

        response = self.client.get(self.url)
        self.assertTrue(response.context['is_paginated'])
        self.assertEqual(len(response.context['members']), PAGE_SIZE)
        self.assertEqual(response.context['paginator'].count, PAGE_SIZE + 5)
        self.assertContains(response, '?page=2')

        response = self.client.get(self.url, {'page': 2})
        self.assertEqual([m.last_name for m in response.context['members']],
                         [f'A{i:03d}' for i in range(PAGE_SIZE, PAGE_SIZE + 5)])

    def test_single_page_has_no_pagination(self):
        self._bulk_members(3)
        response = self.client.get(self.url)
        self.assertFalse(response.context['is_paginated'])
        self.assertNotContains(response, '?page=2')

    def test_search_covers_every_page_and_page_links_keep_it(self):
        self._bulk_members(PAGE_SIZE * 2)
        # Sorted after every A### member, so it would sit on the last page.
        self._member('Mario', 'Zeta')

        response = self.client.get(self.url, {'q': 'zeta'})
        self.assertEqual([m.last_name for m in response.context['members']], ['Zeta'])

        response = self.client.get(self.url, {'q': 'player'})
        self.assertEqual(response.context['paginator'].count, PAGE_SIZE * 2)
        self.assertContains(response, 'q=player&amp;page=2')
        # The count is the total of the filtered list, not of the page.
        total = PAGE_SIZE * 2
        self.assertContains(response, ngettext(
            '%(counter)s member found', '%(counter)s members found', total) % {'counter': total})

    def test_search_matches_every_word_across_fields(self):
        self._member('Mario', 'Rossi', email='mario@example.com', fiscal_code='RSSMRA80A01H501U',
                     phone_number='+393331234567')
        self._member('Mario', 'Bianchi')
        nickname = UserProfileFactory(nickname='meeple_king')
        self._member('Luca', 'Verdi', user_profile=nickname)

        def found(q):
            return [m.last_name for m in self.client.get(self.url, {'q': q}).context['members']]

        self.assertEqual(found('mario rossi'), ['Rossi'])
        self.assertEqual(found('Mario'), ['Bianchi', 'Rossi'])
        self.assertEqual(found('example.com'), ['Rossi'])
        self.assertEqual(found('rssmra'), ['Rossi'])
        self.assertEqual(found('3331234'), ['Rossi'])
        self.assertEqual(found('meeple'), ['Verdi'])

    def test_unsigned_filter_matches_needs_signed_document(self):
        MembershipDocument.objects.create(
            location=self.location, name='Modulo di adesione', file='membership-documents/modulo.pdf')
        today = date.today()
        pending = self._member('A', 'Pending')
        Membership.objects.create(member=pending, status=Membership.PENDING)
        signed = self._member('B', 'Signed')
        Membership.objects.create(member=signed, status=Membership.ACTIVE, signed_document=True,
                                  start_date=today, end_date=today + timedelta(days=30))
        active = self._member('C', 'Active')
        Membership.objects.create(member=active, status=Membership.ACTIVE,
                                  start_date=today, end_date=today + timedelta(days=30))
        # A later rejected request doesn't hide the active, signed membership.
        renewed = self._member('D', 'Renewed')
        Membership.objects.create(member=renewed, status=Membership.ACTIVE, signed_document=True,
                                  start_date=today, end_date=today + timedelta(days=30))
        Membership.objects.create(member=renewed, status=Membership.REJECTED)
        rejected = self._member('E', 'Rejected')
        Membership.objects.create(member=rejected, status=Membership.REJECTED)
        self._member('F', 'Nothing')

        response = self.client.get(self.url, {'unsigned': '1'})
        listed = [m.last_name for m in response.context['members']]
        expected = sorted(m.last_name for m in Member.objects.filter(location=self.location)
                          if m.needs_signed_document)
        self.assertEqual(listed, expected)
        self.assertEqual(listed, ['Active', 'Pending'])

    def test_unsigned_filter_is_kept_across_pages(self):
        MembershipDocument.objects.create(
            location=self.location, name='Modulo di adesione', file='membership-documents/modulo.pdf')
        self._bulk_members(PAGE_SIZE + 1)
        Membership.objects.bulk_create(
            Membership(member=m, status=Membership.PENDING) for m in Member.objects.all())

        response = self.client.get(self.url, {'unsigned': '1'})
        self.assertEqual(response.context['paginator'].count, PAGE_SIZE + 1)
        self.assertContains(response, 'unsigned=1&amp;page=2')

        response = self.client.get(self.url, {'unsigned': '1', 'page': 2})
        self.assertEqual(len(response.context['members']), 1)

    def test_unsigned_filter_is_ignored_without_documents(self):
        self._member('A', 'Pending')
        response = self.client.get(self.url, {'unsigned': '1'})
        self.assertFalse(response.context['only_unsigned'])
        self.assertEqual(len(response.context['members']), 1)

    def test_empty_states(self):
        self.assertContains(self.client.get(self.url), _('No members yet'))

        self._member('Mario', 'Rossi')
        response = self.client.get(self.url, {'q': 'nobody'})
        self.assertContains(response, _('No members found.'))
        self.assertNotContains(response, _('No members yet'))
