"""Reads of an event's game library, shared by the event page and the library page.

The event page gets a lot of traffic: the featured games are capped, game
descriptions (long BGG texts) are never loaded, and everything per-game comes
from one query per relation, whatever the number of games.
"""

from django.db.models import Exists, Min, OuterRef, Prefetch
from django.utils import timezone

from webapp.models import EventGame, EventGameTag, Location, Table

#: Games shown on the event page, the rest are one click away in the library.
FEATURED_GAMES_LIMIT = 12


def library_queryset(event):
    """The event's games, by name (pk as tie-breaker keeps pagination stable)."""
    return (
        EventGame.objects
        .filter(event=event)
        .select_related('game')
        .defer('game__description')
        .prefetch_related(
            'tags',
            Prefetch('sponsor_locations', queryset=Location.objects.only('id', 'name').order_by('name')),
        )
        .order_by('game__name', 'pk')
    )


def attach_booking_dates(event, entries):
    """Set `first_table_date` on each entry: the first day the game has a table
    still to be played, or None. Full tables count, closed or past ones don't.
    Returns `entries` as a list."""
    entries = list(entries)
    if entries:
        dates = dict(
            Table.objects
            .filter(event=event, game_id__in=[entry.game_id for entry in entries],
                    date__gte=timezone.localdate())
            .exclude(status=Table.CLOSED)
            .order_by()
            .values_list('game_id')
            .annotate(first_date=Min('date'))
        )
        for entry in entries:
            entry.first_table_date = dates.get(entry.game_id)
    return entries


def featured_games(event):
    """The games to show on the event page: those with a tag flagged for it."""
    flagged = EventGameTag.objects.filter(games=OuterRef('pk'), show_on_event_page=True)
    return attach_booking_dates(event, library_queryset(event).filter(Exists(flagged))[:FEATURED_GAMES_LIMIT])
