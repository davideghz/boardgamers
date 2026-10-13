import logging

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.utils.timezone import now
from webapp.models import Table, Location, Game
from webapp.api.serializers import TableSerializer
from webapp.services.bgg import search_bgg, import_game_from_bgg, fetch_bgg_classifications

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([AllowAny])
def tables_by_location_view(request, location_slugs):
    """Public tables of one or more locations (comma-separated slugs), for the
    embeddable widget (boardGames/static/widget/widget.js)."""
    # Split the comma-separated slugs and remove any empty strings
    slugs = [slug.strip() for slug in location_slugs.split(',') if slug.strip()]

    # Get all valid locations
    locations = Location.objects.filter(slug__in=slugs)

    # If no valid locations found, return 404
    if not locations.exists():
        return Response(
            {'error': 'No valid locations found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Get tables from all specified locations
    limit = 12
    today = now().date()
    base_qs = (
        Table.objects
        .filter(location__in=locations)
        .select_related('location', 'game')
        .prefetch_related('players')
    )

    # Upcoming tables first (closest in time first), then fill the
    # remaining slots with the most recent past tables as a fallback.
    future_tables = list(
        base_qs.filter(date__gte=today).order_by('date', 'time')[:limit]
    )
    remaining = limit - len(future_tables)
    past_tables = (
        list(base_qs.filter(date__lt=today).order_by('-date', '-time')[:remaining])
        if remaining > 0 else []
    )
    tables = future_tables + past_tables

    return Response(TableSerializer(tables, many=True, context={'request': request}).data)


@api_view(['GET'])
def bgg_search_view(request):
    """Search games in local DB only. Fast path — excludes known expansions."""
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=401)

    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return Response({'local': []})

    local_qs = Game.objects.filter(name__icontains=query).order_by('name')[:8]
    local_data = [
        {'id': g.id, 'name': g.name, 'year_published': g.year_published,
         'min_players': g.min_players, 'max_players': g.max_players}
        for g in local_qs
    ]
    return Response({'local': local_data})


@api_view(['GET'])
def bgg_search_external_view(request):
    """Search BGG, classify via batch /thing, save stubs for non-expansions, return filtered results."""
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=401)

    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return Response({'bgg': []})

    try:
        bgg_results = search_bgg(query)
    except Exception as e:
        logger.warning(f'BGG search failed for query="{query}": {e}')
        return Response({'bgg': []})

    bgg_results = bgg_results[:20]

    # Split into known (already in DB) vs unknown (need /thing)
    search_bgg_ids = [r['bgg_id'] for r in bgg_results]
    existing_codes = set(
        Game.objects.filter(bgg_code__in=search_bgg_ids).values_list('bgg_code', flat=True)
    )
    unknown_ids = [bid for bid in search_bgg_ids if bid not in existing_codes]

    # Batch classify unknowns
    classifications = fetch_bgg_classifications(unknown_ids) if unknown_ids else {}

    # Return only non-expansions not already shown in local results
    bgg_data = []
    for r in bgg_results:
        if r['bgg_id'] in existing_codes:
            continue
        info = classifications.get(r['bgg_id'])
        if info is not None and info['is_expansion']:
            continue
        bgg_data.append(r)

    return Response({'bgg': bgg_data[:15]})


@api_view(['POST'])
def bgg_import_view(request):
    """Import a game from BGG by bgg_id. Returns {id, name}."""
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=401)

    bgg_id = request.data.get('bgg_id')
    if not bgg_id:
        return Response({'error': 'bgg_id is required'}, status=400)

    try:
        game = import_game_from_bgg(bgg_id)
    except Exception as e:
        logger.error(f'BGG import failed for id={bgg_id}: {e}')
        return Response({'error': 'Import failed'}, status=500)

    if not game:
        return Response({'error': 'Game not found on BGG'}, status=404)

    return Response({
        'id': game.id, 'name': game.name,
        'min_players': game.min_players, 'max_players': game.max_players,
    })
