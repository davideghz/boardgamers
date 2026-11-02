import random
import string

from django.db import migrations


def fix_empty_slugs(apps, schema_editor):
    """Rows whose name/title slugified to '' (emoji or non-latin only) got an empty slug."""
    for model_name in ('Game', 'Location', 'UserProfile', 'Table', 'Event'):
        model = apps.get_model('webapp', model_name)
        base = model_name.lower()
        for obj in model.objects.filter(slug=''):
            slug = base
            while model.objects.filter(slug=slug).exists():
                slug = f"{base}-{''.join(random.choice(string.ascii_lowercase) for _ in range(6))}"
            model.objects.filter(pk=obj.pk).update(slug=slug)


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0080_location_enable_public_games_default_on'),
    ]

    operations = [
        migrations.RunPython(fix_empty_slugs, migrations.RunPython.noop),
    ]
