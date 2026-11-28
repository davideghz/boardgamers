"""Profiles and expected refusals shared by the `LocationAccess` tests of tables and events."""
import datetime

from django.utils import timezone

from webapp.factories import LocationFactory, SuperUserProfileFactory, UserProfileFactory
from webapp.models import Location, LocationAccess, Member, Membership

ANYONE, MEMBERS, MANAGERS = Location.PERM_ANYONE, Location.PERM_MEMBERS_ONLY, Location.PERM_MANAGERS_ONLY
LOGIN, MEMBERS_ONLY = LocationAccess.LOGIN, LocationAccess.MEMBERS_ONLY
PENDING, MANAGERS_ONLY = LocationAccess.MEMBERSHIP_PENDING, LocationAccess.MANAGERS_ONLY

# The refusal reason for each profile under each permission; None means allowed.
EXPECTED = {
    ANYONE: {
        'anonymous': LOGIN, 'outsider': None, 'pending': None, 'member': None,
        'expired': None, 'manager': None, 'creator': None, 'superuser': None,
    },
    MEMBERS: {
        'anonymous': MEMBERS_ONLY, 'outsider': MEMBERS_ONLY, 'pending': PENDING, 'member': None,
        'expired': MEMBERS_ONLY, 'manager': None, 'creator': None, 'superuser': None,
    },
    MANAGERS: {
        'anonymous': MANAGERS_ONLY, 'outsider': MANAGERS_ONLY, 'pending': MANAGERS_ONLY,
        'member': MANAGERS_ONLY, 'expired': MANAGERS_ONLY, 'manager': None, 'creator': None,
        'superuser': None,
    },
}


def add_membership(location, profile, status, **dates):
    member, _ = Member.objects.get_or_create(
        location=location, user_profile=profile, defaults={'first_name': 'A', 'last_name': 'B'})
    return Membership.objects.create(member=member, status=status, **dates)


class AccessMatrixMixin:
    """One location and a profile for each relation to it."""

    @classmethod
    def setUpTestData(cls):
        cls.location = LocationFactory(creator=UserProfileFactory())
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        cls.profiles = {
            'anonymous': None,
            'outsider': UserProfileFactory(),
            'pending': UserProfileFactory(),
            'member': UserProfileFactory(),
            'expired': UserProfileFactory(),
            'manager': UserProfileFactory(),
            'creator': cls.location.creator,
            'superuser': SuperUserProfileFactory(),
        }
        cls.location.managers.add(cls.profiles['manager'])
        add_membership(cls.location, cls.profiles['pending'], Membership.PENDING)
        add_membership(cls.location, cls.profiles['member'], Membership.ACTIVE)
        # Still marked active, but its period is over.
        add_membership(cls.location, cls.profiles['expired'], Membership.ACTIVE, end_date=yesterday)

    def assert_matrix(self, permission_field, access_method, permissions):
        for permission in permissions:
            setattr(self.location, permission_field, permission)
            for name, profile in self.profiles.items():
                with self.subTest(permission=permission, profile=name):
                    access = getattr(self.location, access_method)(profile)
                    expected = EXPECTED[permission][name]
                    self.assertEqual(access.reason, expected)
                    self.assertEqual(access.allowed, expected is None)
