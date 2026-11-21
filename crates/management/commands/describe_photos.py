from django.core.management.base import BaseCommand, CommandError

from crates import describe
from crates.models import Photo


class Command(BaseCommand):
    help = 'Lässt die KI alle Fotos beschreiben, die noch keine Beschreibung haben.'

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='auch schon beschriebene Fotos neu beschreiben')
        parser.add_argument('--crate', help='nur die Fotos dieser Crate (ID, z. B. 001A)')

    def handle(self, *args, **options):
        if not describe.enabled():
            raise CommandError('AI_BASE_URL ist nicht gesetzt.')
        photos = Photo.objects.select_related('crate').order_by('pk')
        if not options['all']:
            photos = photos.filter(description='')
        if options['crate']:
            photos = photos.filter(crate__code=options['crate'].upper().zfill(4))
        failed = 0
        for photo in photos:
            if describe.describe_photo(photo):
                self.stdout.write(f'{photo}: {photo.description}')
            else:
                failed += 1
                self.stderr.write(f'{photo}: keine Beschreibung')
        if failed:
            raise CommandError(f'{failed} Foto(s) ohne Beschreibung, siehe oben.')
