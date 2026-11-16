from django.db import migrations

DEV_NULL_CODE = '0000'


def create_dev_null(apps, schema_editor):
    Crate = apps.get_model('crates', 'Crate')
    Crate.objects.get_or_create(
        code=DEV_NULL_CODE,
        defaults={'name': '/dev/null', 'description': 'Die Mülltonne.', 'size': 'other'},
    )


class Migration(migrations.Migration):
    dependencies = [('crates', '0001_initial')]

    operations = [migrations.RunPython(create_dev_null, migrations.RunPython.noop)]
