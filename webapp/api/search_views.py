"""JSON searches behind the search pickers (forms.SearchPickerWidget) and the
location filter modal. Each result carries `id`, `title`, `subtitle` and
`image_url`, the fields static/js/search_picker.js renders."""
from django.conf import settings
from django.db.models import Q, Case, When, Value, IntegerField, Exists, OuterRef
from django.db.models.functions import Lower
from django.http import JsonResponse
from django.shortcuts import get_object_or_404

from webapp.forms import USER_SEARCH_MIN_LENGTH
from webapp.models import FavoriteUser, Location, UserProfile, Member

#: Maximum number of results returned by every search.
SEARCH_LIMIT = 12

#: Characters to type before the location search runs.
LOCATION_SEARCH_MIN_LENGTH = 2


def search_user_profiles(query, owner=None, excluded=()):
    """Users matching `query`, for the user picker.

    Every word must match the nickname, or the first/last name of users who
    chose to show their full name. A whole email address matches exactly:
    partial emails never match, so addresses can't be guessed piece by piece.
    The favorites of `owner` come right after an exact nickname match; the
    `excluded` ids (e.g. players already at the table) are left out.
    """
    query = query.strip()
    if len(query) < USER_SEARCH_MIN_LENGTH:
        return UserProfile.objects.none()

    public_name = Q(show_full_name=True)
    words = Q()
    for word in query.split():
        words &= Q(nickname__icontains=word) | (public_name & (
            Q(user__first_name__icontains=word) | Q(user__last_name__icontains=word)))

    is_favorite = Exists(FavoriteUser.objects.filter(owner=owner, favorite=OuterRef('pk')))
    return (UserProfile.objects
            .filter(user__is_active=True)
            .filter(words | Q(user__email__iexact=query))
            .exclude(pk__in=excluded)
            .select_related('user')
            .annotate(rank=Case(
                When(nickname__iexact=query, then=Value(0)),
                When(is_favorite, then=Value(1)),
                When(nickname__istartswith=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            ))
            .order_by('rank', Lower('nickname'))[:SEARCH_LIMIT])


def favorite_user_profiles(owner):
    """The favorite users of `owner`, by nickname: the picker's quick picks."""
    return (UserProfile.objects
            .filter(favorited_by__owner=owner, user__is_active=True)
            .select_related('user')
            .order_by(Lower('nickname')))


def user_profile_result(profile):
    return {
        'id': profile.pk,
        'title': profile.nickname,
        'subtitle': profile.user.get_full_name() if profile.show_full_name else '',
        'image_url': profile.avatar_url,
    }


def _excluded_ids(request):
    """Ids listed in ?exclude=1,2,3 (e.g. the players already at the table)."""
    return [int(pk) for pk in request.GET.get('exclude', '').split(',') if pk.strip().isdigit()]


def user_search_view(request):
    """Users for the user picker. The email is never returned: `badge` only
    flags an exact email match. With `favorites=1` it returns the current
    user's favorites instead of searching."""
    if not request.user.is_authenticated:
        return JsonResponse({'results': []}, status=403)
    owner = request.user.user_profile
    excluded = _excluded_ids(request)
    if request.GET.get('favorites'):
        return JsonResponse({'results': [
            user_profile_result(profile)
            for profile in favorite_user_profiles(owner).exclude(pk__in=excluded)
        ]})
    query = request.GET.get('q', '').strip()
    return JsonResponse({'results': [
        {**user_profile_result(profile), 'badge': profile.user.email.lower() == query.lower()}
        for profile in search_user_profiles(query, owner, excluded)
    ]})


def location_result(location):
    return {
        'id': location.pk,
        'slug': location.slug,
        'title': location.name,
        'subtitle': location.city or '',
        'image_url': location.cover_url,
    }


def location_search_view(request):
    """Locations by name or city. With `tables=1` only the ones whose
    tables are listed on the public tables page (the tables location filter)."""
    query = request.GET.get('q', '').strip()
    if len(query) < LOCATION_SEARCH_MIN_LENGTH:
        return JsonResponse({'results': []})
    locations = Location.objects.all()
    if request.GET.get('tables'):
        locations = locations.filter(show_tables_in_homepage=True)
    locations = (locations
                 .filter(Q(name__icontains=query) | Q(city__icontains=query))
                 .annotate(rank=Case(When(name__istartswith=query, then=Value(0)),
                                     default=Value(1), output_field=IntegerField()))
                 .order_by('rank', Lower('name'))[:SEARCH_LIMIT])
    return JsonResponse({'results': [location_result(location) for location in locations]})


def member_result(member):
    profile = member.user_profile
    return {
        'id': member.pk,
        'title': f"{member.first_name} {member.last_name}",
        'subtitle': profile.nickname if profile else member.email,
        'image_url': profile.avatar_url if profile else settings.STATIC_URL + settings.DEFAULT_AVATAR_URL,
    }


def member_search_view(request, slug):
    """Members of a location, for its managers only."""
    location = get_object_or_404(Location, slug=slug)
    if not request.user.is_authenticated:
        return JsonResponse({'results': []}, status=403)
    profile = request.user.user_profile
    if location.creator != profile and not location.managers.filter(pk=profile.pk).exists():
        return JsonResponse({'results': []}, status=403)
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'results': []})
    words = Q()
    for word in query.split():
        words &= (Q(first_name__icontains=word) | Q(last_name__icontains=word)
                  | Q(user_profile__nickname__icontains=word))
    members = (location.members.filter(words)
               .select_related('user_profile')
               .order_by(Lower('last_name'), Lower('first_name'))[:SEARCH_LIMIT])
    return JsonResponse({'results': [member_result(member) for member in members]})
