"""Riduzione delle immagini caricate (copertine, avatar) prima del salvataggio nello storage.

Le copertine BGG arrivano a piena risoluzione (PNG fino a diversi MB) ma sono
mostrate al massimo come hero di pagina: le riduciamo a JPEG con lato lungo
limitato. JPEG e non WebP perché le copertine finiscono anche in og:image.
"""
import logging
import os
from contextlib import contextmanager
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.utils.translation import gettext_lazy as _
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

COVER_MAX_SIDE = 1200
COVER_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
AVATAR_MAX_SIDE = 256
NETWORK_LOGO_MAX_BYTES = 2 * 1024 * 1024
NETWORK_LOGO_MAX_INPUT_SIDE = 2048
NETWORK_LOGO_MAX_SIDE = 512
NETWORK_LOGO_FORMATS = ('PNG', 'JPEG', 'WEBP')
JPEG_QUALITY = 82
# Sotto questa soglia un'immagine già entro le dimensioni viene lasciata com'è
SMALL_ENOUGH_BYTES = 200 * 1024
# Riscriviamo il file solo se il risultato pesa al massimo il 70% dell'originale
MIN_SAVING_RATIO = 0.7
# Formati che Pillow può aprire: gli unici che servono per copertine e avatar.
# MPO (i JPEG multi-immagine di molti telefoni) li apre il decoder JPEG: è in
# lista solo nel caso una versione futura di Pillow lo registri a parte.
ALLOWED_OPEN_FORMATS = ('JPEG', 'MPO', 'PNG', 'WEBP', 'GIF')


def restrict_open_formats():
    """Toglie dal registro di Pillow tutti i decoder tranne ALLOWED_OPEN_FORMATS.

    Quasi tutte le vulnerabilità di Pillow stanno in decoder di formati che non
    usiamo (TIFF, PDF, EPS, FPX, ...), raggiungibili da qualunque Image.open(),
    compresa la validazione di ImageField. Pillow carica i plugin in modo pigro,
    anche in base all'estensione del file: li carichiamo tutti subito con init()
    e poi li togliamo, così un import successivo non li registra di nuovo.
    """
    Image.init()
    Image.ID[:] = [f for f in Image.ID if f in ALLOWED_OPEN_FORMATS]
    for fmt in list(Image.OPEN):
        if fmt not in ALLOWED_OPEN_FORMATS:
            del Image.OPEN[fmt]


def shrink_image_bytes(data, max_side):
    """Restituisce i byte JPEG ridotti, oppure None se l'immagine va lasciata com'è
    (già piccola, non decodificabile, o la riduzione non farebbe risparmiare)."""
    try:
        with Image.open(BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            if max(img.size) <= max_side and len(data) <= SMALL_ENOUGH_BYTES:
                return None
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            img = _to_rgb(img)
            out = BytesIO()
            img.save(out, 'JPEG', quality=JPEG_QUALITY, optimize=True, progressive=True)
    except (UnidentifiedImageError, OSError, ValueError) as e:
        logger.warning(f'Image shrink skipped: {e}')
        return None

    result = out.getvalue()
    if len(result) > len(data) * MIN_SAVING_RATIO:
        return None
    return result


def _to_rgb(img):
    """Appiattisce la trasparenza su bianco: il JPEG non ha canale alpha."""
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        img = img.convert('RGBA')
        background = Image.new('RGB', img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel('A'))
        return background
    if img.mode != 'RGB':
        return img.convert('RGB')
    return img


def jpeg_name(name):
    """`games/bgg_123.png` -> `bgg_123.jpg` (upload_to aggiunge la cartella)."""
    return os.path.splitext(os.path.basename(name))[0] + '.jpg'


def shrink_content_file(data, name, max_side):
    """ContentFile pronto per FieldFile.save(): ridotto se conviene, altrimenti l'originale."""
    shrunk = shrink_image_bytes(data, max_side)
    if shrunk is None:
        return name, ContentFile(data)
    return jpeg_name(name), ContentFile(shrunk)


@contextmanager
def _open_network_logo(upload):
    if upload.size > NETWORK_LOGO_MAX_BYTES:
        raise ValidationError(_('The logo must be 2 MB or smaller.'))
    upload.seek(0)
    try:
        with Image.open(upload, formats=NETWORK_LOGO_FORMATS) as image:
            if max(image.size) > NETWORK_LOGO_MAX_INPUT_SIDE:
                raise ValidationError(_('The logo must be 2048 pixels or smaller on each side.'))
            yield image
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ValidationError(_('Upload a valid PNG, JPEG or WebP logo.')) from exc
    finally:
        upload.seek(0)


def validate_network_logo(upload):
    with _open_network_logo(upload) as image:
        image.load()


def normalize_network_logo(upload, name):
    with _open_network_logo(upload) as source:
        logo = ImageOps.exif_transpose(source).convert('RGBA')
        logo.thumbnail((NETWORK_LOGO_MAX_SIDE, NETWORK_LOGO_MAX_SIDE), Image.LANCZOS)
        output = BytesIO()
        logo.save(output, format='PNG')
    return f'{os.path.splitext(name)[0]}.png', ContentFile(output.getvalue())
