from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0045_telegram_group_config_thread_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='location',
            name='opening_hours',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
