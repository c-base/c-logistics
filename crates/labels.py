"""Label für eine Cargo Crate: QR-Code, Schriftzug und ID – nichts, was sich ändert.

Das Label ist so breit wie das Endlosband (Querformat): Die Bildbreite ist die
Druckbreite der Rolle, die Bildhöhe die Länge des abgeschnittenen Stücks.
"""

import io
from pathlib import Path

import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

LABEL_DPI = 300
TAPE_WIDTH_MM = 62  # Brother-DK-Endlosrolle; bedruckbar sind davon 696 Pixel (ca. 59 mm)
QUIET_ZONE = 4  # Module Abstand zwischen QR-Code und Text, laut QR-Spezifikation
# Rand im Bild in Modulen. Der Rest der Ruhezone kommt vom Drucker: Das Band ist
# breiter als der Druckbereich, und vor und nach jedem Etikett gibt es Vorschub.
EDGE = 2
FONT_DIR = Path(__file__).resolve().parent / 'fonts'
TOP_LINE = 'c-base cargo'
MIDDLE_LINE = 'crate'
HEX_DIGITS = '0123456789ABCDEF'

# `axes` stellt variable Schriften ein, `features` schaltet OpenType-Varianten zu
# (bei Anybody die Null mit Querbalken). `code_font` setzt die ID in einer
# anderen Schrift: Bai Jamjuree unterscheidet 0 und O kaum, Orbitron streicht
# die Null durch.
FONTS = {
    'baijamjuree': {'file': 'BaiJamjuree-Bold.ttf', 'axes': {}, 'features': [], 'code_font': 'orbitron'},
    'orbitron': {'file': 'Orbitron.ttf', 'axes': {'Weight': 900}, 'features': []},
    'anybody': {'file': 'Anybody.ttf', 'axes': {'Width': 150, 'Weight': 800}, 'features': ['zero']},
}


def public_url(crate, request=None):
    """Die URL, die im NFC-Tag und im QR-Code steht."""
    path = crate.get_absolute_url()
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL + path
    return request.build_absolute_uri(path) if request else path


class _Typeface:
    def __init__(self, name):
        self.spec = FONTS[name]
        # OpenType-Features gibt es nur mit der Raqm-Textausgabe.
        self.features = self.spec['features'] or None
        self.engine = ImageFont.Layout.RAQM if self.features else ImageFont.Layout.BASIC
        code_font = self.spec.get('code_font')
        self.code_face = _Typeface(code_font) if code_font else self

    def font(self, size):
        font = ImageFont.truetype(str(FONT_DIR / self.spec['file']), max(1.0, size), layout_engine=self.engine)
        if self.spec['axes']:
            values = []
            for axis in font.get_variation_axes():
                name = axis['name'].decode() if isinstance(axis['name'], bytes) else axis['name']
                values.append(self.spec['axes'].get(name, axis['default']))
            font.set_variation_by_axes(values)
        return font

    def width(self, font, text):
        return font.getlength(text, features=self.features)

    def ink(self, font, text):
        """Höhe über und Tiefe unter der Grundlinie, die der Text tatsächlich einfärbt."""
        _, top, _, bottom = font.getbbox(text, anchor='ls', features=self.features)
        return -top, max(0, bottom)

    def text_block(self, block_width, code):
        """Die drei Zeilen als (Text, Schrift, Grundlinie, Features) und die Gesamthöhe des Blocks.

        Oben klein „c-base cargo“, darunter „crate“, darunter die ID – jede Zeile
        füllt die Blockbreite, kürzere Zeilen werden dadurch größer. Die ID richtet
        sich nach der breitesten Ziffer, damit sie auf allen Labels gleich groß ist.
        """
        probe = self.font(1000)
        top_font = self.font(1000 * block_width / self.width(probe, TOP_LINE))
        middle_font = self.font(1000 * block_width / self.width(probe, MIDDLE_LINE))
        code_face = self.code_face
        code_probe = code_face.font(1000)
        code_font = code_face.font(
            1000 * block_width / max(code_face.width(code_probe, digit * 4) for digit in HEX_DIGITS)
        )

        top_up, top_down = self.ink(top_font, TOP_LINE)
        middle_up, middle_down = self.ink(middle_font, MIDDLE_LINE)
        code_up, _ = code_face.ink(code_font, '0')
        top_baseline = top_up
        middle_baseline = top_baseline + top_down + 0.45 * top_up + middle_up
        code_baseline = middle_baseline + middle_down + 0.25 * middle_up + code_up
        lines = [
            (TOP_LINE, top_font, top_baseline, self.features),
            (MIDDLE_LINE, middle_font, middle_baseline, self.features),
            (code, code_font, code_baseline, code_face.features),
        ]
        return lines, code_baseline


def render_label(url, code, tape_px=None, font=None):
    """Zeichnet das Label als Schwarz-Weiß-Bild in voller Bandbreite.

    Links der QR-Code, rechts daneben der Schriftzug und die ID. Der Textblock
    ist genau so hoch wie der QR-Code; beide zusammen füllen die Bandbreite.
    """
    tape_px = tape_px or settings.LABEL_WIDTH_PX
    typeface = _Typeface(font or settings.LABEL_FONT)
    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules
    count = len(modules)

    # Der Textblock ist bei gleicher Höhe ein festes Vielfaches breiter als der
    # QR-Code. Daraus folgt die größte ganzzahlige Modulgröße, bei der beides
    # nebeneinander auf das Band passt (ganzzahlig für scharfe Kanten im Thermodruck).
    width_per_height = 1000 / typeface.text_block(1000, code)[1]
    module_px = int(tape_px / (count * (1 + width_per_height) + 2 * EDGE + QUIET_ZONE))
    if module_px < 1:
        raise ValueError('Das Band ist zu schmal für QR-Code und Text.')
    qr_px = module_px * count
    edge = module_px * EDGE
    block_width = qr_px * width_per_height
    lines, _ = typeface.text_block(block_width, code)

    content_width = edge + qr_px + module_px * QUIET_ZONE + block_width + edge
    left = edge + round((tape_px - content_width) / 2)
    text_left = left + qr_px + module_px * QUIET_ZONE

    image = Image.new('1', (tape_px, qr_px + 2 * edge), 1)
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(modules):
        for x, dark in enumerate(row):
            if dark:
                x0, y0 = left + x * module_px, edge + y * module_px
                draw.rectangle([x0, y0, x0 + module_px - 1, y0 + module_px - 1], fill=0)
    for text, line_font, baseline, features in lines:
        draw.text((text_left, edge + baseline), text, font=line_font, fill=0, anchor='ls', features=features)
    return image


def label_png(url, code, font=None):
    buffer = io.BytesIO()
    render_label(url, code, font=font).save(buffer, format='PNG', dpi=(LABEL_DPI, LABEL_DPI))
    return buffer.getvalue()


def label_pdf(url, code, font=None):
    """Das Label als einseitiges PDF: 62 mm breit, so hoch wie das Etikett lang ist."""
    label = render_label(url, code, font=font)
    tape_px = max(label.width, round(TAPE_WIDTH_MM / 25.4 * LABEL_DPI))
    page = Image.new('1', (tape_px, label.height), 1)
    page.paste(label, ((tape_px - label.width) // 2, 0))
    buffer = io.BytesIO()
    page.save(buffer, format='PDF', resolution=LABEL_DPI, title=f'c-base cargo crate {code}')
    return buffer.getvalue()
