from django import forms
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.views import View
from meta.views import Meta

from webapp.forms import LocationPickerWidget
from webapp.models import Event, EventDate, Location, MasterEvent, MasterEventDate, Table
from webapp.services.appointments import paginate_appointments, with_matching_day


SEARCH_TYPES = (
    ('all', pgettext_lazy('appointment search results', 'All')),
    ('events', _('Events')),
    ('tables', _('Tables')),
    ('master-events', _('Festivals')),
)


class AppointmentSearchForm(forms.Form):
    type = forms.ChoiceField(choices=SEARCH_TYPES, required=False)
    q = forms.CharField(max_length=200, required=False)
    location = forms.SlugField(
        label=_('Venue'), max_length=144, required=False,
        widget=LocationPickerWidget(button_label=_('Find a venue'), value_key='slug', scope='venue',
                                    chip_label=_('Venue')),
    )
    organizer = forms.SlugField(
        label=_('Organizing location'), max_length=144, required=False,
        widget=LocationPickerWidget(button_label=_('Find an organizing location'), value_key='slug',
                                    scope='organizer', chip_label=_('Organizing location')),
    )
    at = forms.SlugField(max_length=144, required=False)  # venue or organizer: the location page's links


def _search_tables(query, venue, organizer, at, date_filters):
    tables = Table.objects.public().filter(**date_filters)
    if query:
        tables = tables.filter(
            Q(title__icontains=query) | Q(description__icontains=query) | Q(game__name__icontains=query)
            | Q(event__name__icontains=query)
            | Q(event__master_event__status=Event.PUBLISHED, event__master_event__name__icontains=query)
        )
    if venue:
        tables = tables.filter(Q(event__isnull=True, location__slug=venue) | Q(event__venue_location__slug=venue))
    if organizer:
        tables = tables.filter(event__organizer_location__slug=organizer)
    if at:
        tables = tables.filter(Q(event__isnull=True, location__slug=at) | Q(event__venue_location__slug=at)
                               | Q(event__organizer_location__slug=at))
    return tables.select_related(
        'location', 'game', 'event__venue_location', 'event__organizer_location', 'event__master_event',
    )


def _search_events(query, venue, organizer, at, date_filters, newest_first):
    events = Event.objects.filter(status=Event.PUBLISHED)
    if query:
        events = events.filter(
            Q(name__icontains=query) | Q(description__icontains=query) | Q(venue_name__icontains=query)
            | Q(venue_location__name__icontains=query) | Q(organizer_location__name__icontains=query)
            | Q(city__icontains=query) | Q(address__icontains=query)
            | Q(master_event__status=Event.PUBLISHED, master_event__name__icontains=query)
        )
    if venue:
        events = events.filter(venue_location__slug=venue)
    if organizer:
        events = events.filter(organizer_location__slug=organizer)
    if at:
        events = events.filter(Q(venue_location__slug=at) | Q(organizer_location__slug=at))
    return with_matching_day(
        events.select_related('organizer_location', 'venue_location', 'master_event'),
        EventDate.objects.filter(event_id=OuterRef('pk'), **date_filters),
        newest_first=newest_first,
    )


def _organized_that_day(organizer):
    """A manifestation day on which a published event of `organizer` takes place."""
    return Exists(EventDate.objects.filter(
        event__master_event_id=OuterRef('master_event_id'), date=OuterRef('date'),
        event__status=Event.PUBLISHED, event__organizer_location__slug=organizer,
    ))


def _search_manifestations(query, venue, organizer, at, date_filters, newest_first):
    masters = MasterEvent.objects.filter(status=Event.PUBLISHED)
    if query:
        masters = masters.filter(
            Q(name__icontains=query) | Q(description__icontains=query) | Q(venue_name__icontains=query)
            | Q(venue_location__name__icontains=query) | Q(city__icontains=query) | Q(address__icontains=query),
        )
    if venue:
        masters = masters.filter(venue_location__slug=venue)
    days = MasterEventDate.objects.filter(master_event_id=OuterRef('pk'), **date_filters)
    if organizer:
        days = days.filter(_organized_that_day(organizer))
    if at:
        days = days.filter(Q(master_event__venue_location__slug=at) | _organized_that_day(at))
    return with_matching_day(masters.select_related('venue_location'), days, newest_first=newest_first)


def _without(params, *keys):
    """The current query string without `keys` (and the page)."""
    remaining = params.copy()
    for key in (*keys, 'page'):
        remaining.pop(key, None)
    return f'?{remaining.urlencode()}' if remaining else '?'


def _legacy_params(params):
    """The filters of the old /tables/ and /events/ lists, in the search's terms."""
    tab, past = params.pop('tab', [''])[-1], params.pop('past', [''])[-1]
    if tab == 'past' or past == '1':
        params.setdefault('when', 'past')
    return params


def _drafts(user, search_type):
    """Events or manifestations not yet published that `user` may see: the old lists showed
    them to their managers, the search keeps them apart from the results."""
    if not user.is_authenticated:
        return []
    if search_type == 'events':
        drafts = Event.objects.managed_by(user.user_profile).filter(status=Event.DRAFT)
        return [('event', event) for event in drafts.select_related('organizer_location', 'venue_location')]
    if search_type == 'master-events':
        drafts = MasterEvent.objects.exclude(status=Event.PUBLISHED).select_related('venue_location')
        if not MasterEvent.can_approve(user):
            drafts = drafts.filter(managers__user=user).distinct()
        return [('manifestation', master) for master in drafts]
    return []


#: The old lists, now the search with the type preset: (URL name, title, description).
PRESETS = {
    'tables': ('table-index', _('Game Tables'), _('Discover all available game tables and join the game!')),
    'events': ('event-index', _('Events'), _('Conventions, tournaments and game days near you.')),
    'master-events': ('master-event-list', _('Festivals'), _('Fairs and festivals that gather several events.')),
}


class AppointmentSearchView(View):
    template_name = 'search/appointments.html'
    #: 'tables', 'events' or 'master-events' for /tables/, /events/ and /master-events/
    preset = None

    def get(self, request):
        params = request.GET.copy()
        if self.preset:
            params = _legacy_params(params)
            params.pop('type', None)
        if params.get('when') != 'past':  # upcoming, and the periods of old links (today, weekend, range)
            params.pop('when', None)
        for key in ('date_from', 'date_to'):
            params.pop(key, None)
        form = AppointmentSearchForm(params)
        valid = form.is_valid()
        search_type = self.preset or form.cleaned_data.get('type') or 'all'
        past = params.get('when') == 'past'
        query = form.cleaned_data.get('q', '')
        places = {key: form.cleaned_data.get(key, '') for key in ('location', 'organizer', 'at')}

        if self.preset:
            title, description = PRESETS[self.preset][1:]
        else:
            title = pgettext_lazy('navigation', 'Activities')
            description = _('Find events, game tables and festivals on Board Gamers.')
        context = {
            'search_form': form,
            # The filters are chips that apply at once and show their own state; "Clear all"
            # keeps the type and the period
            'has_filters': bool(request.GET.get('q', '').strip() or any(places.values())),
            'reset_url': _without(params, 'q', 'location', 'organizer', 'at'),
            'at_name': (Location.objects.filter(slug=places['at']).values_list('name', flat=True).first()
                        or places['at']) if places['at'] else '',
            'search_type': search_type,
            'search_types': [(value, label, reverse(PRESETS[value][0]) if value in PRESETS
                              else reverse('appointment-search')) for value, label in SEARCH_TYPES],
            'search_params': params,
            'preset': self.preset,
            'page_title': dict(SEARCH_TYPES)[self.preset] if self.preset else title,  # as the type control
            'when': 'past' if past else 'upcoming',
            'q': request.GET.get('q', '').strip(),
            'selected_at': places['at'],
            'past': past,
            'search_error': '' if valid else _("Check the search filters and try again."),
            'meta': Meta(title=title, description=description),
        }
        if valid:
            date_filters = {'date__lt' if past else 'date__gte': timezone.localdate()}
            newest_first = past
            sources = {}
            if search_type in ('all', 'tables'):
                sources['table'] = _search_tables(query, *places.values(), date_filters)
            if search_type in ('all', 'events'):
                sources['event'] = _search_events(query, *places.values(), date_filters, newest_first)
            if search_type in ('all', 'master-events'):
                sources['manifestation'] = _search_manifestations(query, *places.values(), date_filters, newest_first)
            page, items = paginate_appointments(sources, request.GET.get('page'), newest_first=newest_first)
            context.update(items=items, page_obj=page, paginator=page.paginator, is_paginated=page.has_other_pages())
            if page.number == 1:
                context['drafts'] = _drafts(request.user, search_type)
        return render(request, self.template_name, context)
