from django.db import migrations


def assign_unknown(apps, schema_editor):
    """Crates ohne Verantwortliche (z. B. 0000) bekommen den Platzhalter „unbecannt“."""
    Crate = apps.get_model('crates', 'Crate')
    Member = apps.get_model('members', 'Member')
    unknown = Member.objects.get(username='unbecannt')
    for crate in Crate.objects.filter(responsible__isnull=True):
        crate.responsible.add(unknown)


class Migration(migrations.Migration):
    dependencies = [('crates', '0003_photo'), ('members', '0003_unknown_member')]

    operations = [migrations.RunPython(assign_unknown, migrations.RunPython.noop)]
