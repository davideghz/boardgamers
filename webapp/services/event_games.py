"""Reads of an event's game library, shared by the event page and the library page.

The event page gets a lot of traffic: the featured games are capped, game
descriptions (long BGG texts) are never loaded, and everything per-game comes
from one query per relation, whatever the number of games.
"""

from dataclasses import dataclass, field
from datetime import date

from django.db.models import Exists, Min, OuterRef, Prefetch, Q
from django.utils import timezone

from webapp.models import Event, EventGame, Game, Location, LocationGame, Table
from webapp.services.game_loans import with_game_loan_status

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


def catalog_game_sources(events):
    """Select the inventory and event selections that make up these catalogs."""
    archived = LocationGame.objects.filter(
        location_id=OuterRef('event__organizer_location_id'), game_id=OuterRef('game_id'), is_archived=True,
    )
    scheduled = Table.objects.filter(event_id=OuterRef('event_id'), game_id=OuterRef('game_id'))
    # Library-mode events keep a withdrawn title only when one of their tables plays it.
    selections = EventGame.objects.filter(event__in=events).exclude(
        Event.location_catalog_condition('event__') & Q(Exists(archived)) & ~Q(Exists(scheduled)),
    )
    inventory = LocationGame.objects.filter(
        is_archived=False, location__organized_events__in=events.filter(Event.location_catalog_condition()),
    )
    return selections, inventory


def games_from_catalog_sources(selections, inventory):
    return Game.objects.filter(
        Exists(selections.filter(game_id=OuterRef('pk'))) | Exists(inventory.filter(game_id=OuterRef('pk'))),
    ).defer('description').order_by('name', 'pk')


def effective_catalog(event):
    """The games of the event's catalog, by name."""
    return games_from_catalog_sources(*catalog_game_sources(Event.objects.filter(pk=event.pk)))


@dataclass
class CatalogEntry:
    """A game as the event's catalog shows it."""
    game: Game
    #: Its title in the organizing location's library, when the catalog uses it.
    location_game: LocationGame | None = None
    tags: list = field(default_factory=list)
    sponsor_locations: list = field(default_factory=list)
    first_table_date: date | None = None

    @property
    def game_id(self):
        return self.game.pk


def catalog_entries(event, games):
    """The entries to show for `games`, a page of the event's catalog."""
    games = list(games)
    if not games:
        return []
    selections = {entry.game_id: entry for entry in library_queryset(event).filter(game__in=games)}
    titles = {}
    if event.uses_location_library:
        titles = {title.game_id: title for title in with_game_loan_status(LocationGame.objects.filter(
            location_id=event.organizer_location_id, is_archived=False, game__in=games))}
    entries = []
    for game in games:
        entry = CatalogEntry(game, titles.get(game.pk))
        if game.pk in selections:
            entry.tags = list(selections[game.pk].tags.all())
            entry.sponsor_locations = list(selections[game.pk].sponsor_locations.all())
        entries.append(entry)
    return attach_booking_dates(event, entries)


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
    flagged = EventGame.objects.filter(
        event=event, game_id=OuterRef('pk'), tags__show_on_event_page=True)
    return catalog_entries(event, effective_catalog(event).filter(Exists(flagged))[:FEATURED_GAMES_LIMIT])
