from dal import autocomplete
from django.db.models import Q, Case, When, Value, IntegerField
from django.db.models.functions import Lower
from django.http import JsonResponse

from webapp.forms import USER_SEARCH_MIN_LENGTH
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


#: Maximum number of users returned by user_search_view.
USER_SEARCH_LIMIT = 12


def search_user_profiles(query):
    """Users matching `query`, for the user picker.

    Every word must match the nickname, or the first/last name of users who
    chose to show their full name. A whole email address matches exactly:
    partial emails never match, so addresses can't be guessed piece by piece.
    """
    query = query.strip()
    if len(query) < USER_SEARCH_MIN_LENGTH:
        return UserProfile.objects.none()

    public_name = Q(show_full_name=True)
    words = Q()
    for word in query.split():
        words &= Q(nickname__icontains=word) | (public_name & (
            Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word)))

    return (UserProfile.objects
            .filter(user__is_active=True)
            .filter(words | Q(user__email__iexact=query))
            .select_related('user')
            .annotate(rank=Case(
                When(nickname__iexact=query, then=Value(0)),
                When(nickname__istartswith=query, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ))
            .order_by('rank', Lower('nickname'))[:USER_SEARCH_LIMIT])


def user_search_view(request):
    """JSON search used by the user picker widget (UserPickerWidget)."""
    if not request.user.is_authenticated:
        return JsonResponse({'results': []}, status=403)
    query = request.GET.get('q', '').strip()
    return JsonResponse({'results': [
        {
            'id': profile.pk,
            'nickname': profile.nickname,
            'full_name': profile.user.get_full_name() if profile.show_full_name else '',
            'avatar_url': profile.avatar_url,
            'email_match': profile.user.email.lower() == query.lower(),
        }
        for profile in search_user_profiles(query)
    ]})


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
