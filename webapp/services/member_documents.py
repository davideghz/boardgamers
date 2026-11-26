"""
Online membership documents: a text a location writes in the app, with
placeholders for the member's data, that members sign by drawing their
signature. Signing turns it into a flat PDF stored on the private bucket.

The PDF is built with ReportLab (pure Python, nothing to install on Heroku)
from the small HTML subset the editor produces.
"""
import base64
import binascii
import hashlib
import ipaddress
import logging
import re
from html import escape as html_escape
from html.parser import HTMLParser
from io import BytesIO
from xml.sax.saxutils import escape as xml_escape

import nh3
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.utils.translation import gettext as _, gettext_lazy
from PIL import Image as PILImage

from webapp.models import Member, MembershipDocument, SignedMembershipDocument

logger = logging.getLogger(__name__)

#: Member fields a document can ask for, in the order the signing form shows them.
MEMBER_PLACEHOLDER_FIELDS = (
    'first_name', 'last_name', 'fiscal_code', 'birth_date', 'birth_place', 'nationality',
    'address', 'zip_code', 'city', 'province', 'email', 'phone_number',
)
LOCATION_NAME = 'location_name'
DATE = 'date'
SIGNATURE = 'signature'

#: Every placeholder the editor offers: key -> label.
PLACEHOLDERS = {
    **{field: Member._meta.get_field(field).verbose_name for field in MEMBER_PLACEHOLDER_FIELDS},
    LOCATION_NAME: gettext_lazy('Association name'),
    DATE: gettext_lazy('Signing date'),
    SIGNATURE: gettext_lazy('Signature'),
}

PLACEHOLDER_RE = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')

ALLOWED_TAGS = {'p', 'br', 'strong', 'em', 'u', 'h2', 'h3', 'ul', 'ol', 'li'}
BODY_MAX_LENGTH = 50_000

#: A drawn signature is a small PNG: anything bigger is not one.
SIGNATURE_MAX_BYTES = 512 * 1024
BLANK = '_______________'


# ── Body ─────────────────────────────────────────────────────────────────────

def sanitize_body(html):
    """Keep only the formatting the editor offers: no attributes, no links."""
    return nh3.clean(html or '', tags=ALLOWED_TAGS, attributes={}).strip()


def used_placeholders(body):
    """Known placeholder keys found in `body`, in the order of `PLACEHOLDERS`."""
    found = set(PLACEHOLDER_RE.findall(body or ''))
    return [key for key in PLACEHOLDERS if key in found]


def member_fields_for(document):
    """The member fields the signing form has to ask for."""
    used = set(used_placeholders(document.body))
    return [field for field in MEMBER_PLACEHOLDER_FIELDS if field in used]


def _format_value(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return date_format(value, 'd/m/Y')
    return str(value).strip()


def placeholder_values(member, location, signed_at=None):
    """Text for each placeholder but the signature, for `member` signing now."""
    values = {field: _format_value(getattr(member, field, '')) for field in MEMBER_PLACEHOLDER_FIELDS}
    values[LOCATION_NAME] = location.name
    values[DATE] = date_format(timezone.localtime(signed_at or timezone.now()), 'd/m/Y')
    return values


def render_html(body, values):
    """
    The document as the signer reads it. Values are escaped; each one sits in
    a `data-placeholder` span the signing page updates while the form is typed.
    """
    def replace(match):
        key = match.group(1)
        if key not in PLACEHOLDERS:
            return match.group(0)
        if key == SIGNATURE:
            return '<span class="doc-signature-slot" data-signature-slot></span>'
        value = values.get(key, '')
        return (f'<span class="doc-placeholder" data-placeholder="{key}">'
                f'{html_escape(value) if value else BLANK}</span>')
    return mark_safe(PLACEHOLDER_RE.sub(replace, sanitize_body(body)))


# ── Signature ────────────────────────────────────────────────────────────────

def decode_signature(data_url):
    """
    PNG bytes of the signature drawn in the browser, re-encoded by Pillow so
    nothing but pixels gets into the PDF. Raises ValueError when the data is
    not a PNG image or nothing was drawn.
    """
    prefix = 'data:image/png;base64,'
    if not data_url or not data_url.startswith(prefix):
        raise ValueError('not a PNG data URL')
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('invalid base64') from exc
    if len(raw) > SIGNATURE_MAX_BYTES:
        raise ValueError('signature too large')
    try:
        image = PILImage.open(BytesIO(raw))
        image.load()
    except Exception as exc:
        raise ValueError('invalid image') from exc
    if image.format != 'PNG' or image.width > 2000 or image.height > 1000:
        raise ValueError('unexpected image')
    image = image.convert('RGBA')
    if image.getchannel('A').getbbox() is None:
        raise ValueError('empty signature')
    # Crop to the strokes, so the signature fills its box in the PDF.
    image = image.crop(image.getchannel('A').getbbox())
    out = BytesIO()
    image.save(out, format='PNG')
    return out.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────────────

class _PdfBuilder(HTMLParser):
    """Turns the editor's HTML subset into ReportLab flowables."""

    INLINE = {'strong': 'b', 'b': 'b', 'em': 'i', 'i': 'i', 'u': 'u'}
    BLOCKS = {'p': 'Body', 'h2': 'DocH2', 'h3': 'DocH3'}

    def __init__(self, styles, values, signature_flowable):
        super().__init__(convert_charrefs=True)
        self.styles = styles
        self.values = values
        self.signature_flowable = signature_flowable
        self.flowables = []
        self.buffer = []
        self.style = 'Body'
        self.lists = []  # stack of (tag, items)
        self.signature_placed = False

    # Paragraph text is ReportLab markup: data is escaped, tags are ours.
    def _flush(self):
        from reportlab.platypus import Paragraph
        text = ''.join(self.buffer).strip()
        self.buffer = []
        if not text or text == '<br/>':
            return
        paragraph = Paragraph(text, self.styles[self.style])
        if self.lists:
            self.lists[-1][1].append(paragraph)
        else:
            self.flowables.append(paragraph)

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self._flush()
            self.style = self.BLOCKS[tag]
        elif tag in ('ul', 'ol'):
            self._flush()
            self.lists.append((tag, []))
        elif tag == 'li':
            self._flush()
            self.style = 'Body'
        elif tag in self.INLINE:
            self.buffer.append(f'<{self.INLINE[tag]}>')
        elif tag == 'br':
            self.buffer.append('<br/>')

    def handle_endtag(self, tag):
        if tag in self.BLOCKS or tag == 'li':
            self._flush()
            self.style = 'Body'
        elif tag in ('ul', 'ol') and self.lists:
            self._flush()
            from reportlab.platypus import ListFlowable
            list_tag, items = self.lists.pop()
            if not items:
                return
            flowable = ListFlowable(
                items, bulletType='1' if list_tag == 'ol' else 'bullet',
                start=None if list_tag == 'ol' else '•', bulletFormat='%s.' if list_tag == 'ol' else None,
                leftIndent=14, bulletFontSize=9)
            if self.lists:
                self.lists[-1][1].append(flowable)
            else:
                self.flowables.append(flowable)
        elif tag in self.INLINE:
            self.buffer.append(f'</{self.INLINE[tag]}>')

    def handle_data(self, data):
        position = 0
        for match in PLACEHOLDER_RE.finditer(data):
            self.buffer.append(xml_escape(data[position:match.start()]))
            position = match.end()
            key = match.group(1)
            if key == SIGNATURE:
                self._flush()
                self._place_signature()
            elif key in PLACEHOLDERS:
                value = self.values.get(key, '')
                self.buffer.append(xml_escape(value) if value else BLANK)
            else:
                self.buffer.append(xml_escape(match.group(0)))
        self.buffer.append(xml_escape(data[position:]))

    def _place_signature(self):
        target = self.lists[-1][1] if self.lists else self.flowables
        target.append(self.signature_flowable())
        self.signature_placed = True

    def close(self):
        super().close()
        self._flush()
        while self.lists:
            self.handle_endtag(self.lists[-1][0])


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    base = getSampleStyleSheet()
    return {
        'Title': ParagraphStyle('DocTitle', parent=base['Title'], fontSize=16, leading=20, spaceAfter=12),
        'Body': ParagraphStyle('DocBody', parent=base['BodyText'], fontSize=10.5, leading=14.5, spaceAfter=6),
        'DocH2': ParagraphStyle('DocH2', parent=base['Heading2'], fontSize=13, leading=16, spaceBefore=8),
        'DocH3': ParagraphStyle('DocH3', parent=base['Heading3'], fontSize=11.5, leading=14, spaceBefore=6),
        'Caption': ParagraphStyle('DocCaption', parent=base['BodyText'], fontSize=8.5, leading=11,
                                  textColor=colors.HexColor('#475569')),
        'Audit': ParagraphStyle('DocAudit', parent=base['BodyText'], fontSize=7.5, leading=10,
                                textColor=colors.HexColor('#64748b')),
    }


def build_pdf(*, title, location_name, body, values, signature_png=None, signer_name='', audit_lines=()):
    """
    The document as a flat PDF. Without `signature_png` it is a preview: the
    signature box stays empty and no audit trail is printed.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table

    styles = _styles()

    def signature_flowable():
        if signature_png:
            reader = PILImage.open(BytesIO(signature_png))
            ratio = reader.width / reader.height
            width, height = 6 * cm, 6 * cm / ratio
            if height > 2.5 * cm:
                height, width = 2.5 * cm, 2.5 * cm * ratio
            mark = Image(BytesIO(signature_png), width=width, height=height, mask='auto')
        else:
            mark = Spacer(6 * cm, 2 * cm)
        caption = Paragraph(xml_escape(signer_name) or _('Signature'), styles['Caption'])
        box = Table([[mark], [caption]], colWidths=[7 * cm], hAlign='LEFT')
        box.setStyle([
            ('LINEBELOW', (0, 0), (0, 0), 0.6, colors.HexColor('#94a3b8')),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (0, 0), 2),
        ])
        return KeepTogether([Spacer(1, 6), box, Spacer(1, 6)])

    builder = _PdfBuilder(styles, values, signature_flowable)
    builder.feed(sanitize_body(body))
    builder.close()

    story = [Paragraph(xml_escape(title), styles['Title'])] + builder.flowables
    if not builder.signature_placed:
        story += [
            Spacer(1, 12),
            Paragraph(xml_escape(_('Date: %(date)s') % {'date': values.get(DATE, '')}), styles['Body']),
            signature_flowable(),
        ]
    if audit_lines:
        story += [Spacer(1, 18)] + [Paragraph(xml_escape(line), styles['Audit']) for line in audit_lines]

    footer = f'{location_name} · {title}'

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(colors.HexColor('#64748b'))
        canvas.drawString(2 * cm, 1.2 * cm, footer[:110])
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, str(doc.page))
        canvas.restoreState()

    out = BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=title, author=location_name, creator='Board-Gamers.com')
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out.getvalue()


def preview_pdf(document):
    """The document with empty placeholders, for the manager to check the layout."""
    values = {key: '' for key in PLACEHOLDERS}
    values[LOCATION_NAME] = document.location.name
    return build_pdf(title=document.name, location_name=document.location.name,
                     body=document.body, values=values)


# ── Signing ──────────────────────────────────────────────────────────────────

def client_ip(request):
    """
    The client address. Heroku's router appends the address it saw to
    X-Forwarded-For, so the last entry is the one nobody can forge.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    candidate = forwarded.split(',')[-1].strip() if forwarded else request.META.get('REMOTE_ADDR', '')
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def pending_online_documents(membership):
    """Active online documents of the membership's location not signed for it yet."""
    if membership is None:
        return MembershipDocument.objects.none()
    location = membership.member.location
    return location.membership_documents.filter(
        kind=MembershipDocument.ONLINE, is_active=True,
    ).exclude(signatures__membership=membership).order_by('name')


def signing_membership(member):
    """The membership a document is signed for: the pending or active one."""
    membership = member.current_membership
    if membership and membership.status in (membership.PENDING, membership.ACTIVE):
        return membership
    return None


def _mark_membership_signed(membership):
    """
    Tick "signed document received" once every active online document is
    signed, unless the location also asks for paper ones.
    """
    if membership.signed_document:
        return
    active = membership.member.location.membership_documents.filter(is_active=True)
    if active.filter(kind=MembershipDocument.FILE).exists():
        return
    if not pending_online_documents(membership).exists():
        membership.signed_document = True
        membership.save(update_fields=['signed_document', 'updated_at'])


def sign_document(*, document, member, membership, signature_png, request, collected_by=None):
    """
    Generate and store the signed PDF of `document` for `member`, whose data
    the caller has already saved, then notify the location's managers.
    """
    location = member.location
    signed_at = timezone.now()
    signed = SignedMembershipDocument(
        document=document, document_name=document.name, member=member, membership=membership,
        signed_at=signed_at,
        signed_by=member.user_profile if collected_by is None else None,
        collected_by=collected_by,
        ip_address=client_ip(request),
        user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:300],
    )
    local_time = timezone.localtime(signed_at)
    audit_lines = [
        _("Signed with a simple electronic signature on Board-Gamers.com by %(name)s on %(date)s at %(time)s.") % {
            'name': member.full_name,
            'date': date_format(local_time, 'd/m/Y'),
            'time': local_time.strftime('%H:%M:%S %Z'),
        },
        _("IP address: %(ip)s · Document ID: %(uuid)s") % {'ip': signed.ip_address or '-', 'uuid': signed.uuid},
    ]
    if collected_by is not None:
        audit_lines.append(_("Signed in person on the device of %(manager)s.") % {
            'manager': collected_by.nickname})
    elif member.user_profile is not None:
        audit_lines.append(_("Signed from the account %(nickname)s.") % {
            'nickname': member.user_profile.nickname})

    pdf_bytes = build_pdf(
        title=document.name, location_name=location.name, body=document.body,
        values=placeholder_values(member, location, signed_at),
        signature_png=signature_png, signer_name=member.full_name, audit_lines=audit_lines,
    )
    signed.sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    with transaction.atomic():
        signed.pdf.save(f'{signed.uuid}.pdf', ContentFile(pdf_bytes), save=False)
        signed.save()
        if membership is not None:
            _mark_membership_signed(membership)
        transaction.on_commit(lambda: _notify_managers(signed, exclude=collected_by))
    return signed


def _notify_managers(signed, exclude=None):
    from webapp.emails import send_notification_document_signed
    location = signed.member.location
    recipients = {profile.pk: profile for profile in location.managers.select_related('user')}
    if location.creator_id:
        recipients[location.creator_id] = location.creator
    if exclude is not None:
        recipients.pop(exclude.pk, None)
    for profile in recipients.values():
        try:
            send_notification_document_signed(profile, signed)
        except Exception:
            # The signature is saved: a mail hiccup must not turn it into an error page.
            logger.exception('Could not notify %s of signed document %s', profile.pk, signed.uuid)


def signed_pdf_filename(signed):
    return f'{slugify(signed.document_name) or "document"}-{slugify(signed.member.full_name)}.pdf'

