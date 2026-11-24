"""Label für eine Cargo Crate: QR-Code, Schriftzug und ID – nichts, was sich ändert.

Das Label ist so breit wie das Endlosband (Querformat): Die Bildbreite ist die
Druckbreite der Rolle, die Bildhöhe die Länge des abgeschnittenen Stücks.
"""

import io
import math
from pathlib import Path

import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

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


# --- NFC-Logo ---------------------------------------------------------------
# Schriftzug „NFC“ in X-Scale, rechts daneben drei Funkwellen – dieselbe
# Zeichnung wie auf den c-base-Karten (cbag3). Es steht unter dem QR-Code und
# zeigt, dass im Label ein NFC-Tag steckt.
NFC_FONT = 'XScale.ttf'
NFC_WAVE_ANGLE = 58      # halber Öffnungswinkel der Wellen in Grad
NFC_WAVE_STROKE = 0.11   # Strichstärke, als Anteil der Logohöhe
NFC_TEXT_GAP = 0.08      # Abstand zwischen Schriftzug und Wellen
NFC_LOGO_GAP = 2         # Abstand zwischen QR-Code und Logo in Modulen


def _nfc_metrics():
    """(Breite je Höhe des Logos, Schriftgröße je Höhe, Versalhöhe je Schriftgröße)."""
    probe = ImageFont.truetype(str(FONT_DIR / NFC_FONT), 1000)
    left, top, right, bottom = probe.getbbox('NFC', anchor='ls')
    cap = -top / 1000
    text_width = (right - left) / 1000
    # Versalhöhe = halbe Logohöhe; die äußerste Welle ist so hoch wie das Logo.
    size_per_height = 0.5 / cap
    waves = 1 / (2 * math.sin(math.radians(NFC_WAVE_ANGLE)))
    return size_per_height * text_width + NFC_TEXT_GAP + waves, size_per_height, cap


def nfc_logo(width):
    """Das NFC-Logo als Schwarz-Weiß-Bild in der angegebenen Breite."""
    width_per_height, size_per_height, cap = _nfc_metrics()
    height = width / width_per_height
    image = Image.new('1', (round(width), math.ceil(height)), 1)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_DIR / NFC_FONT), height * size_per_height)
    ink_left, _, ink_right, _ = font.getbbox('NFC', anchor='ls')
    middle = height / 2
    draw.text((-ink_left, middle + cap * font.size / 2), 'NFC', font=font, fill=0, anchor='ls')
    # Mittelpunkt der Wellen kurz hinter dem C
    center = ink_right - ink_left + NFC_TEXT_GAP * height
    stroke = max(1.0, NFC_WAVE_STROKE * height)
    outer = height / (2 * math.sin(math.radians(NFC_WAVE_ANGLE))) - stroke / 2
    for radius in (0.42 * outer, 0.71 * outer, outer):
        box = [center - radius - stroke / 2, middle - radius - stroke / 2,
               center + radius + stroke / 2, middle + radius + stroke / 2]
        draw.arc(box, -NFC_WAVE_ANGLE, NFC_WAVE_ANGLE, fill=0, width=round(stroke))
        # runde Strichenden
        for sign in (-1, 1):
            x = center + radius * math.cos(math.radians(NFC_WAVE_ANGLE))
            y = middle + sign * radius * math.sin(math.radians(NFC_WAVE_ANGLE))
            draw.ellipse([x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2], fill=0)
    return image


def render_label(url, code, tape_px=None, font=None, nfc=None):
    """Zeichnet das Label als Schwarz-Weiß-Bild in voller Bandbreite.

    Links der QR-Code und darunter das NFC-Logo, rechts daneben der Schriftzug
    und die ID. Der Textblock ist genau so hoch wie die linke Spalte; beide
    zusammen füllen die Bandbreite. Mit nfc=False (oder LABEL_NFC_LOGO=0)
    entfällt das Logo, und der QR-Code wird entsprechend größer.
    """
    tape_px = tape_px or settings.LABEL_WIDTH_PX
    typeface = _Typeface(font or settings.LABEL_FONT)
    nfc = settings.LABEL_NFC_LOGO if nfc is None else nfc
    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_Q)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules
    count = len(modules)

    # Linke Spalte in Modulen: QR-Code, darunter Abstand und das Logo in QR-Breite.
    column_modules = count
    if nfc:
        column_modules += NFC_LOGO_GAP + count / _nfc_metrics()[0]
    # Der Textblock ist bei gleicher Höhe ein festes Vielfaches breiter als hoch.
    # Daraus folgt die größte ganzzahlige Modulgröße, bei der beides
    # nebeneinander auf das Band passt (ganzzahlig für scharfe Kanten im Thermodruck).
    width_per_height = 1000 / typeface.text_block(1000, code)[1]
    module_px = int(tape_px / (count + column_modules * width_per_height + 2 * EDGE + QUIET_ZONE))
    if module_px < 1:
        raise ValueError('Das Band ist zu schmal für QR-Code und Text.')
    qr_px = module_px * count
    edge = module_px * EDGE
    logo = nfc_logo(qr_px) if nfc else None
    column_px = qr_px + (module_px * NFC_LOGO_GAP + logo.height if logo else 0)
    block_width = column_px * width_per_height
    lines, _ = typeface.text_block(block_width, code)

    content_width = edge + qr_px + module_px * QUIET_ZONE + block_width + edge
    left = edge + round((tape_px - content_width) / 2)
    text_left = left + qr_px + module_px * QUIET_ZONE

    image = Image.new('1', (tape_px, column_px + 2 * edge), 1)
    draw = ImageDraw.Draw(image)
    for y, row in enumerate(modules):
        for x, dark in enumerate(row):
            if dark:
                x0, y0 = left + x * module_px, edge + y * module_px
                draw.rectangle([x0, y0, x0 + module_px - 1, y0 + module_px - 1], fill=0)
    if logo:
        image.paste(logo, (left, edge + column_px - logo.height))
    for text, line_font, baseline, features in lines:
        draw.text((text_left, edge + baseline), text, font=line_font, fill=0, anchor='ls', features=features)
    return image


def label_png(url, code, font=None):
    buffer = io.BytesIO()
    render_label(url, code, font=font).save(buffer, format='PNG', dpi=(LABEL_DPI, LABEL_DPI))
    return buffer.getvalue()


# Der Drucker kann die ersten und letzten 3 mm eines Etiketts nicht bedrucken
# (Vorschub bis zum Messer). Die PDF-Seite bekommt deshalb oben und unten
# mindestens so viel Rand, sonst schneidet der Treiber dort den Inhalt ab.
PDF_FEED_MARGIN_MM = 3


def pdf_page_mm(label_height_px):
    """Länge der PDF-Seite in ganzen Millimetern, passend für `-o PageSize=Custom.62x…mm`."""
    return math.ceil(label_height_px / LABEL_DPI * 25.4 + 2 * PDF_FEED_MARGIN_MM)


def _pdf_page(label):
    tape_px = max(label.width, round(TAPE_WIDTH_MM / 25.4 * LABEL_DPI))
    page_px = round(pdf_page_mm(label.height) / 25.4 * LABEL_DPI)
    page = Image.new('1', (tape_px, page_px), 1)
    page.paste(label, ((tape_px - label.width) // 2, (page_px - label.height) // 2))
    return page


def labels_pdf(labels, font=None):
    """Mehrere Labels als PDF, eine Seite pro Label: 62 mm breit, Etikett plus Rand für den Vorschub lang.

    `labels` ist eine Liste von (url, code). Im PDF selbst steht kein
    Schneidbefehl; der Druckertreiber schneidet nach jeder Seite (CUPS:
    BrCutLabel=1).
    """
    pages = [_pdf_page(render_label(url, code, font=font)) for url, code in labels]
    codes = ', '.join(code for _, code in labels)
    buffer = io.BytesIO()
    pages[0].save(
        buffer, format='PDF', resolution=LABEL_DPI, title=f'c-base cargo crate {codes}',
        save_all=True, append_images=pages[1:],
    )
    return buffer.getvalue()


def label_pdf(url, code, font=None):
    """Das Label als einseitiges PDF."""
    return labels_pdf([(url, code)], font=font)


# --- Brother-QL-Rasterdaten -------------------------------------------------
# Druckdatei für den QL-700 (und baugleiche QL-Drucker mit 720 Punkten
# Druckkopfbreite), die ohne Treiber roh an den Drucker geht und den
# Schneidbefehl selbst enthält. Aufbau nach Brothers „Raster Command Reference“
# (QL-500/550/560/570/580N/650TD/700/1050/1060N); die Befehlsfolge entspricht
# der des verbreiteten Werkzeugs brother_ql für Modell QL-700, Rolle „62“,
# nur ohne dessen Statusabfrage.

QL_HEAD_PX = 720  # Druckkopf: 90 Bytes je Rasterzeile
# Druckbreite in Pixeln -> (Bandbreite in mm, Abstand vom rechten Rand des Druckkopfs)
QL_ENDLESS_TAPES = {696: (62, 12), 306: (29, 6)}
QL_FEED_MARGIN = 35  # Vorschub vor und nach jedem Label in Punkten (3 mm), Vorgabe für Endlosband


def labels_ql_raster(labels, font=None):
    """Mehrere Labels als Brother-QL-Rasterdatei mit Schnitt nach jedem Label.

    `labels` ist eine Liste von (url, code). Die Datei wird unverändert an den
    Drucker geschickt, z. B. `lp -d Brother_QL-700 -o raw labels.bin`.
    """
    data = bytearray(b'\x00' * 200)  # angefangene Befehle verwerfen
    data += b'\x1b\x40'               # ESC @  Drucker zurücksetzen
    for index, (url, code) in enumerate(labels):
        label = render_label(url, code, font=font)
        if label.width not in QL_ENDLESS_TAPES:
            raise ValueError(f'Keine QL-Rolle mit {label.width} Pixeln Druckbreite bekannt (LABEL_WIDTH_PX).')
        tape_mm, offset_right = QL_ENDLESS_TAPES[label.width]
        # ESC i z: Medium. 0xCE = Typ, Breite und Länge gültig, Drucker soll sie prüfen,
        # Qualität vor Geschwindigkeit; 0x0A = Endlosband, Länge 0; danach
        # Zeilenzahl und „erste Seite?“.
        data += b'\x1b\x69\x7a' + bytes([0xCE, 0x0A, tape_mm, 0])
        data += label.height.to_bytes(4, 'little') + bytes([0 if index == 0 else 1, 0])
        data += b'\x1b\x69\x4d\x40'  # ESC i M: automatisch schneiden
        data += b'\x1b\x69\x41\x01'  # ESC i A: nach jedem Label
        data += b'\x1b\x69\x4b\x08'  # ESC i K: auch nach dem letzten schneiden
        data += b'\x1b\x69\x64' + QL_FEED_MARGIN.to_bytes(2, 'little')  # ESC i d: Vorschub
        # Der Drucker erwartet die Zeile von rechts nach links; 1 = schwarz.
        line = Image.new('1', (QL_HEAD_PX, label.height), 1)
        mirrored = label.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        line.paste(mirrored, (QL_HEAD_PX - label.width - offset_right, 0))
        raster = ImageOps.invert(line.convert('L')).convert('1').tobytes()
        row_bytes = QL_HEAD_PX // 8
        for row in range(label.height):
            data += b'\x67\x00' + bytes([row_bytes]) + raster[row * row_bytes:(row + 1) * row_bytes]
        # SUB: drucken und vorschieben – nach jedem Label, damit es einzeln
        # abgeschnitten herauskommt.
        data += b'\x1a'
    return bytes(data)
