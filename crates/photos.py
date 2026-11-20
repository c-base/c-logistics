"""Fotos vom Inhalt einer Crate: verkleinern, drehen, Metadaten entfernen."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Längste Kante des gespeicherten Bildes. Reicht, um Beschriftungen zu lesen,
# und macht aus 12-Megapixel-Fotos Dateien von wenigen hundert Kilobyte.
MAX_EDGE = 1600
THUMB_EDGE = 400
JPEG_QUALITY = 82
# Größte angenommene Datei. Handykameras liefern 3–12 MB.
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


class PhotoError(ValueError):
    """Die hochgeladene Datei lässt sich nicht als Foto verwenden."""


def _jpeg(image, edge):
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def process_upload(upload):
    """Macht aus einem Upload zwei JPEGs (Bild, Vorschau) und gibt sie als Bytes zurück.

    Das Bild wird nach der EXIF-Angabe aufrecht gedreht und neu kodiert. Dabei
    fallen alle Metadaten weg – auch der Aufnahmeort, den Handys mitschreiben.
    """
    if upload.size > MAX_UPLOAD_BYTES:
        raise PhotoError(f'„{upload.name}“ ist größer als {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        if image.mode in ('RGBA', 'LA', 'P'):
            # Transparenz auf Weiß legen; JPEG kennt keine.
            rgba = image.convert('RGBA')
            image = Image.new('RGB', rgba.size, 'white')
            image.paste(rgba, mask=rgba.getchannel('A'))
        else:
            image = image.convert('RGB')
        return _jpeg(image, MAX_EDGE), _jpeg(image, THUMB_EDGE)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoError(f'„{upload.name}“ ist kein Bild, das sich verarbeiten lässt.') from error
