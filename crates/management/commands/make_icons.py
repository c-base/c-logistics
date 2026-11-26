"""Generates the app icons for installing on the phone (PWA)."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from PIL import Image, ImageDraw, ImageFont

APP_DIR = Path(__file__).resolve().parent.parent.parent
ICON_DIR = APP_DIR / 'static' / 'crates' / 'icons'
FONT = APP_DIR / 'fonts' / 'Orbitron.ttf'
BACKGROUND = '#060606'
ACCENT = '#33b5e5'

# file name -> (edge length, share of the area used for the motif)
# "maskable": Android crops the icon round or rounded, so the motif
# has to stay within the inner area.
ICONS = {
    'icon-192.png': (192, 0.80),
    'icon-512.png': (512, 0.80),
    'maskable-512.png': (512, 0.58),
    'apple-touch-icon.png': (180, 0.74),
}


def placeholder(size):
    """Provisional motif without a logo: the lettering "crate" with a border like the input fields."""
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    stroke = max(2, size // 28)
    draw.rectangle([stroke // 2, size * 0.2, size - stroke // 2 - 1, size * 0.8], outline=ACCENT, width=stroke)
    font_size = size
    while True:
        font = ImageFont.truetype(str(FONT), font_size)
        font.set_variation_by_axes([900])
        left, top, right, bottom = draw.textbbox((0, 0), 'crate', font=font)
        if right - left <= size * 0.8:
            break
        font_size -= 1
    draw.text((size / 2, size / 2), 'crate', font=font, fill=ACCENT, anchor='mm')
    return image


class Command(BaseCommand):
    help = (
        'Erzeugt die App-Icons unter crates/static/crates/icons/. Mit LOGO (PNG oder '
        'anderes Rasterbild, am besten quadratisch und mindestens 512 px, mit '
        'transparentem Hintergrund) aus diesem Bild, sonst mit einem vorläufigen Schriftzug.'
    )

    def add_arguments(self, parser):
        parser.add_argument('logo', nargs='?', help='Pfad zum Logo')

    def handle(self, *args, **options):
        logo = None
        if options['logo']:
            try:
                logo = Image.open(options['logo']).convert('RGBA')
            except OSError as error:
                raise CommandError(f'Logo lässt sich nicht lesen: {error}')
            if min(logo.size) < 512:
                self.stderr.write(self.style.WARNING(
                    f'Das Logo ist nur {logo.width} × {logo.height} px groß; unter 512 px wird das Icon unscharf.'
                ))
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        for name, (size, share) in ICONS.items():
            inner = round(size * share)
            if logo:
                # Crop the transparent border and scale to the target size –
                # also upscale if the logo is smaller.
                motif = logo.crop(logo.getbbox() or (0, 0, *logo.size))
                scale = inner / max(motif.size)
                motif = motif.resize(
                    (max(1, round(motif.width * scale)), max(1, round(motif.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            else:
                motif = placeholder(inner)
            icon = Image.new('RGBA', (size, size), BACKGROUND)
            icon.alpha_composite(motif, ((size - motif.width) // 2, (size - motif.height) // 2))
            icon.convert('RGB').save(ICON_DIR / name, optimize=True)
            self.stdout.write(f'{name}: {size} × {size} px')
