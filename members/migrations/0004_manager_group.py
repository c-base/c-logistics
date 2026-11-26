from django.db import migrations

MANAGER_GROUP = 'Manager'


def create_group(apps, schema_editor):
    """The "Manager" role is a group; who belongs to it is set in the admin."""
    apps.get_model('auth', 'Group').objects.get_or_create(name=MANAGER_GROUP)


class Migration(migrations.Migration):
    dependencies = [('members', '0003_unknown_member'), ('auth', '0012_alter_user_first_name_max_length')]

    operations = [migrations.RunPython(create_group, migrations.RunPython.noop)]
