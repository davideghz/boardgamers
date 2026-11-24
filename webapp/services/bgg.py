import logging
import time
import requests
from django.db.models import Q
from xml.etree import ElementTree
from webapp.services.images import COVER_MAX_SIDE, shrink_content_file

logger = logging.getLogger(__name__)

BGG_API_BASE = 'https://boardgamegeek.com/xmlapi2'


def _get(url, params, timeout=10, max_retries=3):
    """GET with retry on BGG's 202 'please try again' response."""
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, headers=_headers(), timeout=timeout)
        if resp.status_code == 200:
            return resp
        if resp.status_code == 202:
            time.sleep(1.5)
            continue
        resp.raise_for_status()
    return resp


def _headers():
    from django.conf import settings
    token = getattr(settings, 'BGG_API_TOKEN', '')
    if token:
        return {'Authorization': f'Bearer {token}'}
    return {}


# 'rpg' (RPG families) is excluded: its ids live in a separate space, so /thing
# resolves them to unrelated items (e.g. a videogame) instead of the RPG.
ALLOWED_TYPES = {'boardgame', 'rpgitem'}
BGG_TYPES = ','.join(sorted(ALLOWED_TYPES))
# /search with type=boardgame already returns expansions, typed as boardgame;
# /thing types them as boardgameexpansion, so they must be allowed explicitly.
THING_TYPES = ','.join(sorted(ALLOWED_TYPES | {'boardgameexpansion'}))


def search_bgg(query):
    """Search BGG. Returns list of {bgg_id, name, year_published}."""
    resp = _get(f'{BGG_API_BASE}/search', {'query': query, 'type': BGG_TYPES}, timeout=8)
    root = ElementTree.fromstring(resp.content)
    results = []
    for item in root.findall('item'):
        if item.get('type') not in ALLOWED_TYPES:
            continue
        bgg_id = item.get('id')
        name_el = item.find('name')
        year_el = item.find('yearpublished')
        if name_el is not None:
            results.append({
                'bgg_id': bgg_id,
                'name': name_el.get('value', ''),
                'year_published': int(year_el.get('value')) if year_el is not None else None,
            })
    query_lower = query.lower()
    results.sort(key=lambda r: (0 if r['name'].lower().startswith(query_lower) else 1))
    return results


def fetch_bgg_classifications(bgg_ids):
    """Batch /thing call to classify a list of bgg_ids.
    Returns {bgg_id: {'is_expansion': bool, 'name': str, 'year_published': int|None}}.
    Silently skips IDs that fail.
    """
    if not bgg_ids:
        return {}

    results = {}
    chunks = [bgg_ids[i:i + 20] for i in range(0, len(bgg_ids), 20)]
    for chunk in chunks:
        try:
            resp = _get(f'{BGG_API_BASE}/thing', {'id': ','.join(str(i) for i in chunk)}, timeout=12)
            root = ElementTree.fromstring(resp.content)
            for item in root.findall('item'):
                bgg_id = item.get('id')
                is_expansion = item.get('type') == 'boardgameexpansion'

                name = None
                for name_el in item.findall('name'):
                    if name_el.get('type') == 'primary':
                        name = name_el.get('value')
                        break

                year_el = item.find('yearpublished')
                year = None
                if year_el is not None:
                    try:
                        year = int(year_el.get('value', ''))
                    except (ValueError, TypeError):
                        pass

                results[bgg_id] = {
                    'is_expansion': is_expansion,
                    'name': name,
                    'year_published': year,
                }
        except Exception as e:
            logger.warning(f'BGG batch /thing failed for chunk {chunk}: {e}')
    return results


def _parse_thing(item):
    """Importable fields of a /thing <item> (fetched with stats=1)."""
    name = None
    for name_el in item.findall('name'):
        if name_el.get('type') == 'primary':
            name = name_el.get('value')
            break

    def get_int(tag):
        el = item.find(tag)
        if el is None:
            return None
        try:
            return int(el.get('value', ''))
        except (ValueError, TypeError):
            return None

    description_el = item.find('description')
    description = (description_el.text or '') if description_el is not None else ''

    image_el = item.find('image')
    image_url = image_el.text if image_el is not None else None
    if image_url and image_url.startswith('//'):
        image_url = 'https:' + image_url

    weight = None
    stats = item.find('statistics')
    if stats is not None:
        ratings = stats.find('ratings')
        if ratings is not None:
            w_el = ratings.find('averageweight')
            if w_el is not None:
                try:
                    w = float(w_el.get('value', '0'))
                    if w > 0:
                        weight = round(w, 2)
                except (ValueError, TypeError):
                    pass

    mechanics = [link.get('value') for link in item.findall('link') if link.get('type') == 'boardgamemechanic']

    return {
        'name': name,
        'bgg_type': item.get('type'),
        'is_expansion': item.get('type') == 'boardgameexpansion',
        'mechanics': mechanics,
        'description': description,
        'bgg_code': str(item.get('id')),
        'year_published': get_int('yearpublished'),
        'min_players': get_int('minplayers'),
        'max_players': get_int('maxplayers'),
        'min_playtime': get_int('minplaytime'),
        'max_playtime': get_int('maxplaytime'),
        'weight': weight,
        'image_url': image_url,
    }


def fetch_bgg_thing(bgg_id):
    """Fetch full game data from BGG thing endpoint. Returns a dict with all importable fields."""
    resp = _get(f'{BGG_API_BASE}/thing', {'id': bgg_id, 'type': THING_TYPES, 'stats': 1}, timeout=10)
    root = ElementTree.fromstring(resp.content)
    item = root.find('item')
    if item is None:
        return None
    data = _parse_thing(item)
    data['bgg_code'] = str(bgg_id)
    return data


THING_BATCH_SIZE = 20  # BGG's limit of ids per /thing call


def fetch_bgg_things(bgg_ids):
    """Batch version of fetch_bgg_thing: {bgg_id: data} for the ids BGG knows.
    Expansions are included (no type filter), so collections can bring them in."""
    results = {}
    bgg_ids = [str(i) for i in bgg_ids]
    for start in range(0, len(bgg_ids), THING_BATCH_SIZE):
        chunk = bgg_ids[start:start + THING_BATCH_SIZE]
        resp = _get(f'{BGG_API_BASE}/thing', {'id': ','.join(chunk), 'stats': 1}, timeout=15)
        root = ElementTree.fromstring(resp.content)
        for item in root.findall('item'):
            data = _parse_thing(item)
            results[data['bgg_code']] = data
    return results


class BGGCollectionError(Exception):
    NOT_FOUND = 'not_found'      # no such BGG user
    PENDING = 'pending'          # BGG is still preparing the collection: retry later
    UNAVAILABLE = 'unavailable'  # BGG is down or answered something unexpected

    def __init__(self, code):
        super().__init__(code)
        self.code = code


# BGG answers 202 while it builds a collection that is not cached, sometimes for
# a while. Keep the whole fetch well under Heroku's 30 s request timeout: past
# the budget the user is asked to retry, and BGG keeps building it meanwhile.
COLLECTION_TIME_BUDGET = 20


def _get_collection(params, deadline):
    delay = 1.5
    while True:
        try:
            resp = requests.get(f'{BGG_API_BASE}/collection', params=params, headers=_headers(), timeout=15)
        except requests.RequestException as e:
            logger.warning(f'BGG collection request failed: {e}')
            raise BGGCollectionError(BGGCollectionError.UNAVAILABLE)
        if resp.status_code == 200:
            break
        if resp.status_code != 202:
            logger.warning(f'BGG collection answered {resp.status_code}')
            raise BGGCollectionError(BGGCollectionError.UNAVAILABLE)
        if time.monotonic() + delay > deadline:
            raise BGGCollectionError(BGGCollectionError.PENDING)
        time.sleep(delay)
        delay = min(delay * 1.5, 5)

    try:
        root = ElementTree.fromstring(resp.content)
    except ElementTree.ParseError:
        raise BGGCollectionError(BGGCollectionError.UNAVAILABLE)
    if root.tag == 'errors':
        message = ' '.join(el.text or '' for el in root.iter('message'))
        if 'username' in message.lower():
            raise BGGCollectionError(BGGCollectionError.NOT_FOUND)
        raise BGGCollectionError(BGGCollectionError.UNAVAILABLE)
    return root


def _collection_items(root, is_expansion):
    items = []
    for item in root.findall('item'):
        name_el = item.find('name')
        year_el = item.find('yearpublished')
        thumb_el = item.find('thumbnail')
        try:
            year = int(year_el.text) if year_el is not None else None
        except (TypeError, ValueError):
            year = None
        thumbnail = (thumb_el.text or '').strip() if thumb_el is not None else ''
        if thumbnail.startswith('//'):
            thumbnail = 'https:' + thumbnail
        items.append({
            'bgg_id': item.get('objectid'),
            'name': (name_el.text or '').strip() if name_el is not None else '',
            'year_published': year,
            'thumbnail': thumbnail,
            'is_expansion': is_expansion,
        })
    return items


def fetch_bgg_collection(username):
    """Games and expansions a BGG user marks as owned (public collections only).

    Returns a list of {bgg_id, name, year_published, thumbnail, is_expansion}:
    games first, then expansions, each sorted by name, one entry per BGG id.
    Raises BGGCollectionError.
    """
    deadline = time.monotonic() + COLLECTION_TIME_BUDGET
    base = {'username': username, 'own': 1}
    # subtype=boardgame also returns expansions, hence the exclusion.
    games = _get_collection({**base, 'subtype': 'boardgame', 'excludesubtype': 'boardgameexpansion'}, deadline)
    expansions = _get_collection({**base, 'subtype': 'boardgameexpansion'}, deadline)

    seen = set()
    result = []
    for root, is_expansion in ((games, False), (expansions, True)):
        items = sorted(_collection_items(root, is_expansion), key=lambda i: i['name'].lower())
        for item in items:
            if item['bgg_id'] and item['bgg_id'] not in seen:
                seen.add(item['bgg_id'])
                result.append(item)
    return result


def suggest_result_mode(bgg_type, mechanics):
    """Suggested leaderboard mode from BGG data (see docs/leaderboard-seasons-plan.md).

    BGG has no "competitive" tag, so free-for-all is inferred when no coop/team
    mechanic is listed. Semi-cooperative games are recorded as free-for-all.
    """
    from webapp.models import ResultMode

    if bgg_type == 'rpgitem':
        return ResultMode.NONE
    if bgg_type != 'boardgame':
        return ResultMode.NONE
    mechanics = set(mechanics or [])
    if 'Semi-Cooperative Game' in mechanics:
        return ResultMode.FFA
    if 'Cooperative Game' in mechanics:
        return ResultMode.COOP
    if 'Team-Based Game' in mechanics:
        return ResultMode.TEAMS
    return ResultMode.FFA


def _create_game(data):
    """Create a Game from fetch_bgg_thing data, downloading its cover."""
    from webapp.models import Game

    bgg_id = data['bgg_code']
    game = Game(
        name=data['name'],
        description=data['description'],
        bgg_code=bgg_id,
        year_published=data['year_published'],
        min_players=data['min_players'],
        max_players=data['max_players'],
        min_playtime=data['min_playtime'],
        max_playtime=data['max_playtime'],
        weight=data['weight'],
        leaderboard_enabled=False,
        default_result_mode=suggest_result_mode(data['bgg_type'], data['mechanics']),
        bgg_imported=True,
        is_expansion=data['is_expansion'],
    )
    game.slug = game.create_unique_slug()
    game.save()

    if data['image_url']:
        try:
            img_resp = requests.get(data['image_url'], timeout=10)
            img_resp.raise_for_status()
            ext = data['image_url'].rsplit('.', 1)[-1].split('?')[0][:4]
            name, content = shrink_content_file(img_resp.content, f"bgg_{bgg_id}.{ext}", COVER_MAX_SIDE)
            game.image.save(name, content, save=True)
        except Exception as e:
            logger.warning(f'BGG image download failed for id={bgg_id}: {e}')

    return game


def import_game_from_bgg(bgg_id):
    """Import a game from BGG into the local DB. Returns the Game instance."""
    from webapp.models import Game

    bgg_id = str(bgg_id)

    existing = Game.objects.filter(bgg_code=bgg_id).first()
    if existing:
        return existing

    data = fetch_bgg_thing(bgg_id)
    if not data or not data['name']:
        return None
    return _create_game(data)


def import_games_from_bgg(items):
    """Batch import for BGG collections. `items`: [{bgg_id, name}].

    Returns {bgg_id: Game}, leaving out the ids BGG does not know. A game is
    reused when its BGG code is already in the DB, or else when a game without
    BGG code has the same name; only the remaining ones are fetched from BGG.
    """
    from webapp.models import Game

    names = {str(i['bgg_id']): (i.get('name') or '').strip() for i in items}
    games = {}
    for game in Game.objects.filter(bgg_code__in=names).order_by('pk'):
        games.setdefault(game.bgg_code, game)

    missing = []
    for bgg_id, name in names.items():
        if bgg_id in games:
            continue
        same_name = Game.objects.filter(name__iexact=name).filter(
            Q(bgg_code__isnull=True) | Q(bgg_code='')).order_by('pk').first() if name else None
        if same_name:
            games[bgg_id] = same_name
        else:
            missing.append(bgg_id)

    for bgg_id, data in fetch_bgg_things(missing).items():
        if data['name']:
            games[bgg_id] = _create_game(data)
    return games
