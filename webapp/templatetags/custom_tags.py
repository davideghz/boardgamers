import mistune
import nh3

from django import template
from django.urls import translate_url, reverse
from django.utils.safestring import mark_safe
from django.utils.translation import get_language, gettext_lazy as _, pgettext_lazy
from urllib.parse import urlencode

register = template.Library()

_ALLOWED_TAGS = {"p", "strong", "em", "ul", "ol", "li", "br"}


@register.filter
def km(value):
    """Convert a GeoDjango Distance (or plain meters float) to a formatted km string."""
    try:
        meters = value.m  # GeoDjango Distance object
    except AttributeError:
        meters = float(value)
    return f"{meters / 1000:.1f}".replace(".", ",")


@register.filter
def render_markdown(value):
    if not value:
        return ""
    html = mistune.html(value)
    clean = nh3.clean(html, tags=_ALLOWED_TAGS)
    return mark_safe(clean)



@register.inclusion_tag("partials/_back_link.html")
def back_link(url_name, *args, label="", query=None):
    """Link back to the page that logically contains the current one."""
    return {"url": reverse(url_name, args=args, query=query), "label": label}


@register.inclusion_tag("tags/location_card.html", takes_context=True)
def location_card(context, location):
    followed_ids = context.get('followed_location_ids', set())
    return {
        'location': location,
        'is_followed': location.id in followed_ids,
        'affiliations': getattr(location, 'public_affiliations', ()),
    }


@register.inclusion_tag("tags/table_card.html", takes_context=True)
def table_card(context, table):
    # Pages that pass `joined_table_ids` (the viewer's upcoming tables) mark the ones they're in
    return {
        'table': table,
        'joined': table.pk in context.get('joined_table_ids', ()),
    }


@register.inclusion_tag("tags/event_card.html", takes_context=True)
def event_card(context, event, today=None):
    # Pages that pass `managed_event_ids` get a gear linking to the event's management
    return {
        'event': event,
        'is_concluded': event.is_concluded(today),
        'can_manage': event.pk in context.get('managed_event_ids', ()),
    }


@register.inclusion_tag("tags/event_table_card.html")
def event_table_card(table):
    return {'table': table}


@register.inclusion_tag("tags/event_agenda_card.html")
def event_agenda_card(table):
    return {'table': table}


@register.inclusion_tag("tags/event_grid_cell.html")
def event_grid_cell(table):
    return {'table': table}


@register.simple_tag(takes_context=True)
def query_transform(context, **kwargs):
    """Return the current querystring (without leading '?') with the given
    params overridden. A param passed as '' or None is removed. Any other
    current params are preserved, which keeps independent filters composable."""
    request = context.get('request')
    if request is None:
        return ''
    params = request.GET.copy()
    for key, value in kwargs.items():
        if value in ('', None):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


@register.simple_tag(takes_context=True)
def alternate_url(context, lang_code):
    request = context["request"]
    current_url = request.build_absolute_uri()
    return translate_url(current_url, lang_code)


@register.simple_tag(takes_context=True)
def canonical_url(context):
    """Restituisce l'URL canonico nella lingua corrente."""
    request = context["request"]
    return request.build_absolute_uri()


@register.simple_tag(takes_context=True)
def social_auth_url(context, backend):
    """
    Genera l'URL per l'autenticazione social con la lingua corrente salvata nello state.
    Questo permette di preservare la lingua dell'utente durante il flusso OAuth
    senza dover configurare redirect URI multipli in Google Console.
    
    Usage: {% social_auth_url 'google-oauth2' %}
    """
    from django.utils.translation import get_language, override
    
    current_lang = get_language()
    
    # Forza la generazione di un URL non localizzato
    # usando override(None) per disattivare temporaneamente i18n
    with override(None):
        base_url = reverse('social:begin', args=[backend])
    
    # Aggiungi la lingua come parametro 'lang'
    # La custom view auth_with_language lo salverà nella sessione
    params = {'lang': current_lang}
    
    return f"{base_url}?{urlencode(params)}"


# ── Components ────────────────────────────────────────────────────────────────
# One look per element, shared by every page; /dev/ui/ shows them all (DEBUG only).

@register.inclusion_tag("components/button.html")
def button(label, url=None, variant="primary", size="md", type="submit", icon=None, full=False,
           disabled=False, extra_class=""):
    return {"label": label, "url": url, "variant": variant, "size": size, "type": type, "icon": icon,
            "full": full, "disabled": disabled, "extra_class": extra_class}


@register.inclusion_tag("components/icon.html")
def icon(name, css_class="w-4 h-4"):
    return {"name": name, "class": css_class}


@register.inclusion_tag("components/badge.html")
def badge(label, tone="neutral"):
    return {"label": label, "tone": tone}


# State words follow docs/ui-glossary.md; a state is always filled, a type always outlined.
STATUS_BADGES = {
    "draft": (pgettext_lazy("status", "Draft"), "warning"),
    "published": (pgettext_lazy("status", "Published"), "success"),
    "upcoming": (pgettext_lazy("status", "Upcoming"), "info"),
    "open": (pgettext_lazy("status", "Open"), "success"),
    "ongoing": (pgettext_lazy("status", "Ongoing"), "info"),
    "full": (pgettext_lazy("status", "Full"), "warning"),
    "closed": (pgettext_lazy("status", "Closed"), "neutral"),
    "past": (pgettext_lazy("status", "Past"), "neutral"),
    "pending": (pgettext_lazy("status", "Pending"), "warning"),
    "active": (pgettext_lazy("status", "Active"), "success"),
    "rejected": (pgettext_lazy("status", "Rejected"), "danger"),
}
TYPE_BADGES = {
    "table": pgettext_lazy("appointment type", "Table"),
    "event": pgettext_lazy("appointment type", "Event"),
    "manifestation": pgettext_lazy("appointment type", "Festival"),
}
ROLE_BADGES = {
    "creator": (pgettext_lazy("location role", "Owner"), "info"),
    "manager": (pgettext_lazy("location role", "Manager"), "info"),
    "member": (pgettext_lazy("location role", "Member"), "success"),
    "organizer": (pgettext_lazy("location role", "Organizer"), "outline"),
}


@register.inclusion_tag("components/badge.html")
def status_badge(status):
    label, tone = STATUS_BADGES.get(status, (status, "neutral"))
    return {"label": label, "tone": tone}


@register.inclusion_tag("components/badge.html")
def type_badge(kind):
    return {"label": TYPE_BADGES.get(kind, kind), "tone": "outline"}


@register.inclusion_tag("components/role_badge.html")
def role_badge(role):
    label, tone = ROLE_BADGES.get(role, (role, "neutral"))
    return {"label": label, "tone": tone}


@register.inclusion_tag("components/page_header.html")
def page_header(title, count=None, subtitle=None, action_label=None, action_url=None, action_icon="plus",
                back_url=None, back_label=""):
    return {"title": title, "count": count, "subtitle": subtitle, "action_label": action_label,
            "action_url": action_url, "action_icon": action_icon, "back_url": back_url, "back_label": back_label}


@register.inclusion_tag("components/empty_state.html")
def empty_state(message, detail=None, action_label=None, action_url=None, action_icon="plus", icon=None,
                access=None, location=None):
    return {"message": message, "detail": detail, "action_label": action_label, "action_url": action_url,
            "action_icon": action_icon, "icon": icon, "access": access, "location": location}


@register.inclusion_tag("components/result_row.html")
def result_row(url, kicker, title, meta=(), status=None, image_url=None, participation=None, actions=()):
    """`participation`: 'table' or 'event' adds the compact "You're in" / "You're attending";
    `actions`: (label, url, icon) links under the row, outside its main link."""
    status_label, status_tone = STATUS_BADGES.get(status, (status, "neutral")) if status else (None, None)
    return {"url": url, "kicker": kicker, "title": title, "meta": [line for line in meta if line],
            "status_label": status_label, "status_tone": status_tone, "image_url": image_url,
            "participation": participation, "actions": actions}


@register.inclusion_tag("components/manage_tile.html")
def manage_tile(url, title, description=None, icon=None, count=None):
    return {"url": url, "title": title, "description": description, "icon": icon, "count": count}


@register.inclusion_tag("components/todo_card.html")
def todo_card(url, title, count, description=None, tone="warning"):
    return {"url": url, "title": title, "count": count, "description": description, "tone": tone}


@register.inclusion_tag("components/participation_status.html")
def participation_status(kind="table", leave_dialog=None, compact=False):
    return {"kind": kind, "leave_dialog": leave_dialog, "compact": compact}


@register.inclusion_tag("components/confirm_dialog.html", takes_context=True)
def confirm_dialog(context, dialog_id, title, action_url, confirm_label, message=None, danger=True):
    return {"dialog_id": dialog_id, "title": title, "action_url": action_url, "confirm_label": confirm_label,
            "message": message, "danger": danger, "csrf_token": context.get("csrf_token")}


@register.simple_tag(takes_context=True)
def location_relation(context, location):
    """The viewer's relation to `location`: manager, member, pending, follower, visitor or
    anonymous (see services/viewer.py). Usage: {% location_relation location as rel %}."""
    return context['viewer'].relation(location)


@register.inclusion_tag("components/joined_dialog.html")
def joined_dialog(share_title, message, share_label=None):
    return {"share_title": share_title, "message": message, "share_label": share_label}


@register.filter
def in_list(value, names):
    """True when `value` is one of the comma-separated `names` (e.g. the current URL name
    against the pages a menu entry stands for)."""
    return value in [name.strip() for name in names.split(',')]


@register.inclusion_tag("components/result_row.html", takes_context=True)
def appointment_row(context, kind, item, past=False, status=None, mine=False):
    """A table, event or manifestation (kind 'table', 'event', 'manifestation') as a result_row:
    kicker "Type · date", title, where and who, and the state apart from the type.

    `mine` (My activities): upcoming rows say whether the user plays or attends, read from the
    `playing` / `attending` annotations, and the tables the user created offer edit and duplicate."""
    from django.utils import timezone
    from django.utils.formats import date_format, time_format

    def day_label(day):  # the year only when it is not this one
        return date_format(day, 'D j M' if day.year == timezone.localdate().year else 'D j M Y')

    if kind == 'table':
        kicker = [TYPE_BADGES['table'], day_label(item.date), time_format(item.time, 'H:i')]
        if item.event_id:
            meta = [item.event.name, item.event.venue_label]
        else:
            meta = [item.location.name if item.location_id else '']
        meta.insert(0, str(item.game) if item.game_id else '')
        status, image = item.status, item.cover_url
    else:
        day = getattr(item, 'matching_date', None)
        kicker = [TYPE_BADGES[kind], day_label(day) if day else '']
        if getattr(item, 'matching_time', None):
            kicker.append(time_format(item.matching_time, 'H:i'))
        if kind == 'event':
            meta = [item.organizer_location.name if item.organizer_location_id else '',
                    '' if item.is_at_organizer_location else item.venue_label]
            image = item.cover_url
        else:
            meta = [item.venue_label]
            image = item.venue_location.cover_url if item.venue_location_id else None
        status = status or ('past' if past else None)
    title = item.title if kind == 'table' else item.name
    participation, actions = None, []
    if mine:
        if not past and getattr(item, 'playing' if kind == 'table' else 'attending', False):
            participation = kind
        user = context.get('user')
        if kind == 'table' and not item.event_id and user and item.author_id == getattr(
                getattr(user, 'user_profile', None), 'id', None):
            if item.status != item.CLOSED and item.location_id:
                actions.append((_('Edit'), reverse('location-table-update', args=[item.location.slug, item.slug]),
                                'pencil'))
            actions.append((_('Duplicate table'), reverse('table-duplicate', args=[item.slug]), 'copy'))
    return result_row(item.get_absolute_url(), ' · '.join(str(part) for part in kicker if part), title,
                      meta=meta, status=status, image_url=image, participation=participation, actions=actions)


@register.inclusion_tag("components/create_menu.html", takes_context=True)
def create_menu(context, menu_id, location=None, primary=False, trigger_id=None, secondary_class="",
                icon_class=None):
    """The "+ Create" menu (plan F1) with only the entries the viewer may use.

    Site-wide: a table (anonymous users go through the login first; on a location's or an
    event's pages, there), an event where the user
    may create one, a manifestation when signed in, a location for who doesn't run one yet.
    With `location`: a table and, if allowed, an event at that location."""
    from urllib.parse import urlencode

    from webapp.services.viewer import get_viewer

    viewer = get_viewer(context['request'])
    items = []
    if location is not None:
        items.append({'label': pgettext_lazy('create menu', 'Table'), 'hint': _('A game night here'), 'icon': 'bolt',
                      'url': reverse('location-table-create', args=[location.slug])})
        if viewer.event_creation_access(location).allowed:
            items.append({'label': pgettext_lazy('create menu', 'Event'), 'hint': _('One or more days of play here'), 'icon': 'calendar',
                          'url': reverse('location-event-create', args=[location.slug])})
    else:
        # On a location's or an event's pages the table goes there (table_new_view checks it)
        match = context['request'].resolver_match
        table_query = {}
        if match and match.url_name in ('location-detail', 'location-calendar'):
            table_query['location'] = match.kwargs.get('slug')
        elif match and match.url_name in ('event_detail', 'event-program'):
            table_query['event'] = match.kwargs.get('slug')
        table_url = reverse('table-new', query=table_query or None)
        if not viewer.is_authenticated:
            table_url = f"{reverse('login')}?{urlencode({'next': table_url})}"
        items.append({'label': pgettext_lazy('create menu', 'Table'), 'hint': _('A game night at a location'), 'icon': 'bolt',
                      'url': table_url})
        if viewer.can_create_events:
            items.append({'label': pgettext_lazy('create menu', 'Event'), 'hint': _('One or more days of play at a location'),
                          'icon': 'calendar', 'url': reverse('event-create')})
        if viewer.is_authenticated:
            items.append({'label': pgettext_lazy('create menu', 'Festival'), 'hint': _('Gathers the events of several locations'),
                          'icon': 'users', 'url': reverse('master-event-create')})
        if not viewer.managed_location_ids:
            items.append({'label': pgettext_lazy('create menu', 'Location'), 'hint': _('A club, a game library or a shop'),
                          'icon': 'map-pin', 'url': reverse('location-create')})
    return {'menu_id': menu_id, 'items': items, 'primary': primary, 'trigger_id': trigger_id,
            'secondary_class': secondary_class, 'icon_class': icon_class}
