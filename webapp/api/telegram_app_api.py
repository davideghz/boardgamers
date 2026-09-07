"""JSON API backing the Telegram Mini App.

Every endpoint authenticates from the signed `initData` header — see
`telegram_miniapp_auth` — never from the Django session.
"""

from django.db.models import Prefetch
from django.http import JsonResponse
from django.utils import formats, timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from webapp.models import Location, Player, Table
from webapp.services.tables import TableActionError, join_table, leave_table
from webapp.views.decorators import telegram_miniapp_auth


def _serialize_table(table, joined_table_ids):
    players = [p.display_name for p in table.player_set.all()]
    return {
        'slug': table.slug,
        'title': table.title,
        'game': table.game.name if table.game else '',
        'date': table.date.isoformat(),
        # 'l j E' = weekday + day + month in the locale's long-date form
        # ("Venerdì 11 Settembre"); the client groups by `date`, not by this.
        'day_label': formats.date_format(table.date, 'l j E'),
        'time_label': table.time.strftime('%H:%M'),
        'players_count': table.total_players,
        'max_players': table.max_players,
        'seats_available': max(0, table.seats_available),
        'unlimited_seats': table.unlimited_seats,
        'players': players,
        'is_joined': table.id in joined_table_ids,
    }


@require_GET
@telegram_miniapp_auth
def bootstrap(request):
    """Everything the Mini App needs on open: who the viewer is, which location
    the link pointed at, and that location's upcoming tables."""
    slug = request.telegram_start_param
    if not slug:
        return JsonResponse({'error': 'no_location'}, status=400)

    location = Location.objects.filter(slug=slug).first()
    if not location:
        return JsonResponse({'error': 'unknown_location'}, status=404)

    profile = request.telegram_profile

    players_prefetch = Prefetch(
        'player_set',
        queryset=Player.objects.select_related(
            'user_profile', 'guest_profile', 'guest_profile__owner'),
    )
    # Filtering by location already excludes event tables: the
    # `table_location_xor_event` constraint means a table has one or the other.
    tables = (
        Table.objects
        .filter(
            location=location,
            date__gte=timezone.localdate(),
            status__in=Table.JOIN_LEAVE_STATUSES,
        )
        .select_related('game')
        .prefetch_related(players_prefetch)
        .order_by('date', 'time')
    )

    joined_table_ids = set()
    if profile:
        joined_table_ids = set(
            Player.objects
            .filter(user_profile=profile, table__in=tables)
            .values_list('table_id', flat=True)
        )

    return JsonResponse({
        'linked': profile is not None,
        'telegram_user': {
            'first_name': request.telegram_user.get('first_name', ''),
        },
        'profile': {'nickname': profile.nickname} if profile else None,
        'location': {
            'name': location.name,
            'slug': location.slug,
            'city': location.city or '',
            'cover_url': location.cover_url,
        },
        'tables': [_serialize_table(t, joined_table_ids) for t in tables],
    })


# ── Actions ───────────────────────────────────────────────────────────────────

def _resolve_table(slug):
    """The Mini App only ever operates on a location's tables. Event tables have
    their own sign-up flow on the website, and are not listed here — so a
    crafted request must not be able to reach one through this API."""
    return Table.objects.filter(slug=slug, location__isnull=False).first()


def _table_state(table, profile):
    """The table as the client should redraw it after an action."""
    joined = set(
        Player.objects
        .filter(user_profile=profile, table=table)
        .values_list('table_id', flat=True)
    )
    return _serialize_table(table, joined)


def _table_action(request, slug, action):
    if request.telegram_profile is None:
        return JsonResponse(
            {'error': 'not_linked',
             'detail': _('Connect your Board-Gamers account to book a seat.')},
            status=403)

    table = _resolve_table(slug)
    if table is None:
        return JsonResponse({'error': 'unknown_table'}, status=404)

    try:
        result = action(request.telegram_profile, table)
    except TableActionError as error:
        return JsonResponse(
            {'error': error.code, 'detail': str(error.message)}, status=409)

    warnings = getattr(result, 'warnings', [])
    table.refresh_from_db()
    return JsonResponse({
        'table': _table_state(table, request.telegram_profile),
        'warnings': [{'code': w.code, 'detail': str(w.message)} for w in warnings],
    })


@csrf_exempt
@require_POST
@telegram_miniapp_auth
def join(request, slug):
    return _table_action(request, slug, join_table)


@csrf_exempt
@require_POST
@telegram_miniapp_auth
def leave(request, slug):
    return _table_action(request, slug, leave_table)
