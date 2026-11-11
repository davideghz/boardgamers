from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

from django.db import IntegrityError, connections, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from webapp.factories import GameFactory, LocationFactory, UserProfileFactory
from webapp.models import LocationGame, LocationGameLoan, Member, Membership
from webapp.services.game_loans import GameLoanError, create_game_loan
from webapp.services.games import merge_games


def make_member(location, profile=None, *, start=None, end=None, status=Membership.ACTIVE):
    today = timezone.localdate()
    member = Member.objects.create(
        location=location, user_profile=profile, first_name='Name', last_name='From registry',
    )
    Membership.objects.create(
        member=member, status=status,
        start_date=start or today - timedelta(days=7), end_date=end or today + timedelta(days=30),
    )
    return member


class LocationGameLoanTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = UserProfileFactory()
        cls.borrower = UserProfileFactory(nickname='loan-borrower')
        cls.viewer = UserProfileFactory()
        cls.location = LocationFactory(creator=cls.manager, enable_game_loans=True)
        cls.game = LocationGame.objects.create(location=cls.location, game=GameFactory())
        cls.member = make_member(cls.location, cls.borrower)
        cls.other_location = LocationFactory(creator=cls.manager, enable_game_loans=True)
        cls.other_member = make_member(cls.other_location, cls.viewer)

    def url(self, name, **kwargs):
        return reverse(name, kwargs={'slug': self.location.slug, **kwargs})

    def game_url(self, name):
        return self.url(name, game_uuid=self.game.uuid)

    def create_loan(self, member=None):
        return create_game_loan(self.location, self.game, self.manager, member=member or self.member)

    def enable_self_service(self):
        self.location.enable_member_game_loans = True
        self.location.save(update_fields=['enable_member_game_loans'])

    def test_manager_checkout_for_member_without_account(self):
        member = make_member(self.location)
        staff = UserProfileFactory()
        self.location.managers.add(staff)
        self.client.force_login(staff.user)
        url = self.game_url('location-game-loan-create')
        today = timezone.localdate()
        response = self.client.get(url)
        self.assertEqual(response.context['form']['due_date'].value(), today + timedelta(days=7))
        self.assertContains(response, '?active=1')
        due_date = today + timedelta(days=10)
        self.assertRedirects(self.client.post(url, {'member': member.pk, 'due_date': due_date}),
                             self.game_url('location-game-detail'))
        loan = LocationGameLoan.objects.get()
        self.assertEqual((loan.member, loan.loaned_by, loan.due_date), (member, staff, due_date))

    def test_checkout_rejects_foreign_member_and_past_due_date(self):
        self.client.force_login(self.manager.user)
        url = self.game_url('location-game-loan-create')
        today = timezone.localdate()
        response = self.client.post(url, {'member': self.other_member.pk, 'due_date': today})
        self.assertTrue(response.context['form']['member'].errors)
        response = self.client.post(url, {'member': self.member.pk, 'due_date': today - timedelta(days=1)})
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertFalse(LocationGameLoan.objects.exists())

    def test_member_picker_filters_for_valid_memberships(self):
        expired = make_member(self.location, end=timezone.localdate() - timedelta(days=1))
        url = self.url('member-search')
        self.client.force_login(self.borrower.user)
        self.assertEqual(self.client.get(url, {'q': 'registry', 'active': 1}).status_code, 403)
        self.client.force_login(self.manager.user)
        result = self.client.get(url, {'q': 'registry', 'active': 1}).json()['results']
        self.assertEqual([member['id'] for member in result], [self.member.pk])
        result = self.client.get(url, {'q': 'registry'}).json()['results']
        self.assertCountEqual([member['id'] for member in result], [self.member.pk, expired.pk])

    def test_catalogue_only_exposes_details_to_active_members(self):
        self.create_loan()
        self.location.show_game_loan_borrower = True
        self.location.save(update_fields=['show_game_loan_borrower'])
        url = self.url('location-games')
        for viewer in (None, self.viewer):
            with self.subTest(viewer=viewer):
                if viewer:
                    self.client.force_login(viewer.user)
                response = self.client.get(url)
                entry = response.context['location_games'][0]
                self.assertTrue(entry.is_on_loan)
                self.assertFalse(hasattr(entry, 'loan_due_date'))
                self.assertFalse(hasattr(entry, 'borrower_nickname'))
                self.assertNotContains(response, 'loan-borrower')
        self.client.force_login(self.borrower.user)
        response = self.client.get(url)
        self.assertEqual(response.context['location_games'][0].borrower_nickname, 'loan-borrower')
        self.assertNotContains(response, self.member.full_name)
        self.assertEqual(response.context['location_games'][0].loan_due_date, timezone.localdate() + timedelta(days=7))
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_private_catalogue_shows_dates_to_members_without_sharing_nickname(self):
        self.create_loan()
        self.location.enable_public_games = False
        self.location.save(update_fields=['enable_public_games'])
        url = self.url('location-games')
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.viewer.user)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.borrower.user)
        response = self.client.get(url)
        self.assertContains(self.client.get(self.url('location-detail')), url)
        self.assertTrue(response.context['location_games'][0].loan_due_date)
        self.assertFalse(hasattr(response.context['location_games'][0], 'borrower_nickname'))

    def test_self_service_uses_signed_in_member_and_configured_duration(self):
        self.enable_self_service()
        self.location.game_loan_days = 14
        self.location.save(update_fields=['game_loan_days'])
        self.client.force_login(self.borrower.user)
        url = self.game_url('location-game-loan-borrow')
        self.assertContains(self.client.get(self.url('location-games')), url)
        due_date = timezone.localdate() + timedelta(days=14)
        self.assertEqual(self.client.get(url).context['due_date'], due_date)
        self.assertFalse(LocationGameLoan.objects.exists())
        self.assertRedirects(self.client.post(url, {'member': self.other_member.pk, 'due_date': '2037-01-01'}),
                             self.url('location-games'))
        loan = LocationGameLoan.objects.get()
        self.assertEqual((loan.member, loan.loaned_by, loan.due_date), (self.member, self.borrower, due_date))
        self.client.post(url)
        self.assertEqual(LocationGameLoan.objects.count(), 1)

    def test_self_service_requires_active_membership_and_both_settings(self):
        url = self.game_url('location-game-loan-borrow')
        self.client.force_login(self.borrower.user)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.enable_self_service()
        self.client.force_login(self.viewer.user)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.borrower.user)
        membership = self.member.memberships.get()
        today = timezone.localdate()
        for update in ({'end_date': today - timedelta(days=1)}, {'start_date': today + timedelta(days=1)},
                       {'status': Membership.PENDING}):
            with self.subTest(update=update):
                self.member.memberships.update(**{
                    'start_date': membership.start_date, 'end_date': membership.end_date,
                    'status': membership.status, **update,
                })
                self.assertEqual(self.client.post(url).status_code, 403)
        self.member.memberships.update(status=Membership.ACTIVE)
        self.location.enable_game_loans = False
        self.location.save(update_fields=['enable_game_loans'])
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertFalse(LocationGameLoan.objects.exists())

    def test_only_site_owned_games_kept_on_site_can_be_borrowed(self):
        self.enable_self_service()
        self.client.force_login(self.borrower.user)
        url = self.game_url('location-game-loan-borrow')
        for ownership, physical_location in ((LocationGame.OWNED_BY_MEMBER, LocationGame.AT_ASSOCIATION),
                                             (LocationGame.OWNED_BY_LOCATION, LocationGame.AT_HOME)):
            with self.subTest(ownership=ownership, physical_location=physical_location):
                LocationGame.objects.filter(pk=self.game.pk).update(
                    ownership=ownership, physical_location=physical_location,
                )
                self.assertNotContains(self.client.get(self.url('location-games')), url)
                self.client.post(url)
                self.assertFalse(LocationGameLoan.objects.exists())

    def test_return_is_manager_only_and_idempotent_even_after_disabling_loans(self):
        loan = self.create_loan()
        self.location.enable_game_loans = False
        self.location.save(update_fields=['enable_game_loans'])
        url = self.url('location-game-loan-return', loan_uuid=loan.uuid)
        self.client.force_login(self.borrower.user)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.client.force_login(self.manager.user)
        wrong_location_url = reverse('location-game-loan-return', args=[self.other_location.slug, loan.uuid])
        self.assertEqual(self.client.post(wrong_location_url).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertRedirects(self.client.post(url), self.url('location-manage-game-loans'))
        loan.refresh_from_db()
        self.assertEqual(loan.returned_by, self.manager)
        self.assertIsNotNone(loan.returned_at)
        returned_at = loan.returned_at
        self.client.post(url)
        loan.refresh_from_db()
        self.assertEqual(loan.returned_at, returned_at)
        self.assertFalse(self.client.get(self.url('location-games')).context['location_games'][0].is_on_loan)
        response = self.client.get(self.url('location-manage-game-loans'), {'status': 'returned'})
        self.assertEqual(list(response.context['page_obj']), [loan])

    def test_overdue_loan_keeps_game_unavailable(self):
        loan = self.create_loan()
        LocationGameLoan.objects.filter(pk=loan.pk).update(due_date=timezone.localdate() - timedelta(days=1))
        self.client.force_login(self.manager.user)
        response = self.client.get(self.url('location-manage-game-loans'), {'status': 'overdue'})
        self.assertTrue(response.context['page_obj'][0].is_overdue)
        with self.assertRaises(GameLoanError):
            self.create_loan()
        with self.assertRaises(IntegrityError), transaction.atomic():
            LocationGameLoan.objects.create(location_game=self.game, member=self.member, due_date=timezone.localdate())

    def test_settings_require_manager_and_validate_duration(self):
        url = self.url('location-manage-game-loans')
        data = {'enable_game_loans': 'on', 'enable_member_game_loans': 'on', 'game_loan_days': 0}
        self.client.force_login(self.borrower.user)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.manager.user)
        self.assertTrue(self.client.post(url, data).context['form']['game_loan_days'].errors)
        data['game_loan_days'] = 12
        self.assertRedirects(self.client.post(url, data), url)
        self.location.refresh_from_db()
        self.assertTrue(self.location.enable_member_game_loans)
        self.assertEqual(self.location.game_loan_days, 12)

    def test_borrow_requires_csrf(self):
        self.enable_self_service()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.borrower.user)
        self.assertEqual(client.post(self.game_url('location-game-loan-borrow')).status_code, 403)
        self.assertFalse(LocationGameLoan.objects.exists())

    def test_delete_and_merge_cannot_discard_loan_history(self):
        loan = self.create_loan()
        self.client.force_login(self.manager.user)
        self.client.post(self.url('location-game-loan-return', loan_uuid=loan.uuid))
        self.assertRedirects(self.client.post(self.game_url('location-delete-game')),
                             self.game_url('location-game-detail'))
        keeper = GameFactory()
        LocationGame.objects.create(location=self.location, game=keeper)
        with self.assertRaises(ProtectedError):
            merge_games(keeper, self.game.game, {})
        self.assertTrue(LocationGameLoan.objects.filter(pk=loan.pk, location_game=self.game).exists())


class ConcurrentGameLoanTest(TransactionTestCase):
    def test_manager_and_member_cannot_both_check_out_same_game(self):
        manager = UserProfileFactory()
        borrower = UserProfileFactory()
        location = LocationFactory(creator=manager, enable_game_loans=True, enable_member_game_loans=True)
        game = LocationGame.objects.create(location=location, game=GameFactory())
        make_member(location, borrower)
        staff_borrower = make_member(location)
        start = Barrier(2, timeout=10)

        def checkout(actor, member=None):
            try:
                start.wait()
                create_game_loan(location, game, actor, member=member)
            except GameLoanError:
                return False
            finally:
                connections.close_all()
            return True

        with ThreadPoolExecutor(max_workers=2) as executor:
            manager_result = executor.submit(checkout, manager, staff_borrower)
            member_result = executor.submit(checkout, borrower)
            self.assertCountEqual([manager_result.result(), member_result.result()], [True, False])
        self.assertEqual(LocationGameLoan.objects.count(), 1)
