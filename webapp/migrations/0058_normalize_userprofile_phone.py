# Best-effort normalization of existing UserProfile.phone values to E.164.
#
# Legacy values were free text. We re-parse each one assuming the Italian
# region (numbers without an international prefix), and rewrite it in E.164
# when it parses to a valid number. Anything that cannot be parsed is left
# untouched (the user can fix it on the next profile edit). Non-destructive.

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
            "SELECT id, phone FROM webapp_userprofile "
            "WHERE phone IS NOT NULL AND phone <> ''"
        )
        rows = cursor.fetchall()
        for pk, raw in rows:
            e164 = _to_e164(raw)
            if e164 and e164 != raw:
                cursor.execute(
                    "UPDATE webapp_userprofile SET phone = %s WHERE id = %s",
                    [e164, pk],
                )


class Migration(migrations.Migration):

    dependencies = [
        ('webapp', '0057_alter_userprofile_phone'),
    ]

    operations = [
        migrations.RunPython(normalize_phones, migrations.RunPython.noop),
    ]
