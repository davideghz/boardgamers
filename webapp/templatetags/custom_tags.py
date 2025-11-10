from django import template
from django.urls import translate_url

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
