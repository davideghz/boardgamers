import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations
from django.utils import timezone

# Every location starts at the 2-day default (0075). Tables still editable under the
# old 7-day window would be locked by the next update_table_status run through save(),
# sending a "leaderboard locked" notification to each player: lock them here instead,
# with a queryset update so no signals fire.
DEFAULT_DAYS = 2


def lock_silently(apps, schema_editor):
    Table = apps.get_model('webapp', 'Table')
    tz = ZoneInfo(settings.TIME_ZONE)
    now = timezone.now()
    expired = [
        pk for pk, date, time in Table.objects.filter(
            status='closed', leaderboard_status='editable',
        ).values_list('pk', 'date', 'time')
        if now >= datetime.datetime.combine(date, time, tzinfo=tz) + datetime.timedelta(days=DEFAULT_DAYS)
    ]
    Table.objects.filter(pk__in=expired).update(leaderboard_status='not_editable')


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0075_leaderboard_settings'),
    ]

    operations = [
        migrations.RunPython(lock_silently, migrations.RunPython.noop),
    ]
