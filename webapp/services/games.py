"""Merging duplicate games (admin action).

The caller (the admin) picks which game to keep and, field by field, which
value wins; this module moves every relation and deletes the duplicate in one
transaction. Players and results hang off tables, so they follow untouched.
"""

from collections import namedtuple

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from webapp.models import Game, LocationGame, Table

# Fields offered for a side-by-side choice in the merge confirmation page.
MERGEABLE_FIELDS = (
    'name', 'description', 'image', 'bgg_code', 'min_players', 'max_players',
    'min_playtime', 'max_playtime', 'weight', 'year_published', 'default_result_mode',
)
# Flags kept if true on either game.
OR_FLAGS = ('verified', 'bgg_imported', 'leaderboard_enabled')

MergeResult = namedtuple('MergeResult', 'tables_moved library_moved library_merged')


def is_empty(value):
    if value is None:
        return True
    if hasattr(value, 'name'):  # FieldFile
        return not value.name
    return value == ''


def default_keeper(game_a, game_b):
    """The game to keep by default: more tables, then BGG-imported/verified, then the older one."""
    counts = dict(
        Game.objects.filter(pk__in=[game_a.pk, game_b.pk])
        .annotate(n=Count('created_tables')).values_list('pk', 'n')
    )

    def score(g):
        return (counts.get(g.pk, 0), g.bgg_imported or g.verified, -g.pk)
    return game_a if score(game_a) >= score(game_b) else game_b


def default_choice(field, keeper, duplicate):
    """'keeper' unless the keeper's value is empty and the duplicate's is not."""
    if is_empty(getattr(keeper, field)) and not is_empty(getattr(duplicate, field)):
        return 'duplicate'
    return 'keeper'


def differing_fields(game_a, game_b):
    def norm(v):
        return v.name if hasattr(v, 'name') else v
    return [f for f in MERGEABLE_FIELDS if norm(getattr(game_a, f)) != norm(getattr(game_b, f))]


def library_conflicts(keeper, duplicate):
    """Locations that have both games in their library."""
    return list(
        LocationGame.objects.filter(game=duplicate, location__location_games__game=keeper)
        .select_related('location')
    )


def merge_games(keeper, duplicate, choices):
    """Merge `duplicate` into `keeper` and delete it.

    `choices`: {field: 'keeper' | 'duplicate'} for MERGEABLE_FIELDS (missing = keeper).
    The keeper's slug never changes (fields are written with update(), so a new
    name does not regenerate it). Library entries of a location holding both
    games are folded into the keeper's entry, appending the duplicate's notes.
    """
    if keeper.pk == duplicate.pk:
        raise ValueError('Cannot merge a game into itself.')

    with transaction.atomic():
        keeper = Game.objects.select_for_update().get(pk=keeper.pk)
        duplicate = Game.objects.select_for_update().get(pk=duplicate.pk)

        values = {}
        for field in MERGEABLE_FIELDS:
            if choices.get(field) == 'duplicate':
                value = getattr(duplicate, field)
                values[field] = value.name if hasattr(value, 'name') else value
        for flag in OR_FLAGS:
            values[flag] = getattr(keeper, flag) or getattr(duplicate, flag)
        values['updated_at'] = timezone.now()

        # queryset update: no table signals; results stay as they are.
        tables_moved = Table.objects.filter(game=duplicate).update(game=keeper)

        library_merged = 0
        for entry in library_conflicts(keeper, duplicate):
            kept = LocationGame.objects.get(location=entry.location, game=keeper)
            if entry.notes.strip():
                kept.notes = f'{kept.notes}\n{entry.notes}'.strip() if kept.notes.strip() else entry.notes
                kept.save(update_fields=['notes', 'updated_at'])
            entry.delete()
            library_merged += 1
        library_moved = LocationGame.objects.filter(game=duplicate).update(game=keeper)

        Game.objects.filter(pk=keeper.pk).update(**values)
        duplicate.delete()

    return MergeResult(tables_moved, library_moved, library_merged)
