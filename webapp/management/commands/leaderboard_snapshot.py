import json
import sys

from django.core.management.base import BaseCommand
from django.utils import timezone

from webapp.models import Player

# Legacy "leaderboard not compiled" marker; it will become NULL. Both mean "no position".
UNSET_POSITION = 99


def _position(value):
    return None if value in (None, UNSET_POSITION) else value


def take_snapshot():
    """Every player result, keyed by Player id, with positions normalised."""
    players = {}
    rows = Player.objects.values_list(
        'id', 'table_id', 'user_profile_id', 'guest_profile_id', 'position', 'score'
    ).order_by('id')
    for pid, table_id, user_id, guest_id, position, score in rows:
        players[str(pid)] = {
            'table': table_id,
            'user': user_id,
            'guest': guest_id,
            'position': _position(position),
            'score': score,
        }
    return players


def load_snapshot(path):
    """Read a snapshot file, skipping any noise around the JSON line.

    Output captured from `heroku run` (or local settings that print at startup)
    can contain extra lines; the snapshot itself is always a single JSON line.
    """
    with open(path) as fh:
        for line in fh:
            if line.startswith('{"generated_at"'):
                return json.loads(line)
    raise ValueError(f'No snapshot found in {path}')


def summarize(players):
    compiled = [p for p in players.values() if p['position'] is not None]
    return {
        'players': len(players),
        'players_with_position': len(compiled),
        'tables_with_results': len({p['table'] for p in compiled}),
        'first_places': sum(1 for p in compiled if p['position'] == 1),
        'second_places': sum(1 for p in compiled if p['position'] == 2),
        'third_places': sum(1 for p in compiled if p['position'] == 3),
    }


class Command(BaseCommand):
    help = (
        'Snapshot every table result (player positions and scores) as JSON on stdout, '
        'or compare the current data with a previous snapshot (--compare). '
        'Used to prove that the leaderboard migration does not lose or alter results.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--compare', metavar='FILE',
            help='Compare the current data with a snapshot file instead of printing a new one',
        )

    def handle(self, *args, **options):
        current = take_snapshot()

        if not options['compare']:
            self.stdout.write(json.dumps({
                'generated_at': timezone.now().isoformat(),
                'summary': summarize(current),
                'players': current,
            }))
            return

        old = load_snapshot(options['compare'])['players']

        missing = sorted(set(old) - set(current), key=int)
        added = sorted(set(current) - set(old), key=int)
        changed = [
            (pid, old[pid], current[pid])
            for pid in sorted(set(old) & set(current), key=int)
            if old[pid] != current[pid]
        ]

        self.stdout.write(f'Snapshot:  {json.dumps(summarize(old))}')
        self.stdout.write(f'Current:   {json.dumps(summarize(current))}')
        self.stdout.write(f'Missing players (in snapshot, gone now): {len(missing)}')
        for pid in missing:
            self.stdout.write(f'  - player {pid}: {old[pid]}')
        self.stdout.write(f'Changed players: {len(changed)}')
        for pid, before, after in changed:
            self.stdout.write(f'  ~ player {pid}: {before} -> {after}')
        # New players are expected in production (people keep joining tables).
        self.stdout.write(f'Added players (new since snapshot, informational): {len(added)}')

        if missing or changed:
            self.stdout.write(self.style.ERROR('DIFFERENCES FOUND: results were lost or altered.'))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS('OK: every result in the snapshot is unchanged.'))
