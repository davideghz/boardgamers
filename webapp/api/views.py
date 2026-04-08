import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from webapp.models import Table, Location, Player, Game
from webapp.api.serializers import TableSerializer
from webapp.services.bgg import search_bgg, import_game_from_bgg, fetch_bgg_classifications

logger = logging.getLogger(__name__)


class TableViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Table.objects.all()
    serializer_class = TableSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        # Rendi pubblica solo l'azione by_location
        if self.action == 'by_location':
            return [AllowAny()]
        return super().get_permissions()

    @action(detail=True, methods=['post'], url_path='update-player-position')
    def update_player_position(self, request, pk=None):
        try:
            table = self.get_object()

            # Verifica se la classifica è modificabile
            if table.leaderboard_status == Table.LEADERBOARD_NOT_EDITABLE and not request.user.is_superuser:
                print(f"Errore: La classifica per il tavolo '{table.title}' non è modificabile.")
                return Response({'success': False, 'error': 'Leaderboard is not editable'},
                                status=status.HTTP_403_FORBIDDEN)


            players = request.data.get('players', [])

            # Log per verificare i dati ricevuti
            print(f"Players data received: {players}")

            # Verifica che l'utente sia un player del tavolo o un admin
            if not (request.user.is_superuser or request.user.user_profile in table.players.all()):
                return Response({'success': False, 'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

            # Aggiorna le posizioni dei giocatori
            for player_data in players:
                player_id = player_data.get('id')
                position = player_data.get('position')

                # Log per verificare id e posizione
                print(f"Aggiornamento player ID {player_id} alla posizione {position}")

                if player_id is None or position is None:
                    print(f"Errore: ID o posizione mancanti per il player: {player_data}")
                    continue

                try:
                    player = Player.objects.get(id=player_id, table=table)  # Usa il filtro per il tavolo corretto
                    player.position = position
                    player.save()
                    print(f"Giocatore {player.display_name} aggiornato alla posizione {player.position}")
                except Player.DoesNotExist:
                    print(f"Errore: Player con ID {player_id} non trovato.")
                    continue
                except Exception as e:
                    print(f"Errore durante l'aggiornamento del player con ID {player_id}: {str(e)}")
                    return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

            return Response({'success': True}, status=status.HTTP_200_OK)

        except Table.DoesNotExist:
            return Response({'success': False, 'error': 'Table not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            print(f"Errore inaspettato: {str(e)}")
            return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], url_path=r'by-location/(?P<location_slugs>[\w,-]+)')

    def by_location(self, request, location_slugs=None):
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
        tables = (
            Table.objects
            .filter(location__in=locations)
            .select_related('location', 'game')
            .prefetch_related('players')
            .order_by('-date', '-time')[:12]  # Increased limit since we're combining locations
        )

        serializer = self.get_serializer(tables, many=True)
        return Response(serializer.data)


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
        {'id': g.id, 'name': g.name, 'year_published': g.year_published}
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

    return Response({'id': game.id, 'name': game.name})
