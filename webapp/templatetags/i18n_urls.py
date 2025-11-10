# webapp/templatetags/i18n_urls.py
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from django import template
from django.conf import settings
from django.urls import translate_url

register = template.Library()

# Imposta in settings.py queste costanti per gestire i querystring, es.:
# ALLOWED_ALTERNATE_QUERY_PARAMS = {"page", "sort"}
# ALLOWED_CANONICAL_QUERY_PARAMS = set()
ALLOWED_ALTERNATE_QUERY_PARAMS = getattr(settings, "ALLOWED_ALTERNATE_QUERY_PARAMS", set())
ALLOWED_CANONICAL_QUERY_PARAMS = getattr(settings, "ALLOWED_CANONICAL_QUERY_PARAMS", set())


def _split(url: str):
    """Ritorna (parts, query_dict) dove parts è result di urlsplit e query_dict è lista [(k,v)]."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    return parts, query


def _rebuild(parts, query_items):
    """Ricostruisce un URL da parts (di urlsplit) e una lista [(k,v)] come query."""
    qs = urlencode(query_items, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, qs, parts.fragment))


def _strip_all_query(url: str) -> str:
    """Rimuove completamente la querystring (per canonical 'pulito')."""
    parts, _ = _split(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def _keep_only_allowed(url: str, allowed: set[str]) -> str:
    """Mantiene solo i parametri in whitelist; se vuota, rimuove tutto."""
    parts, items = _split(url)
    if not allowed:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))
    filtered = [(k, v) for k, v in items if k in allowed]
    return str(_rebuild(parts, filtered))


@register.simple_tag(takes_context=True)
def canonical_url(context):
    """
    Canonical 'pulito':
    - se ALLOWED_CANONICAL_QUERY_PARAMS è vuoto -> rimuove tutta la query
    - altrimenti tiene SOLO i parametri in whitelist
    """
    request = context["request"]
    current = request.build_absolute_uri()
    if ALLOWED_CANONICAL_QUERY_PARAMS:
        return _keep_only_allowed(current, ALLOWED_CANONICAL_QUERY_PARAMS)
    return _strip_all_query(current)


@register.simple_tag(takes_context=True)
def alternate_url(context, lang_code):
    """
    URL alternativo tradotto nella lingua richiesta.
    - usa translate_url sul CURRENT URL
    - poi mantiene SOLO i parametri in ALLOWED_ALTERNATE_QUERY_PARAMS (se vuoto -> rimuove tutto)
    """
    request = context["request"]
    current = request.build_absolute_uri()
    translated = translate_url(current, lang_code)
    return _keep_only_allowed(translated, ALLOWED_ALTERNATE_QUERY_PARAMS)
