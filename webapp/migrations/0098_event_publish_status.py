from django.db import migrations, models

# Events used to wait for an admin's approval; now their managers publish them.
STATUS_MAP = {'pending': 'draft', 'approved': 'published', 'rejected': 'blocked'}


def forwards(apps, schema_editor):
    Event = apps.get_model('webapp', 'Event')
    for old, new in STATUS_MAP.items():
        Event.objects.filter(status=old).update(status=new)


def backwards(apps, schema_editor):
    Event = apps.get_model('webapp', 'Event')
    for old, new in STATUS_MAP.items():
        Event.objects.filter(status=new).update(status=old)


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0097_normalize_network_logos'),
    ]

    operations = [
        migrations.AlterField(
            model_name='event',
            name='status',
            field=models.CharField(
                choices=[('draft', 'Draft'), ('published', 'Published'), ('blocked', 'Blocked')],
                default='draft', max_length=20, verbose_name='Status'),
        ),
        migrations.RunPython(forwards, backwards),
    ]
