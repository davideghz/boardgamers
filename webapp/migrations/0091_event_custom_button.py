from django.db import migrations, models


def external_program_to_custom_button(apps, schema_editor):
    # The external program link becomes a custom button with the old label.
    Event = apps.get_model('webapp', 'Event')
    Event.objects.exclude(custom_button_url='').update(
        custom_button_title='Vedi il programma',
        custom_button_subtitle='Apre il sito degli organizzatori')


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0090_use_default_media_storage'),
    ]

    operations = [
        migrations.RenameField(
            model_name='event',
            old_name='external_program_url',
            new_name='custom_button_url',
        ),
        migrations.AlterField(
            model_name='event',
            name='custom_button_url',
            field=models.URLField(blank=True, db_default='', default='', max_length=500, verbose_name='Button link'),
        ),
        migrations.AddField(
            model_name='event',
            name='custom_button_title',
            field=models.CharField(blank=True, db_default='', default='', max_length=80, verbose_name='Button title'),
        ),
        migrations.AddField(
            model_name='event',
            name='custom_button_subtitle',
            field=models.CharField(blank=True, db_default='', default='', max_length=160, verbose_name='Button subtitle'),
        ),
        migrations.RunPython(external_program_to_custom_button, migrations.RunPython.noop),
    ]
