# Best-effort normalization of existing Member.phone_number values to E.164,
# mirroring the UserProfile (0058) and Event (0060) migrations. Legacy free-text
# values are re-parsed assuming the Italian region and rewritten in E.164 when
# valid; anything that cannot be parsed is left untouched. Non-destructive.

import phonenumbers
from django.db import migrations


def _to_e164(raw, region='IT'):
    if not raw:
        return None
    try:
        number = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException:
        return None
    if phonenumbers.is_valid_number(number):
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
    return None


def normalize_phones(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, phone_number FROM webapp_member "
            "WHERE phone_number IS NOT NULL AND phone_number <> ''"
        )
        rows = cursor.fetchall()
        for pk, raw in rows:
            e164 = _to_e164(raw)
            if e164 and e164 != raw:
                cursor.execute(
                    "UPDATE webapp_member SET phone_number = %s WHERE id = %s",
                    [e164, pk],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0061_alter_member_phone_number'),
    ]

    operations = [
        migrations.RunPython(normalize_phones, migrations.RunPython.noop),
    ]
