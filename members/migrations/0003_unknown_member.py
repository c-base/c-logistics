from django.db import migrations

UNKNOWN_USERNAME = 'unbecannt'


def create_unknown(apps, schema_editor):
    Member = apps.get_model('members', 'Member')
    Member.objects.get_or_create(
        username=UNKNOWN_USERNAME,
        # '!' = kein gültiges Passwort; zusammen mit is_active=False ist keine Anmeldung möglich
        defaults={'password': '!', 'is_active': False},
    )


class Migration(migrations.Migration):
    dependencies = [('members', '0002_member_oidc_sub')]

    operations = [migrations.RunPython(create_unknown, migrations.RunPython.noop)]
