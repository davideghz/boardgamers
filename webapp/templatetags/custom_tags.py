from django import template
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
