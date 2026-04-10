import time
from django.core.management.base import BaseCommand
from django.db.models import Q
from webapp.models import Game
from webapp.services.bgg import fetch_bgg_thing

FIELDS = ['min_players', 'max_players', 'min_playtime', 'max_playtime', 'weight', 'year_published']


class Command(BaseCommand):
    help = "Fill missing game info (players, playtime, weight, year) from BGG for games that have a bgg_code"

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be updated without saving')

    def handle(self, *args, **kwargs):
        dry_run = kwargs['dry_run']

        missing_filter = Q()
        for field in FIELDS:
            missing_filter |= Q(**{f'{field}__isnull': True})

        games = Game.objects.exclude(bgg_code__isnull=True).exclude(bgg_code='').filter(missing_filter)
        total = games.count()

        self.stdout.write(f"Found {total} game(s) with bgg_code and at least one missing field.")

        updated = 0
        for i, game in enumerate(games):
            missing = [f for f in FIELDS if getattr(game, f) is None]
            self.stdout.write(f"[{i + 1}/{total}] {game.name} (BGG {game.bgg_code}) — missing: {', '.join(missing)}")

            try:
                data = fetch_bgg_thing(game.bgg_code)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Error fetching BGG data: {e}"))
                time.sleep(2)
                continue

            if not data:
                self.stdout.write(self.style.WARNING("  No data returned from BGG, skipping."))
                time.sleep(2)
                continue

            changed_fields = []
            for field in missing:
                value = data.get(field)
                if value is not None:
                    setattr(game, field, value)
                    changed_fields.append(f"{field}={value}")

            if changed_fields:
                if not dry_run:
                    game.save(update_fields=[f for f in missing if getattr(game, f) is not None])
                self.stdout.write(self.style.SUCCESS(f"  {'(dry-run) ' if dry_run else ''}Updated: {', '.join(changed_fields)}"))
                updated += 1
            else:
                self.stdout.write("  Nothing to update (BGG returned no values for missing fields).")

            if i < total - 1:
                time.sleep(2)

        self.stdout.write(self.style.SUCCESS(f"\nDone. {updated}/{total} game(s) updated."))
