from datetime import timedelta

from django import forms
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.views import View
from meta.views import Meta

from webapp.models import Event, EventDate, Location, MasterEvent, MasterEventDate, Table
from webapp.services.appointments import paginate_appointments, with_matching_day


SEARCH_TYPES = (
    ('all', pgettext_lazy('appointment search results', 'All')),
    ('events', _('Events')),
    ('tables', _('Tables')),
    ('manifestations', _('Manifestations')),
)


class AppointmentSearchForm(forms.Form):
    type = forms.ChoiceField(choices=SEARCH_TYPES, required=False)
    q = forms.CharField(max_length=200, required=False)
    location = forms.SlugField(max_length=144, required=False)
    organizer = forms.SlugField(max_length=144, required=False)
    when = forms.ChoiceField(
        choices=[(key, key) for key in ('upcoming', 'today', 'weekend', 'past', 'range')], required=False,
    )
    date_from = forms.DateField(required=False, input_formats=['%Y-%m-%d'])
    date_to = forms.DateField(required=False, input_formats=['%Y-%m-%d'])

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('when') != 'range' or 'date_from' in self.errors or 'date_to' in self.errors:
            return cleaned_data

        start = cleaned_data.get('date_from')
        end = cleaned_data.get('date_to')
        if not start or not end:
            self.add_error('date_from', _('Enter both a start and an end date.'))
        elif end < start:
            self.add_error('date_to', _('The end date must be on or after the start date.'))
        return cleaned_data


def _date_filters(when, today, start, end):
    if when == 'range':
        return {'date__range': (start, end)}
    if when == 'today':
        return {'date': today}
    if when == 'weekend':
        weekday = today.weekday()
        days_to_saturday = -1 if weekday == 6 else 5 - weekday
        saturday = today + timedelta(days=days_to_saturday)
        return {'date__range': (saturday, saturday + timedelta(days=1))}
    if when == 'past':
        return {'date__lt': today}
    return {'date__gte': today}


def _search_tables(query, venue, organizer, date_filters):
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
    return tables.select_related(
        'location', 'game', 'event__venue_location', 'event__organizer_location', 'event__master_event',
    )


def _search_events(query, venue, organizer, date_filters, newest_first):
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
    return with_matching_day(
        events.select_related('organizer_location', 'venue_location', 'master_event'),
        EventDate.objects.filter(event_id=OuterRef('pk'), **date_filters),
        newest_first=newest_first,
    )


def _search_manifestations(query, venue, organizer, date_filters, newest_first):
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
        days = days.filter(Exists(EventDate.objects.filter(
            event__master_event_id=OuterRef('master_event_id'), date=OuterRef('date'),
            event__status=Event.PUBLISHED, event__organizer_location__slug=organizer,
        )))
    return with_matching_day(masters.select_related('venue_location'), days, newest_first=newest_first)


def _filter_locations():
    public_events = Event.objects.filter(status=Event.PUBLISHED)
    locations = Location.objects.order_by('name', 'pk')
    venues = locations.filter(
        Exists(public_events.filter(venue_location_id=OuterRef('pk')))
        | Exists(MasterEvent.objects.filter(status=Event.PUBLISHED, venue_location_id=OuterRef('pk')))
        | Exists(Table.objects.filter(event__isnull=True, location_id=OuterRef('pk'))),
    )
    organizers = locations.filter(Exists(public_events.filter(organizer_location_id=OuterRef('pk'))))
    return venues, organizers


class AppointmentSearchView(View):
    template_name = 'search/appointments.html'

    def get(self, request):
        params = request.GET.copy()
        if params.get('when') != 'range':
            params.pop('date_from', None)
            params.pop('date_to', None)
        form = AppointmentSearchForm(params)
        valid = form.is_valid()
        search_type = form.cleaned_data.get('type') or 'all'
        when = form.cleaned_data.get('when') or 'upcoming'
        query = form.cleaned_data.get('q', '')
        location_slug = form.cleaned_data.get('location', '')
        organizer_slug = form.cleaned_data.get('organizer', '')
        date_errors = form.errors.get('date_from') or form.errors.get('date_to')

        venues, organizers = _filter_locations()
        context = {
            'search_type': search_type,
            'search_types': SEARCH_TYPES,
            'search_params': params,
            'when': when,
            'q': request.GET.get('q', '').strip(),
            'selected_location': location_slug,
            'venues': venues,
            'organizers': organizers,
            'selected_organizer': organizer_slug,
            'periods': [('upcoming', _('Upcoming')), ('today', _('Today')), ('weekend', _('This weekend')),
                        ('past', _('Past')), ('range', _('Custom date range'))],
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
            'date_error': date_errors[0] if date_errors else '',
            'search_error': _("Check the search filters and try again.") if not valid and not date_errors else '',
            'meta': Meta(
                title=_('Search – Board-Gamers.com'),
                description=_('Find events, game tables and manifestations on Board Gamers.'),
            ),
        }
        if valid:
            date_filters = _date_filters(
                when, timezone.localdate(), form.cleaned_data.get('date_from'), form.cleaned_data.get('date_to'),
            )
            newest_first = when == 'past'
            sources = {}
            if search_type in ('all', 'tables'):
                sources['table'] = _search_tables(query, location_slug, organizer_slug, date_filters)
            if search_type in ('all', 'events'):
                sources['event'] = _search_events(query, location_slug, organizer_slug, date_filters, newest_first)
            if search_type in ('all', 'manifestations'):
                sources['manifestation'] = _search_manifestations(
                    query, location_slug, organizer_slug, date_filters, newest_first,
                )
            page, items = paginate_appointments(sources, request.GET.get('page'), newest_first=newest_first)
            context.update(items=items, page_obj=page, paginator=page.paginator, is_paginated=page.has_other_pages())
        return render(request, self.template_name, context)
