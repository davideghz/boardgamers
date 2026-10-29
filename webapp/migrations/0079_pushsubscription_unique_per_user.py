from django.db import migrations, models


def delete_duplicate_subscriptions(apps, schema_editor):
    """Keep only the most recent row for each (user_profile, endpoint) pair."""
    PushSubscription = apps.get_model('webapp', 'PushSubscription')
    seen = set()
    for sub in PushSubscription.objects.order_by('user_profile_id', 'endpoint', '-id'):
        key = (sub.user_profile_id, sub.endpoint)
        if key in seen:
            sub.delete()
        else:
            seen.add(key)


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0078_drop_location_is_public'),
    ]

    operations = [
        migrations.RunPython(delete_duplicate_subscriptions, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='pushsubscription',
            constraint=models.UniqueConstraint(
                fields=('user_profile', 'endpoint'), name='unique_push_subscription_per_user'),
        ),
    ]
