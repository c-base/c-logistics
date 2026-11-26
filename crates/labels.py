"""Label for a cargo crate: QR code, lettering and ID – nothing that changes.

The label is as wide as the continuous tape (landscape): the image width is the
print width of the roll, the image height the length of the piece cut off.
"""

import io
import math
from pathlib import Path

import qrcode
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

LABEL_DPI = 300
TAPE_WIDTH_MM = 62  # Brother DK continuous roll; 696 pixels (approx. 59 mm) of it are printable
QUIET_ZONE = 4  # modules of space between QR code and text, per the QR specification
# Margin in the image, in modules. The rest of the quiet zone comes from the
# printer: the tape is wider than the print area, and there is feed before and after each label.
EDGE = 2
FONT_DIR = Path(__file__).resolve().parent / 'fonts'
TOP_LINE = 'c-base cargo'
MIDDLE_LINE = 'crate'
HEX_DIGITS = '0123456789ABCDEF'

# `axes` sets up variable fonts, `features` switches on OpenType variants
# (for Anybody the slashed zero). `code_font` sets the ID in a different
# font: Bai Jamjuree barely distinguishes 0 and O, Orbitron strikes
# through the zero.
FONTS = {
    'baijamjuree': {'file': 'BaiJamjuree-Bold.ttf', 'axes': {}, 'features': [], 'code_font': 'orbitron'},
    'orbitron': {'file': 'Orbitron.ttf', 'axes': {'Weight': 900}, 'features': []},
    'anybody': {'file': 'Anybody.ttf', 'axes': {'Width': 150, 'Weight': 800}, 'features': ['zero']},
}


def public_url(crate, request=None):
    """The URL stored in the NFC tag and the QR code."""
    path = crate.get_absolute_url()
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL + path
    return request.build_absolute_uri(path) if request else path


class _Typeface:
    def __init__(self, name):
        self.spec = FONTS[name]
        # OpenType features are only available with the Raqm text layout.
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
        """Height above and depth below the baseline that the text actually inks."""
        _, top, _, bottom = font.getbbox(text, anchor='ls', features=self.features)
        return -top, max(0, bottom)

    def text_block(self, block_width, code):
        """The three lines as (text, font, baseline, features) and the total height of the block.

        On top, small, "c-base cargo", below it "crate", below that the ID – every line
        fills the block width, so shorter lines come out larger. The ID is sized for
        the widest digit so that it is the same size on all labels.
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


# --- NFC logo ---------------------------------------------------------------
# The lettering "NFC" in X-Scale, with three radio waves to its right – the same
# drawing as on the c-base cards (cbag3). It sits below the QR code and
# shows that the label contains an NFC tag.
NFC_FONT = 'XScale.ttf'
NFC_WAVE_ANGLE = 58      # half opening angle of the waves in degrees
NFC_WAVE_STROKE = 0.11   # stroke width, as a fraction of the logo height
NFC_TEXT_GAP = 0.08      # gap between lettering and waves
NFC_LOGO_GAP = 2         # gap between QR code and logo in modules


def _nfc_metrics():
    """(width per height of the logo, font size per height, cap height per font size)."""
    probe = ImageFont.truetype(str(FONT_DIR / NFC_FONT), 1000)
    left, top, right, bottom = probe.getbbox('NFC', anchor='ls')
    cap = -top / 1000
    text_width = (right - left) / 1000
    # Cap height = half the logo height; the outermost wave is as tall as the logo.
    size_per_height = 0.5 / cap
    waves = 1 / (2 * math.sin(math.radians(NFC_WAVE_ANGLE)))
    return size_per_height * text_width + NFC_TEXT_GAP + waves, size_per_height, cap


def nfc_logo(width):
    """The NFC logo as a black-and-white image of the given width."""
    width_per_height, size_per_height, cap = _nfc_metrics()
    height = width / width_per_height
    image = Image.new('1', (round(width), math.ceil(height)), 1)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT_DIR / NFC_FONT), height * size_per_height)
    ink_left, _, ink_right, _ = font.getbbox('NFC', anchor='ls')
    middle = height / 2
    draw.text((-ink_left, middle + cap * font.size / 2), 'NFC', font=font, fill=0, anchor='ls')
    # centre of the waves just behind the C
    center = ink_right - ink_left + NFC_TEXT_GAP * height
    stroke = max(1.0, NFC_WAVE_STROKE * height)
    outer = height / (2 * math.sin(math.radians(NFC_WAVE_ANGLE))) - stroke / 2
    for radius in (0.42 * outer, 0.71 * outer, outer):
        box = [center - radius - stroke / 2, middle - radius - stroke / 2,
               center + radius + stroke / 2, middle + radius + stroke / 2]
        draw.arc(box, -NFC_WAVE_ANGLE, NFC_WAVE_ANGLE, fill=0, width=round(stroke))
        # round stroke ends
        for sign in (-1, 1):
            x = center + radius * math.cos(math.radians(NFC_WAVE_ANGLE))
            y = middle + sign * radius * math.sin(math.radians(NFC_WAVE_ANGLE))
            draw.ellipse([x - stroke / 2, y - stroke / 2, x + stroke / 2, y + stroke / 2], fill=0)
    return image


def render_label(url, code, tape_px=None, font=None, nfc=None):
    """Draws the label as a black-and-white image across the full tape width.

    On the left the QR code with the NFC logo below it, to the right the lettering
    and the ID. The text block is exactly as tall as the left column; together
    they fill the tape width. With nfc=False (or LABEL_NFC_LOGO=0) the logo is
    left out and the QR code becomes correspondingly larger.
    """
    tape_px = tape_px or settings.LABEL_WIDTH_PX
    typeface = _Typeface(font or settings.LABEL_FONT)
    nfc = settings.LABEL_NFC_LOGO if nfc is None else nfc
    qr = qrcode.QRCode(border=0, error_correction=qrcode.constants.ERROR_CORRECT_Q)
    qr.add_data(url)
    qr.make(fit=True)
    modules = qr.modules
    count = len(modules)

    # Left column in modules: QR code, below it a gap and the logo at QR width.
    column_modules = count
    if nfc:
        column_modules += NFC_LOGO_GAP + count / _nfc_metrics()[0]
    # At equal height the text block is a fixed multiple wider than tall.
    # This gives the largest integer module size at which both fit side by
    # side on the tape (integer for crisp edges in thermal printing).
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


# The printer cannot print on the first and last 3 mm of a label
# (feed up to the cutter). The PDF page therefore gets at least that much
# margin at top and bottom, otherwise the driver cuts off the content there.
PDF_FEED_MARGIN_MM = 3


def pdf_page_mm(label_height_px):
    """Length of the PDF page in whole millimetres, suitable for `-o PageSize=Custom.62x…mm`."""
    return math.ceil(label_height_px / LABEL_DPI * 25.4 + 2 * PDF_FEED_MARGIN_MM)


def _pdf_page(label):
    tape_px = max(label.width, round(TAPE_WIDTH_MM / 25.4 * LABEL_DPI))
    page_px = round(pdf_page_mm(label.height) / 25.4 * LABEL_DPI)
    page = Image.new('1', (tape_px, page_px), 1)
    page.paste(label, ((tape_px - label.width) // 2, (page_px - label.height) // 2))
    return page


def labels_pdf(labels, font=None):
    """Several labels as a PDF, one page per label: 62 mm wide, label plus feed margin long.

    `labels` is a list of (url, code). The PDF itself contains no cut
    command; the printer driver cuts after every page (CUPS:
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
    """The label as a single-page PDF."""
    return labels_pdf([(url, code)], font=font)


# --- Brother QL raster data -------------------------------------------------
# Print file for the QL-700 (and identical QL printers with a 720-dot
# print head) that goes to the printer raw, without a driver, and contains
# the cut command itself. Structure follows Brother's "Raster Command Reference"
# (QL-500/550/560/570/580N/650TD/700/1050/1060N); the command sequence matches
# that of the widespread tool brother_ql for model QL-700, roll "62",
# just without its status request.

QL_HEAD_PX = 720  # print head: 90 bytes per raster line
# print width in pixels -> (tape width in mm, offset from the right edge of the print head)
QL_ENDLESS_TAPES = {696: (62, 12), 306: (29, 6)}
QL_FEED_MARGIN = 35  # feed before and after each label in dots (3 mm), the default for continuous tape


def labels_ql_raster(labels, font=None):
    """Several labels as a Brother QL raster file with a cut after each label.

    `labels` is a list of (url, code). The file is sent to the printer
    unchanged, e.g. `lp -d Brother_QL-700 -o raw labels.bin`.
    """
    data = bytearray(b'\x00' * 200)  # discard commands in progress
    data += b'\x1b\x40'               # ESC @  reset the printer
    for index, (url, code) in enumerate(labels):
        label = render_label(url, code, font=font)
        if label.width not in QL_ENDLESS_TAPES:
            raise ValueError(f'Keine QL-Rolle mit {label.width} Pixeln Druckbreite bekannt (LABEL_WIDTH_PX).')
        tape_mm, offset_right = QL_ENDLESS_TAPES[label.width]
        # ESC i z: media. 0xCE = type, width and length valid, printer should check them,
        # quality over speed; 0x0A = continuous tape, length 0; then
        # number of lines and "first page?".
        data += b'\x1b\x69\x7a' + bytes([0xCE, 0x0A, tape_mm, 0])
        data += label.height.to_bytes(4, 'little') + bytes([0 if index == 0 else 1, 0])
        data += b'\x1b\x69\x4d\x40'  # ESC i M: cut automatically
        data += b'\x1b\x69\x41\x01'  # ESC i A: after every label
        data += b'\x1b\x69\x4b\x08'  # ESC i K: also cut after the last one
        data += b'\x1b\x69\x64' + QL_FEED_MARGIN.to_bytes(2, 'little')  # ESC i d: feed
        # The printer expects the line from right to left; 1 = black.
        line = Image.new('1', (QL_HEAD_PX, label.height), 1)
        mirrored = label.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        line.paste(mirrored, (QL_HEAD_PX - label.width - offset_right, 0))
        raster = ImageOps.invert(line.convert('L')).convert('1').tobytes()
        row_bytes = QL_HEAD_PX // 8
        for row in range(label.height):
            data += b'\x67\x00' + bytes([row_bytes]) + raster[row * row_bytes:(row + 1) * row_bytes]
        # SUB: print and feed – after every label, so that each comes out cut
        # off individually.
        data += b'\x1a'
    return bytes(data)
