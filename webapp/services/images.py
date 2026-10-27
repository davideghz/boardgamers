"""Riduzione delle immagini caricate (copertine, avatar) prima del salvataggio su S3.

Le copertine BGG arrivano a piena risoluzione (PNG fino a diversi MB) ma sono
mostrate al massimo come hero di pagina: le riduciamo a JPEG con lato lungo
limitato. JPEG e non WebP perché le copertine finiscono anche in og:image.
"""
import logging
import os
from io import BytesIO

from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

COVER_MAX_SIDE = 1200
AVATAR_MAX_SIDE = 256
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
