import uuid
from django.db import migrations, models


def populate_member_uuids(apps, schema_editor):
    Member = apps.get_model('webapp', 'Member')
    for obj in Member.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


def populate_membership_uuids(apps, schema_editor):
    Membership = apps.get_model('webapp', 'Membership')
    for obj in Membership.objects.all():
        obj.uuid = uuid.uuid4()
        obj.save(update_fields=['uuid'])


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0027_table_leaderboard_default_not_editable'),
    ]

    operations = [
        # Member: add nullable, populate, then make unique+non-null
        migrations.AddField(
            model_name='member',
            name='uuid',
            field=models.UUIDField(db_index=True, null=True, editable=False),
        ),
        migrations.RunPython(populate_member_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='member',
            name='uuid',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
        ),
        # Membership: same pattern
        migrations.AddField(
            model_name='membership',
            name='uuid',
            field=models.UUIDField(db_index=True, null=True, editable=False),
        ),
        migrations.RunPython(populate_membership_uuids, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='membership',
            name='uuid',
            field=models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
