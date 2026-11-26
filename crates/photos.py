"""Photos of a crate's contents: scale down, rotate, strip metadata."""
import io

from PIL import Image, ImageOps, UnidentifiedImageError

# Longest edge of the stored image. Enough to read labelling, and it turns
# 12-megapixel photos into files of a few hundred kilobytes.
MAX_EDGE = 1600
THUMB_EDGE = 400
JPEG_QUALITY = 82
# Largest accepted file. Phone cameras deliver 3–12 MB.
MAX_UPLOAD_BYTES = 30 * 1024 * 1024


class PhotoError(ValueError):
    """The uploaded file cannot be used as a photo."""


def _jpeg(image, edge):
    copy = image.copy()
    copy.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def process_upload(upload):
    """Turns an upload into two JPEGs (image, thumbnail) and returns them as bytes.

    The image is rotated upright according to its EXIF data and re-encoded. This
    drops all metadata – including the location that phones record.
    """
    if upload.size > MAX_UPLOAD_BYTES:
        raise PhotoError(f'„{upload.name}“ ist größer als {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.')
    try:
        image = Image.open(upload)
        image = ImageOps.exif_transpose(image)
        if image.mode in ('RGBA', 'LA', 'P'):
            # Put transparency on white; JPEG has none.
            rgba = image.convert('RGBA')
            image = Image.new('RGB', rgba.size, 'white')
            image.paste(rgba, mask=rgba.getchannel('A'))
        else:
            image = image.convert('RGB')
        return _jpeg(image, MAX_EDGE), _jpeg(image, THUMB_EDGE)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise PhotoError(f'„{upload.name}“ ist kein Bild, das sich verarbeiten lässt.') from error
