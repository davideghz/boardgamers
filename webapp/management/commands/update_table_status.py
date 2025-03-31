from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.timezone import now, make_aware
from datetime import datetime, timedelta  # Import corretto
from webapp.models import Table  # Sostituisci con il percorso corretto del tuo modello


class Command(BaseCommand):
    help = "Aggiorna lo stato dei tavoli e il loro leaderboard status"

    def handle(self, *args, **kwargs):
        current_time = now()

        # Aggiorna i tavoli aperti o in corso
        tables = Table.objects.filter(
            Q(status=Table.OPEN) |
            Q(status=Table.ONGOING) |
            Q(status=Table.CLOSED, leaderboard_status=Table.LEADERBOARD_NOT_EDITABLE)
        )

        for table in tables:
            game_datetime = make_aware(datetime.combine(table.date, table.time))

            # Caso 1: Partita non ancora iniziata
            if current_time < game_datetime:
                table.status = Table.OPEN
                table.leaderboard_status = Table.LEADERBOARD_NOT_EDITABLE

            # Caso 2: Partita in corso
            elif game_datetime <= current_time < game_datetime + timedelta(days=1):
                table.status = Table.ONGOING
                table.leaderboard_status = Table.LEADERBOARD_EDITABLE

            # Caso 3: Partita terminata da 1 giorno
            elif game_datetime + timedelta(days=1) <= current_time < game_datetime + timedelta(days=2):
                table.status = Table.CLOSED
                table.leaderboard_status = Table.LEADERBOARD_EDITABLE

            # Caso 4: Partita terminata da 2 giorni
            elif current_time >= game_datetime + timedelta(days=2):
                table.status = Table.CLOSED
                table.leaderboard_status = Table.LEADERBOARD_NOT_EDITABLE

            table.save()

        self.stdout.write(self.style.SUCCESS("Stati dei tavoli aggiornati con successo!"))
