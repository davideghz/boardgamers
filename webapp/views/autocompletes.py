from dal import autocomplete
from django.db.models import Q, Case, When, Value, IntegerField
from django.db.models.functions import Lower

from webapp.models import Game, Location, UserProfile, Member


class LocationAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return Location.objects.none()

        qs = Location.objects.all()

        is_public_location = self.forwarded.get('is_public_location', None)

        if is_public_location:
            qs = qs.filter(is_public=True)
        else:
            qs = qs.filter(creator=self.request.user.user_profile)

        if self.q:
            qs = qs.filter(name__istartswith=self.q)

        return qs


class GamesAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return Game.objects.none()

        qs = Game.objects.all()
        if self.q:
            qs = qs.filter(name__istartswith=self.q)
        return qs


class UserProfileAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return UserProfile.objects.none()

        qs = UserProfile.objects.all()

        if self.q:
            qs = qs.filter(nickname__istartswith=self.q)

        return qs


class MemberAutocomplete(autocomplete.Select2QuerySetView):
    """Autocomplete for Members scoped to a specific location (by slug in URL)."""

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Member.objects.none()

        location_slug = self.kwargs.get('location_slug')
        qs = Member.objects.filter(location__slug=location_slug).order_by('last_name', 'first_name')

        if self.q:
            qs = qs.filter(
                Q(first_name__icontains=self.q) | Q(last_name__icontains=self.q)
            )

        return qs
