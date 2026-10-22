import logging
import time
import requests
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


def fetch_bgg_thing(bgg_id):
    """Fetch full game data from BGG thing endpoint. Returns a dict with all importable fields."""
    resp = _get(f'{BGG_API_BASE}/thing', {'id': bgg_id, 'type': BGG_TYPES, 'stats': 1}, timeout=10)
    root = ElementTree.fromstring(resp.content)
    item = root.find('item')
    if item is None:
        return None

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
        'mechanics': mechanics,
        'description': description,
        'bgg_code': str(bgg_id),
        'year_published': get_int('yearpublished'),
        'min_players': get_int('minplayers'),
        'max_players': get_int('maxplayers'),
        'min_playtime': get_int('minplaytime'),
        'max_playtime': get_int('maxplaytime'),
        'weight': weight,
        'image_url': image_url,
    }


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
