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
    'first_name', 'last_name', 'fiscal_code', 'id_document_number', 'birth_date', 'birth_place',
    'nationality', 'address', 'zip_code', 'city', 'province', 'email', 'phone_number',
)
#: What a guardian fills in for the minor they sign for.
MINOR_FIELDS = (
    'first_name', 'last_name', 'birth_place', 'birth_date', 'address', 'zip_code', 'city', 'province',
    'fiscal_code',
)
LOCATION_LOGO = 'location_logo'
LOCATION_NAME = 'location_name'
LOCATION_ADDRESS = 'location_address'
LOCATION_CITY = 'location_city'
DATE = 'date'
MINOR = 'minor'
YES_NO = 'yes_no'
SIGNATURE = 'signature'

#: Every placeholder the editor offers: key -> label.
PLACEHOLDERS = {
    **{field: Member._meta.get_field(field).verbose_name for field in MEMBER_PLACEHOLDER_FIELDS},
    LOCATION_LOGO: gettext_lazy('Association logo'),
    LOCATION_NAME: gettext_lazy('Association name'),
    LOCATION_ADDRESS: gettext_lazy('Association address'),
    LOCATION_CITY: gettext_lazy('Association city'),
    DATE: gettext_lazy('Signing date'),
    MINOR: gettext_lazy('On their own behalf / minor'),
    YES_NO: gettext_lazy('Yes / No'),
    SIGNATURE: gettext_lazy('Signature'),
}
#: Placeholders the signer acts on, not plain text: the editor shows them apart.
ACTION_PLACEHOLDERS = (MINOR, YES_NO, SIGNATURE)

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


def consent_labels(body):
    """
    The question behind each yes/no field, in document order: the text of the
    paragraph (or list item) it sits in, without the placeholders.
    """
    collector = _BlockText()
    collector.feed(sanitize_body(body))
    collector.close()
    return collector.labels


class _BlockText(HTMLParser):
    BLOCKS = {'p', 'h2', 'h3', 'li'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.labels = []
        self.text = []

    def _flush(self):
        text = ''.join(self.text)
        self.text = []
        label = ' '.join(PLACEHOLDER_RE.sub(' ', text).split())
        if len(label) > 300:
            label = label[:297] + '...'
        self.labels += [label] * sum(1 for key in PLACEHOLDER_RE.findall(text) if key == YES_NO)

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCKS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in self.BLOCKS:
            self._flush()

    def handle_data(self, data):
        self.text.append(data)

    def close(self):
        super().close()
        self._flush()


def minor_sentence(minor):
    """How the signer acts: for themselves, or for the minor whose data is given."""
    if not minor:
        return _('on their own behalf')
    values = {field: _format_value(minor.get(field)) or BLANK for field in MINOR_FIELDS}
    return _(
        'as the holder of parental responsibility over the minor %(first_name)s %(last_name)s, '
        'born in %(birth_place)s on %(birth_date)s, living in %(address)s, %(zip_code)s %(city)s '
        '(%(province)s), fiscal code %(fiscal_code)s'
    ) % values


def logo_png(location):
    """The location's image as a small PNG for the PDF, or None."""
    if not location.cover:
        return None
    try:
        with location.cover.open('rb') as handle:
            image = PILImage.open(handle)
            image.load()
        image.thumbnail((600, 600))
        out = BytesIO()
        image.convert('RGBA').save(out, format='PNG')
        return out.getvalue()
    except Exception:
        logger.warning('Could not read the image of location %s for a document', location.pk, exc_info=True)
        return None


def _format_value(value):
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return date_format(value, 'd/m/Y')
    return str(value).strip()


def placeholder_values(member, location, signed_at=None, minor=None):
    """Text for each text placeholder, for `member` signing now."""
    values = {field: _format_value(getattr(member, field, '')) for field in MEMBER_PLACEHOLDER_FIELDS}
    values[LOCATION_NAME] = location.name
    values[LOCATION_ADDRESS] = location.address or ''
    values[LOCATION_CITY] = location.city or ''
    values[DATE] = date_format(timezone.localtime(signed_at or timezone.now()), 'd/m/Y')
    values[MINOR] = minor_sentence(minor)
    return values


def yes_no_text(accepted):
    """The two boxes in plain text, for the page: ☒ Yes ☐ No."""
    return f"{'☒' if accepted is True else '☐'} {_('Yes')}   {'☒' if accepted is False else '☐'} {_('No')}"


def render_html(body, values, logo_url=None):
    """
    The document as the signer reads it. Values are escaped; each one sits in
    a `data-placeholder` span the signing page updates while the form is typed.
    """
    consent_index = iter(range(10_000))

    def replace(match):
        key = match.group(1)
        if key not in PLACEHOLDERS:
            return match.group(0)
        if key == SIGNATURE:
            return '<span class="doc-signature-slot" data-signature-slot></span>'
        if key == LOCATION_LOGO:
            return f'<img class="doc-logo" src="{html_escape(logo_url)}" alt="">' if logo_url else ''
        if key == YES_NO:
            return (f'<span class="doc-consent" data-consent="{next(consent_index)}">'
                    f'{html_escape(yes_no_text(None))}</span>')
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

    def __init__(self, styles, values, signature_flowable, logo_flowable=None, consents=()):
        super().__init__(convert_charrefs=True)
        self.styles = styles
        self.values = values
        self.signature_flowable = signature_flowable
        self.logo_flowable = logo_flowable
        self.consents = list(consents)
        self.consent_count = 0
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
            elif key == LOCATION_LOGO:
                if self.logo_flowable is not None:
                    self._flush()
                    target = self.lists[-1][1] if self.lists else self.flowables
                    target.append(self.logo_flowable())
            elif key == YES_NO:
                index = self.consent_count
                self.consent_count += 1
                accepted = self.consents[index] if index < len(self.consents) else None
                self.buffer.append(_yes_no_markup(accepted))
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


def _yes_no_markup(accepted):
    """
    ReportLab markup for the two boxes, as [X] / [ ] in Courier: Helvetica has
    no ballot box, and symbol fonts render differently from viewer to viewer.
    """
    def option(checked, label):
        box = '[X]' if checked else '[&nbsp;]'
        label = xml_escape(label)
        return f'<font name="Courier">{box}</font>&nbsp;{"<b>" + label + "</b>" if checked else label}'
    return f'{option(accepted is True, _("Yes"))}&nbsp;&nbsp;&nbsp;{option(accepted is False, _("No"))}'


def _styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    base = getSampleStyleSheet()
    return {
        'Body': ParagraphStyle('DocBody', parent=base['BodyText'], fontSize=10.5, leading=14.5, spaceAfter=6),
        'DocH2': ParagraphStyle('DocH2', parent=base['Heading2'], fontSize=13, leading=16, spaceBefore=8),
        'DocH3': ParagraphStyle('DocH3', parent=base['Heading3'], fontSize=11.5, leading=14, spaceBefore=6),
        'Caption': ParagraphStyle('DocCaption', parent=base['BodyText'], fontSize=8.5, leading=11,
                                  textColor=colors.HexColor('#475569')),
        'Audit': ParagraphStyle('DocAudit', parent=base['BodyText'], fontSize=7.5, leading=10,
                                textColor=colors.HexColor('#64748b')),
    }


def build_pdf(*, title, location_name, body, values, signature_png=None, signer_name='', audit_lines=(),
              logo=None, consents=()):
    """
    The document as a flat PDF. Without `signature_png` it is a preview: the
    signature box stays empty and no audit trail is printed. `logo` is PNG
    bytes for the logo placeholder, `consents` the yes/no answers in order.
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

    def logo_flowable():
        reader = PILImage.open(BytesIO(logo))
        ratio = reader.width / reader.height
        height = 2.5 * cm
        width = min(height * ratio, 8 * cm)
        image = Image(BytesIO(logo), width=width, height=width / ratio, mask='auto')
        image.hAlign = 'LEFT'
        return KeepTogether([image, Spacer(1, 8)])

    builder = _PdfBuilder(styles, values, signature_flowable,
                          logo_flowable=logo_flowable if logo else None, consents=consents)
    builder.feed(sanitize_body(body))
    builder.close()

    # The text carries its own heading: the name is in the footer and the metadata.
    story = list(builder.flowables)
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
    location = document.location
    values = {key: '' for key in PLACEHOLDERS}
    values.update({
        LOCATION_NAME: location.name, LOCATION_ADDRESS: location.address or '',
        LOCATION_CITY: location.city or '', MINOR: minor_sentence(None),
    })
    return build_pdf(title=document.name, location_name=location.name,
                     body=document.body, values=values, logo=logo_png(location))


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


def sign_document(*, document, member, membership, signature_png, request, collected_by=None,
                  consents=(), minor=None):
    """
    Generate and store the signed PDF of `document` for `member`, whose data
    the caller has already saved, then notify the location's managers.

    `consents` are the yes/no answers in document order, `minor` the data of
    the minor a guardian signs for, if any.
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
        answers=_answers(document, consents, minor),
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
    if minor:
        audit_lines.append(_("Signed by a holder of parental responsibility on behalf of the minor %(name)s.") % {
            'name': f"{minor.get('first_name', '')} {minor.get('last_name', '')}".strip()})

    pdf_bytes = build_pdf(
        title=document.name, location_name=location.name, body=document.body,
        values=placeholder_values(member, location, signed_at, minor=minor),
        signature_png=signature_png, signer_name=member.full_name, audit_lines=audit_lines,
        logo=logo_png(location), consents=consents,
    )
    signed.sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    with transaction.atomic():
        signed.pdf.save(f'{signed.uuid}.pdf', ContentFile(pdf_bytes), save=False)
        signed.save()
        if membership is not None:
            _mark_membership_signed(membership)
        transaction.on_commit(lambda: _notify_managers(signed, exclude=collected_by))
    return signed


def _answers(document, consents, minor):
    answers = {}
    if consents:
        answers['consents'] = [
            {'label': label, 'accepted': accepted}
            for label, accepted in zip(consent_labels(document.body), consents)
        ]
    if minor:
        answers['minor'] = {field: _format_value(minor.get(field)) for field in MINOR_FIELDS}
    return answers


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

