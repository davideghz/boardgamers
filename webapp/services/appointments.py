from django.core.paginator import Paginator
from django.db.models import Exists, F, Subquery, Value


SCHEDULE_FIELDS = {
    'table': ('date', 'time'),
    'event': ('matching_date', 'matching_time'),
    'manifestation': ('matching_date', 'matching_time'),
}


def with_matching_day(items, days, *, newest_first, undated=None):
    dates = days.order_by('-date' if newest_first else 'date')
    matching = Exists(dates)
    if undated is not None:
        matching |= Exists(undated)
    return items.filter(matching).annotate(
        matching_date=Subquery(dates.values('date')[:1]),
        matching_time=Subquery(dates.values('opening_time')[:1]),
    )


def paginate_appointments(querysets, page_number, *, newest_first):
    """Page over dates and IDs, then load full cards for that page."""
    rows = []
    for kind, queryset in querysets.items():
        date_field, time_field = SCHEDULE_FIELDS[kind]
        rows.append(queryset.order_by().annotate(
            result_date=F(date_field), result_time=F(time_field), result_kind=Value(kind),
        ).values('pk', 'result_date', 'result_time', 'result_kind'))

    results = rows[0].union(*rows[1:], all=True) if len(rows) > 1 else rows[0]
    date = F('result_date')
    time = F('result_time')
    ordering = (date.desc(nulls_last=True), time.desc(nulls_last=True)) if newest_first else (
        date.asc(nulls_last=True), time.asc(nulls_last=True),
    )
    paginator = Paginator(results.order_by(*ordering, 'result_kind', 'pk'), 15)
    page = paginator.get_page(page_number)
    ids = {kind: [] for kind in querysets}
    for row in page.object_list:
        ids[row['result_kind']].append(row['pk'])
    objects = {kind: queryset.order_by().in_bulk(ids[kind]) for kind, queryset in querysets.items()}

    items = []
    for row in page.object_list:
        kind = row['result_kind']
        item = objects[kind].get(row['pk'])
        if item is not None:
            item.matching_date = row['result_date']
            item.matching_time = row['result_time']
            items.append((kind, item))
    return page, items
