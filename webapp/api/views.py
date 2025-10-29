import logging

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from webapp.models import Table, Location, Player
from webapp.api.serializers import TableSerializer

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
                    print(f"Giocatore {player.user_profile.nickname} aggiornato alla posizione {player.position}")
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
            .order_by('date', 'time')[:24]  # Increased limit since we're combining locations
        )

        serializer = self.get_serializer(tables, many=True)
        return Response(serializer.data)
