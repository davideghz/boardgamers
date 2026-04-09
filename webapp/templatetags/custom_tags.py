import mistune
import nh3

from django import template
from django.urls import translate_url, reverse
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from urllib.parse import urlencode

register = template.Library()

_ALLOWED_TAGS = {"p", "strong", "em", "ul", "ol", "li", "br"}


@register.filter
def km(value):
    """Convert a GeoDjango Distance (or plain meters float) to a formatted km string."""
    try:
        meters = value.m  # GeoDjango Distance object
    except AttributeError:
        meters = float(value)
    return f"{meters / 1000:.1f}".replace(".", ",")


@register.filter
def render_markdown(value):
    if not value:
        return ""
    html = mistune.html(value)
    clean = nh3.clean(html, tags=_ALLOWED_TAGS)
    return mark_safe(clean)



@register.inclusion_tag("tags/location_card.html", takes_context=True)
def location_card(context, location):
    followed_ids = context.get('followed_location_ids', set())
    return {
        'location': location,
        'is_followed': location.id in followed_ids,
    }


@register.inclusion_tag("tags/table_card.html")
def table_card(table):
    return {
        'table': table,
    }


@register.inclusion_tag("tags/event_table_card.html")
def event_table_card(table):
    return {'table': table}


@register.inclusion_tag("tags/horizontal_table_card.html", takes_context=True)
def horizontal_table_card(context, table, show_author_icon=False):
    return {
        'table': table,
        'user': context.get('user'),
        'show_author_icon': show_author_icon,
    }


@register.simple_tag(takes_context=True)
def alternate_url(context, lang_code):
    request = context["request"]
    current_url = request.build_absolute_uri()
    return translate_url(current_url, lang_code)


@register.simple_tag(takes_context=True)
def canonical_url(context):
    """Restituisce l'URL canonico nella lingua corrente."""
    request = context["request"]
    return request.build_absolute_uri()


@register.simple_tag(takes_context=True)
def social_auth_url(context, backend):
    """
    Genera l'URL per l'autenticazione social con la lingua corrente salvata nello state.
    Questo permette di preservare la lingua dell'utente durante il flusso OAuth
    senza dover configurare redirect URI multipli in Google Console.
    
    Usage: {% social_auth_url 'google-oauth2' %}
    """
    from django.utils.translation import get_language, override
    
    current_lang = get_language()
    
    # Forza la generazione di un URL non localizzato
    # usando override(None) per disattivare temporaneamente i18n
    with override(None):
        base_url = reverse('social:begin', args=[backend])
    
    # Aggiungi la lingua come parametro 'lang'
    # La custom view auth_with_language lo salverà nella sessione
    params = {'lang': current_lang}
    
    return f"{base_url}?{urlencode(params)}"
