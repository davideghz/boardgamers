import time
from django.core.management.base import BaseCommand
from webapp.models import Game
from webapp.services.bgg import fetch_bgg_classifications


class Command(BaseCommand):
    help = "Set Game.is_expansion from BGG for the games that have a bgg_code"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without saving')

    def handle(self, *args, **kwargs):
        dry_run = kwargs['dry_run']

        games = {}
        for game in Game.objects.exclude(bgg_code__isnull=True).exclude(bgg_code=''):
            games.setdefault(game.bgg_code, []).append(game)
        self.stdout.write(f"Classifying {len(games)} BGG code(s)...")

        # 20 ids per /thing call, paced so BGG does not throttle us; ids that
        # fail are skipped and keep their current value
        codes = list(games)
        classifications = {}
        for start in range(0, len(codes), 20):
            if start:
                time.sleep(2)
            classifications.update(fetch_bgg_classifications(codes[start:start + 20]))
        to_update = []
        for bgg_code, info in classifications.items():
            for game in games.get(bgg_code, []):
                if game.is_expansion != info['is_expansion']:
                    game.is_expansion = info['is_expansion']
                    to_update.append(game)
                    self.stdout.write(f"  {game.name} (BGG {bgg_code}) → is_expansion={game.is_expansion}")

        if not dry_run:
            Game.objects.bulk_update(to_update, ['is_expansion'])
        missing = len(games) - len(classifications)
        self.stdout.write(self.style.SUCCESS(
            f"Done. {'(dry-run) ' if dry_run else ''}{len(to_update)} game(s) updated, "
            f"{missing} BGG code(s) not classified."))
