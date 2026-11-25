from collections import defaultdict

from webapp.services.event_games import catalog_game_sources, games_from_catalog_sources
from webapp.services.master_events import public_children, public_program


class MasterCatalog:
    def __init__(self, master):
        self.master = master
        self.events = public_children(master).with_public_catalog()
        self.selections, self.inventory = catalog_game_sources(self.events)

    def games(self):
        return games_from_catalog_sources(self.selections, self.inventory)

    def entries(self, games):
        """Attach the event, organizer and public sessions for a page of games."""
        games = list(games)
        if not games:
            return []
        game_ids = [game.pk for game in games]
        pairs = set(self.selections.filter(game_id__in=game_ids).values_list('game_id', 'event_id'))
        pairs.update(self.inventory.filter(game_id__in=game_ids).values_list('game_id', 'location__organized_events__pk'))
        events = self.events.in_bulk({event_id for _, event_id in pairs})
        pairs = [pair for pair in pairs if pair[1] in events]

        tables = defaultdict(list)
        for table in public_program(self.master).filter(game_id__in=game_ids, event_id__in=events.keys()):
            tables[table.game_id, table.event_id].append(table)

        offers = defaultdict(list)
        for game_id, event_id in sorted(pairs, key=lambda pair: (events[pair[1]].name, pair[1])):
            offers[game_id].append({'event': events[event_id], 'tables': tables[game_id, event_id]})
        return [{'game': game, 'offers': offers[game.pk]} for game in games if offers[game.pk]]
