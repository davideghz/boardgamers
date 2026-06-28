from django.core.management.base import BaseCommand
from django.db.models import Q

from webapp.models import Table


class Command(BaseCommand):
    help = "Recompute table_status and leaderboard_status from each table's schedule."

    def handle(self, *args, **kwargs):
        # Safety net for the passing of time: realign tables whose phase may still
        # change. Terminal tables (CLOSED + leaderboard not editable) never need
        # further transitions, so they are excluded. Tables that get rescheduled
        # are already realigned by Table.save(), so this is just a backstop.
        tables = Table.objects.filter(
            Q(status=Table.OPEN) |
            Q(status=Table.ONGOING) |
            Q(status=Table.CLOSED, leaderboard_status=Table.LEADERBOARD_EDITABLE)
        )

        updated = 0
        for table in tables:
            if table.recompute_statuses():
                # Already recomputed above; skip the recompute inside save() but
                # keep going through save() so notification signals still fire.
                table._skip_status_recompute = True
                table.save()
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Table statuses recomputed — {updated} updated."
        ))
