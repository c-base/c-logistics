from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone
from reversion.models import Version

from crates.models import Photo


# An upload stores the files a moment before its entry exists in the database.
# Files this young are left alone, so that a running upload never loses them.
MIN_AGE = timedelta(hours=1)


class Command(BaseCommand):
    help = (
        'Löscht Fotodateien, die weder eine Crate noch ein Stand im Verlauf mehr zeigt '
        'und die älter als eine Stunde sind. '
        'Vorher alte Stände entfernen, z. B. mit "deleterevisions crates --days 180".'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Nur anzeigen, was gelöscht würde.')

    def handle(self, *args, dry_run=False, **options):
        storage = Photo._meta.get_field('image').storage
        used = set()
        for image, thumbnail in Photo.objects.values_list('image', 'thumbnail'):
            used.update((image, thumbnail))
        for version in Version.objects.filter(content_type=ContentType.objects.get_for_model(Photo)).iterator():
            data = version.field_dict
            used.update(str(data.get(name) or '') for name in ('image', 'thumbnail'))

        def files(folder):
            try:
                folders, names = storage.listdir(folder)
            except FileNotFoundError:
                return
            yield from (f'{folder}/{name}' for name in names)
            for sub in folders:
                yield from files(f'{folder}/{sub}')

        def old_enough(name):
            try:
                modified = storage.get_modified_time(name)
            except FileNotFoundError:
                return False
            if timezone.is_naive(modified):
                modified = timezone.make_aware(modified)
            return timezone.now() - modified >= MIN_AGE

        unused = [name for name in files('crates') if name not in used and old_enough(name)]
        for name in unused:
            if dry_run:
                self.stdout.write(name)
            else:
                storage.delete(name)
        self.stdout.write(f'{len(unused)} Datei{"en" if len(unused) != 1 else ""} {"würden gelöscht" if dry_run else "gelöscht"}.')
