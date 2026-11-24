from collections import defaultdict
from datetime import timedelta

from django.db.models import Q

from webapp.models import Table


def station_conflict_ids(tables, *, public_only=False):
    """Return the given tables' IDs when another session overlaps at their station."""
    scheduled = [table for table in tables if table.physical_table_id and table.duration > 0]
    if not scheduled:
        return set()

    by_station = defaultdict(list)
    for table in scheduled:
        by_station[table.physical_table_id].append(table)

    previous_day = min(table.date for table in scheduled) - timedelta(days=1)
    last_day = max(table.end_datetime.date() for table in scheduled)
    # Sessions that started earlier can only reach the window if they last over a day.
    candidates = Table.objects.filter(
        Q(date__gte=previous_day) | Q(duration__gt=24 * 60),
        date__lte=last_day, physical_table_id__in=by_station, duration__gt=0,
    )
    if public_only:
        candidates = candidates.filter(Table.public_condition())

    conflicts = set()
    for other in candidates.only('date', 'time', 'duration', 'physical_table_id').order_by().iterator():
        for table in by_station[other.physical_table_id]:
            if table.pk not in conflicts and table.pk != other.pk and table.overlaps_with(other):
                conflicts.add(table.pk)
    return conflicts
