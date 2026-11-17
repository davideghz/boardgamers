from datetime import timedelta

from django import forms
from django.db.models import Exists, OuterRef, Q, Subquery
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.views import View
from meta.views import Meta

from webapp.models import Event, EventDate, Location, LocationEvent, Table
from webapp.services.appointments import paginate_appointments
from webapp.views.table_views import _location_picker_sections


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


def _search_tables(query, location_slug, date_filters):
    tables = Table.objects.public().filter(location__isnull=False, **date_filters)
    if query:
        tables = tables.filter(
            Q(title__icontains=query) | Q(description__icontains=query) | Q(game__name__icontains=query),
        )
    if location_slug:
        tables = tables.filter(location__slug=location_slug)

    return tables.select_related('location', 'game')


def _search_location_events(query, location_slug, date_filters):
    events = LocationEvent.objects.filter(status=LocationEvent.PUBLISHED, **date_filters)
    if query:
        events = events.filter(Q(name__icontains=query) | Q(description__icontains=query))
    if location_slug:
        events = events.filter(host_location__slug=location_slug)
    return events.select_related('host_location')


def _search_manifestations(query, location_slug, date_filters, newest_first):
    # Select a single matching date per manifestation, with its own opening time.
    matching_dates = EventDate.objects.filter(event_id=OuterRef('pk'), **date_filters).order_by(
        '-date' if newest_first else 'date',
    )
    events = Event.objects.filter(status=Event.PUBLISHED).filter(Exists(matching_dates)).annotate(
        matching_date=Subquery(matching_dates.values('date')[:1]),
        matching_time=Subquery(matching_dates.values('opening_time')[:1]),
    )
    if query:
        events = events.filter(Q(name__icontains=query) | Q(description__icontains=query))
    # A sponsor association is not the venue of a manifestation.
    return events.none() if location_slug else events


class AppointmentSearchView(View):
    template_name = 'search/appointments.html'

    def get(self, request):
        params = request.GET.copy()
        if params.get('type') == 'events' and params.get('event_kind') == Event.Kind.MANIFESTATION:
            params['type'] = 'manifestations'
        params.pop('event_kind', None)
        params.pop('city', None)
        if params.get('when') != 'range':
            params.pop('date_from', None)
            params.pop('date_to', None)
        form = AppointmentSearchForm(params)
        valid = form.is_valid()
        search_type = form.cleaned_data.get('type') or 'all'
        when = form.cleaned_data.get('when') or 'upcoming'
        query = form.cleaned_data.get('q', '')
        location_slug = form.cleaned_data.get('location', '')
        date_errors = form.errors.get('date_from') or form.errors.get('date_to')

        context = {
            'search_type': search_type,
            'search_types': SEARCH_TYPES,
            'search_params': params,
            'when': when,
            'q': request.GET.get('q', '').strip(),
            'selected_location': location_slug,
            'selected_location_obj': Location.objects.filter(slug=location_slug).first() if location_slug else None,
            'location_picker_sections': _location_picker_sections(request) if search_type != 'manifestations' else [],
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
            'date_error': date_errors[0] if date_errors else '',
            'search_error': _("Check the search filters and try again.") if not valid and not date_errors else '',
            'meta': Meta(
                title=_('Search – Board-Gamers.com'),
                description=_('Find events and game tables on Board Gamers.'),
            ),
        }
        if valid:
            date_filters = _date_filters(
                when, timezone.localdate(), form.cleaned_data.get('date_from'), form.cleaned_data.get('date_to'),
            )
            newest_first = when == 'past'
            sources = {}
            if search_type in ('all', 'tables'):
                sources['table'] = _search_tables(query, location_slug, date_filters)
            if search_type in ('all', 'events'):
                sources['event'] = _search_location_events(query, location_slug, date_filters)
            if search_type in ('all', 'manifestations'):
                sources['manifestation'] = _search_manifestations(query, location_slug, date_filters, newest_first)
            page, items = paginate_appointments(sources, request.GET.get('page'), newest_first=newest_first)
            context.update(items=items, page_obj=page, paginator=page.paginator, is_paginated=page.has_other_pages())
        return render(request, self.template_name, context)
