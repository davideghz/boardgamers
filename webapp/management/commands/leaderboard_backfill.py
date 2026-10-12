import csv
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from webapp.models import Game, Player, ResultMode, Table

MODES_CSV = Path(settings.BASE_DIR) / 'webapp' / 'data' / 'game_result_modes.csv'


class DryRunRollback(Exception):
    pass


class Command(BaseCommand):
    help = (
        'Phase 2 of the leaderboard rollout: fill the new result fields from existing data. '
        'Sets Game.default_result_mode from webapp/data/game_result_modes.csv, marks tables '
        'that already have positions as "ffa" and derives Player.outcome. Never changes '
        'positions or scores. Idempotent; use --dry-run to preview (everything is rolled back).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would change, then roll back')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        try:
            with transaction.atomic():
                self.backfill_games()
                self.backfill_tables()
                self.check_consistency()
                if dry_run:
                    raise DryRunRollback
        except DryRunRollback:
            self.stdout.write(self.style.WARNING('DRY RUN: all changes rolled back.'))
            return
        self.stdout.write(self.style.SUCCESS('Backfill committed.'))

    def backfill_games(self):
        valid = set(ResultMode.values)
        with open(MODES_CSV, newline='') as fh:
            modes = {row['slug']: row['mode'] for row in csv.DictReader(fh)}
        bad = {slug: mode for slug, mode in modes.items() if mode not in valid}
        if bad:
            raise CommandError(f'Invalid modes in {MODES_CSV.name}: {bad}')

        changed = Counter()
        games = list(Game.objects.filter(slug__in=modes))
        for game in games:
            if game.default_result_mode != modes[game.slug]:
                game.default_result_mode = modes[game.slug]
                changed[game.default_result_mode] += 1
        Game.objects.bulk_update(games, ['default_result_mode'])

        found = {g.slug for g in games}
        not_in_db = sorted(set(modes) - found)
        not_in_csv = Game.objects.exclude(slug__in=modes).count()
        self.stdout.write(f'Games: {len(games)} in the list, updated {sum(changed.values())} {dict(changed)}')
        self.stdout.write(f'  slugs in the list but not in the DB: {len(not_in_db)} {not_in_db[:10]}')
        self.stdout.write(f'  games not in the list (left as "{ResultMode.NONE}"): {not_in_csv}')

    def backfill_tables(self):
        # A table with at least one real position was played and recorded as free-for-all:
        # that is the only mode the old leaderboard supported. Decided by the table's own data,
        # never by the game's (new) suggested mode.
        compiled = Table.objects.filter(
            Q(player__position__isnull=False) & ~Q(player__position=Table.UNSET_POSITION)
        ).distinct()
        to_mark = compiled.filter(result_mode__isnull=True)
        marked = to_mark.count()
        # queryset.update: no save(), so no table signals or notifications fire.
        Table.objects.filter(pk__in=to_mark.values('pk')).update(result_mode=ResultMode.FFA)

        tables = Table.objects.filter(result_mode__isnull=False)
        for table in tables:
            table.recompute_outcomes()
        self.stdout.write(f'Tables: {compiled.count()} with positions, newly marked "ffa": {marked}, '
                          f'outcomes recomputed on {tables.count()}')

    def check_consistency(self):
        ranked = Player.objects.exclude(position__isnull=True).exclude(position=Table.UNSET_POSITION)
        missing = ranked.filter(outcome__isnull=True).count()
        unexpected = Player.objects.filter(
            Q(position__isnull=True) | Q(position=Table.UNSET_POSITION), outcome__isnull=False,
            table__result_mode=ResultMode.FFA, table__game_outcome__isnull=True,
        ).count()
        outcomes = Counter(Player.objects.exclude(outcome__isnull=True).values_list('outcome', flat=True))
        self.stdout.write(f'Outcomes: {dict(outcomes)}; first places: {ranked.filter(position=1).count()}')
        if missing or unexpected:
            raise CommandError(
                f'Inconsistent outcomes: {missing} ranked players without outcome, '
                f'{unexpected} unranked players with one. Nothing was committed.'
            )
