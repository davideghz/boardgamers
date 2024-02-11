from django import template
register = template.Library()


@register.inclusion_tag("tags/table_card.html")
def table_list_item(table):
    return {
        'table': table,
    }
