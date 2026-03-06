from django import template
from django.urls import translate_url, reverse
from django.utils.translation import get_language
from urllib.parse import urlencode

register = template.Library()


@register.inclusion_tag("tags/table_card.html")
def table_list_item(table):
    return {
        'table': table,
    }


@register.inclusion_tag("tags/swiper_table_slide.html")
def swiper_table_slide(table):
    return {
        'table': table,
    }


@register.inclusion_tag("tags/v2_table_card.html")
def v2_table_card(table):
    return {
        'table': table,
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
