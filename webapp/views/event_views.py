import datetime
import json
import logging
from collections import defaultdict
from functools import wraps
from itertools import groupby

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Max, Min, Prefetch, Q, prefetch_related_objects
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from webapp import emails
from webapp.forms import (
    EventTableForm, EventForm, EventManageDataForm, EventDateForm, EventDateTimesForm, PlayAreaForm, PhysicalTableForm,
    AddEventManagerForm, AddSponsorLocationForm, AddTableCreatorForm, TableLinkFormSet,
    EventTableCategoryForm, EventGameForm, EventGameTagForm, LocationEventForm, LocationEventDateForm,
)
from webapp.views.table_views import BaseTableDetailView, _links_formset_open, create_location_table
from meta.views import Meta
from phonenumber_field.phonenumber import to_python

from webapp.models import Event, LocationEvent, Table, Player, Game, PlayArea, EventDate, Location, PhysicalTable, EventTableCategory, EventGame, EventGameTag
from webapp.services.event_games import attach_booking_dates, featured_games, library_queryset

logger = logging.getLogger(__name__)


class EventCreateView(LoginRequiredMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = 'events/event_create.html'

    def form_valid(self, form):
        form.instance.creator = self.request.user.user_profile
        response = super().form_valid(form)
        messages.success(self.request, _("Event created as a draft. Publish it from this page when it's ready."))
        return response

    def get_success_url(self):
        return reverse('event-manage', kwargs={'slug': self.object.slug})


class LocationEventCreateView(LoginRequiredMixin, View):
    def get(self, request, location_slug):
        location = self.get_location(request, location_slug)
        return self.render_form(request, location, LocationEventForm(), LocationEventDateForm())

    def post(self, request, location_slug):
        location = self.get_location(request, location_slug)
        event = LocationEvent(host_location=location, creator=request.user.user_profile)
        form = LocationEventForm(request.POST, request.FILES, instance=event)
        date_form = LocationEventDateForm(request.POST)
        form_valid = form.is_valid()
        date_valid = date_form.is_valid()
        if not (form_valid and date_valid):
            return self.render_form(request, location, form, date_form)

        for field, value in date_form.cleaned_data.items():
            setattr(event, field, value)
        form.save()
        if event.can_publish(request.user):
            messages.success(request, _("Location event created. You can publish it from this page."))
        else:
            messages.success(request, _("Event created. The location managers can publish it."))
        return redirect(event.action_url('manage'))

    def get_location(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.can_create_events(request.user):
            raise PermissionDenied
        return location

    def render_form(self, request, location, form, date_form):
        return render(request, 'events/location_event_form.html', {
            'location': location, 'form': form, 'date_form': date_form,
            'can_manage_location_events': request.user.is_superuser or location.is_manager(request.user.user_profile),
        })


class LocationManageEventsView(LoginRequiredMixin, ListView):
    template_name = 'locations/location_manage_events.html'
    context_object_name = 'events'
    paginate_by = 20

    def get_queryset(self):
        self.location = get_object_or_404(Location, slug=self.kwargs['location_slug'])
        user = self.request.user
        if not (user.is_superuser or self.location.is_manager(user.user_profile)):
            raise PermissionDenied
        return (self.location.hosted_events.select_related('host_location')
                .order_by(F('date').desc(nulls_first=True), '-opening_time', '-pk'))

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            location=self.location, can_create_events=self.location.can_create_events(self.request.user), **kwargs,
        )


class EventManagerMixin(LoginRequiredMixin):
    """Ensures the logged-in user is a manager of the event (resolved via slug kwarg)."""

    event_model = Event

    def dispatch(self, request, *args, **kwargs):
        # Check before running the view: anonymous users fall through to
        # LoginRequiredMixin, which redirects them to the login page.
        if request.user.is_authenticated:
            event = self._get_event()
            if not self.can_manage_event(event, request.user):
                raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def _get_event(self):
        if not hasattr(self, '_event_cache'):
            events = self.event_model.objects.all()
            if self.event_model is LocationEvent:
                events = events.select_related('host_location').filter(host_location__slug=self.kwargs['location_slug'])
            self._event_cache = get_object_or_404(events, slug=self.kwargs['slug'])
        return self._event_cache

    def can_manage_event(self, event, user):
        return event.can_manage(user)


def legacy_location_event_route(view, location_event_route):
    """Keep bookmarks and already-open forms for events moved to LocationEvent."""
    @wraps(view)
    def dispatch(request, slug, *args, **kwargs):
        try:
            return view(request, *args, slug=slug, **kwargs)
        except Http404:
            return redirect_legacy_location_event(request, slug, location_event_route)

    return dispatch


def redirect_legacy_location_event(request, slug, location_event_route):
    event = get_object_or_404(LocationEvent.objects.select_related('host_location'), legacy_event_slug=slug)
    return redirect_location_event_action(request, event, location_event_route.removeprefix('location-event-'))


def redirect_unscoped_location_event(request, slug, action):
    event = get_object_or_404(LocationEvent.objects.select_related('host_location'), slug=slug)
    return redirect_location_event_action(request, event, action)


def redirect_location_event_action(request, event, action):
    url = event.action_url(action, query=request.GET)
    return redirect(url, preserve_request=request.method not in ('GET', 'HEAD'))


def _dates_with_gaps(event):
    """Sorted event dates, flagging the days that don't follow the previous one."""
    event_dates = event.sorted_dates
    for previous, current in zip(event_dates, event_dates[1:]):
        current.after_gap = (current.date - previous.date).days > 1
    return event_dates


def _location_event_tables(event):
    return event.tables.order_by('date', 'time', 'pk')


def _program_slots(tables):
    return [
        {'time': time, 'tables': list(group)}
        for time, group in groupby(tables, key=lambda table: table.time)
    ]


class EventPublicAccessMixin:
    """Resolve the event by slug, enforcing visibility (managers can preview
    their own unpublished events)."""

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if not event.is_published and not event.can_manage(self.request.user):
            raise Http404
        return event


class EventDetailView(EventPublicAccessMixin, DetailView):
    """Slim event landing page: intro, sponsors, contacts + CTA to the program."""
    context_object_name = 'event'
    queryset = Event.objects.select_related('creator')
    template_name = 'events/event_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        is_participant = bool(user_profile and event.participants.filter(
            user_profile=user_profile).exists())
        today = timezone.localdate()
        is_concluded = event.is_concluded(today)
        show_library = not event.is_location_event and event.enable_public_games
        games = featured_games(event) if show_library else []
        event_dates = _dates_with_gaps(event)
        context.update({
            'is_manager': event.can_manage(self.request.user),
            'is_participant': is_participant,
            'just_joined': is_participant and self.request.session.pop(
                'event_just_joined', None) == event.get_absolute_url(),
            'needs_phone': not event.is_location_event and is_participant and not user_profile.phone,
            'participant_count': event.participants.count(),
            'event_dates': event_dates,
            'today': today,
            'is_concluded': is_concluded,
            'featured_games': games,
            'has_library': show_library and (bool(games) or event.games.exists()),
            'can_view_program': not event.is_location_event and event.can_view_program(self.request.user),
            # Public link to the program: only while table booking is on.
            'program_url': (
                reverse('event-program', kwargs={'slug': event.slug})
                if not event.is_location_event and event.table_booking_enabled else None),
            'show_custom_button': bool(event.custom_button_title and event.custom_button_url),
        })
        if user_profile and not event.is_location_event and event.table_booking_enabled:
            my_agenda, my_tables_overlap = self._my_tables_agenda(event, user_profile)
            context['my_tables_agenda'] = my_agenda
            context['my_tables_overlap'] = my_tables_overlap
        context['meta'] = event.as_meta(self.request)
        event_data = event.structured_data(self.request)
        context['event_jsonld'] = (
            json.dumps(event_data, ensure_ascii=False) if event_data else None)
        return context

    @staticmethod
    def _my_tables_agenda(event, user_profile):
        """Agenda (grouped by date, then time) of the tables this user joined in
        the event, plus a flag set when two of them overlap in time."""
        tables = list(
            Table.objects
            .filter(event=event, players=user_profile)
            .select_related('game', 'play_area', 'physical_table', 'category', 'event')
            .prefetch_related('player_set')
            .order_by('date', 'time')
        )
        # Mark every table that overlaps another one this user joined.
        has_overlap = False
        for i, table in enumerate(tables):
            for other in tables[i + 1:]:
                if table.overlaps_with(other):
                    has_overlap = True
                    table.overlaps = other.overlaps = True

        agenda = [
            {
                'date': day,
                'slots': [
                    {'time': slot_time, 'tables': list(slot_tables)}
                    for slot_time, slot_tables in groupby(day_tables, key=lambda t: t.time)
                ],
            }
            for day, day_tables in (
                (day, list(group))
                for day, group in groupby(tables, key=lambda t: t.date)
            )
        ]
        return agenda, has_overlap


class LocationEventDetailView(EventDetailView):
    queryset = LocationEvent.objects.select_related('host_location')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.object.host_location
        user = self.request.user
        context['event_members_only'] = location.event_join_permission == Location.PERM_MEMBERS_ONLY
        context['cannot_join_event'] = (
            user.is_authenticated and not context['is_participant'] and not location.can_join_events(user.user_profile)
        )
        if self.object.status != LocationEvent.PUBLISHED and not self.object.can_publish(user):
            return context
        tables = list(self.object.tables.select_related(
            'game', 'play_area', 'physical_table__play_area', 'category',
        ).order_by('time', 'pk'))
        if not tables:
            return context

        table_areas = {
            table.pk: table.physical_table.play_area if table.physical_table_id else table.play_area
            for table in tables
        }
        areas = {str(area.pk): area for area in table_areas.values() if area}
        games = {str(table.game_id): table.game for table in tables if table.game_id}
        selected_area = areas.get(self.request.GET.get('area')) if len(areas) > 1 else None
        selected_game = games.get(self.request.GET.get('game')) if len(games) > 1 else None
        shown = [table for table in tables if (
            (selected_area is None or table_areas[table.pk] == selected_area)
            and (selected_game is None or table.game_id == selected_game.pk)
        )]
        prefetch_related_objects(shown, 'player_set')
        context['location_program'] = {
            'slots': _program_slots(shown),
            'areas': sorted(areas.values(), key=lambda area: (area.order, area.name)) if len(areas) > 1 else [],
            'games': sorted(games.values(), key=lambda game: game.name) if len(games) > 1 else [],
            'selected_area': selected_area,
            'selected_game': selected_game,
        }
        return context


class EventGamesView(EventPublicAccessMixin, DetailView):
    """Public list of the games in the event's library."""
    model = Event
    template_name = 'events/event_games.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'
    paginate_by = 16

    def get_object(self, queryset=None):
        # Until the managers publish it, only they can see it, as a preview.
        event = super().get_object(queryset)
        if not event.enable_public_games:
            user = self.request.user
            if not (user.is_authenticated and (user.is_superuser or event.is_manager(user.user_profile))):
                raise Http404
        return event

    @staticmethod
    def _selected(options, raw_id):
        """The option whose id is `raw_id`, or None if it's missing or not valid."""
        return next((option for option in options if str(option.pk) == raw_id), None)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        tags = list(event.game_tags.all())
        sponsors = list(event.sponsor_locations.only('id', 'name').order_by('name'))
        selected_tag = self._selected(tags, self.request.GET.get('tag'))
        selected_sponsor = self._selected(sponsors, self.request.GET.get('sponsor'))
        q = self.request.GET.get('q', '').strip()

        entries = library_queryset(event)
        total_count = event.games.count()
        if q:
            entries = entries.filter(game__name__icontains=q)
        if selected_tag:
            entries = entries.filter(tags=selected_tag)
        if selected_sponsor:
            entries = entries.filter(sponsor_locations=selected_sponsor)

        paginator = Paginator(entries, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get('page'))
        is_concluded = event.is_concluded()
        context.update({
            'entries': attach_booking_dates(event, page_obj.object_list),
            'can_view_program': event.can_view_program(self.request.user),
            'total_count': total_count,
            'tags': tags,
            'sponsors': sponsors,
            'selected_tag': selected_tag,
            'selected_sponsor': selected_sponsor,
            'has_filters': bool(q or selected_tag or selected_sponsor),
            'q': q,
            'paginator': paginator,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'is_concluded': is_concluded,
            'meta': Meta(
                title=_("Games – %(name)s") % {'name': event.name},
                description=_("Board games available at %(name)s.") % {'name': event.name},
            ),
        })
        return context


def upcoming_events_queryset(limit=None, managed_event_ids=()):
    """Published events with at least one date today or later, ordered by their
    next upcoming date. Prefetches `dates` so Event.start_date/end_date are cheap.

    Drafts among `managed_event_ids` are included too, so their managers can
    find them before publishing; those still without dates come last."""
    today = timezone.localdate()
    visible = Q(status=Event.PUBLISHED)
    if managed_event_ids:
        visible |= Q(status=Event.DRAFT, pk__in=managed_event_ids)
    qs = (
        Event.objects.filter(visible)
        .annotate(
            next_date=Min('dates__date', filter=Q(dates__date__gte=today)),
            date_count=Count('dates'),
        )
        .filter(Q(next_date__isnull=False) | Q(status=Event.DRAFT, date_count=0))
        .prefetch_related('dates')
        .order_by(F('next_date').asc(nulls_last=True), 'name')
    )
    return qs[:limit] if limit else qs


class EventListView(View):
    """Public index of upcoming (and, optionally, past) published events, plus
    the drafts the user manages."""
    template_name = 'events/event_list.html'

    def get(self, request, *args, **kwargs):
        today = timezone.localdate()
        show_past = request.GET.get('past') == '1'
        past_events = (
            Event.objects.filter(status=Event.PUBLISHED)
            .exclude(dates__date__gte=today)
            .filter(dates__isnull=False)
            .annotate(last_date=Max('dates__date'))
            .prefetch_related('dates')
            .order_by('-last_date')
            .distinct()
        )
        managed_event_ids = self._managed_event_ids(request)
        context = {
            'managed_event_ids': managed_event_ids,
            'upcoming_events': upcoming_events_queryset(managed_event_ids=managed_event_ids),
            'past_events': past_events if show_past else past_events[:6],
            'has_past_events': past_events.exists(),
            'show_past': show_past,
            'today': today,
        }
        return render(request, self.template_name, context)

    @staticmethod
    def _managed_event_ids(request):
        if not request.user.is_authenticated:
            return set()
        user_profile = request.user.user_profile
        return set(
            Event.objects.filter(Q(creator=user_profile) | Q(managers=user_profile))
            .values_list('pk', flat=True))


def _station_conflict_ids(event, date):
    """Ids of tables that share a physical station with another table at an
    overlapping time on the same date (a scheduling conflict)."""
    if not date:
        return set()
    day_tables = list(
        Table.objects.filter(event=event, date=date, physical_table__isnull=False)
        .only('id', 'date', 'time', 'duration', 'physical_table_id')
    )
    by_station = defaultdict(list)
    for t in day_tables:
        by_station[t.physical_table_id].append(t)
    conflict_ids = set()
    for tables in by_station.values():
        tables.sort(key=lambda x: x.time)
        for i in range(len(tables)):
            for j in range(i + 1, len(tables)):
                if tables[i].overlaps_with(tables[j]):
                    conflict_ids.add(tables[i].id)
                    conflict_ids.add(tables[j].id)
    return conflict_ids


def _warn_station_conflict(request, table):
    """Non-blocking warning when a table shares its station with another table
    at an overlapping time."""
    if not table.physical_table_id:
        return
    others = Table.objects.filter(
        event_id=table.event_id, date=table.date,
        physical_table_id=table.physical_table_id,
    ).exclude(id=table.id)
    if any(table.overlaps_with(o) for o in others):
        messages.warning(request, _(
            "Warning: this station is already booked by another table at an overlapping time."))


def _build_program_grid(event, tables, selected_area):
    """Build a station/area × time grid. Columns adapt to the most granular
    structure available: stations, else play areas, else a single 'General'
    column ("area generale" fallback)."""
    UNASSIGNED = 'none'
    stations = list(event.physical_tables.select_related('play_area'))
    if selected_area:
        stations = [s for s in stations if s.play_area_id == selected_area.id]

    if stations:
        columns = [{'key': f's{s.id}', 'label': s.name,
                    'sub': s.play_area.name if s.play_area_id else ''} for s in stations]

        def col_key(t):
            return f's{t.physical_table_id}' if t.physical_table_id else UNASSIGNED
    else:
        areas = list(event.play_areas.all())
        if selected_area:
            areas = [a for a in areas if a.id == selected_area.id]
        columns = [{'key': f'a{a.id}', 'label': a.name, 'sub': ''} for a in areas]

        def col_key(t):
            return f'a{t.play_area_id}' if t.play_area_id else UNASSIGNED

    tables = list(tables)
    col_keys = {c['key'] for c in columns}
    if any(col_key(t) not in col_keys for t in tables):
        label = _('No station') if columns else _('General')
        columns = columns + [{'key': UNASSIGNED, 'label': label, 'sub': ''}]

    key_index = {c['key']: i for i, c in enumerate(columns)}
    rows = []
    for slot_time in sorted({t.time for t in tables}):
        cells = [[] for _ in columns]
        for t in tables:
            if t.time == slot_time:
                idx = key_index.get(col_key(t))
                if idx is not None:
                    cells[idx].append(t)
        rows.append({'time': slot_time, 'cells': cells})
    return {'columns': columns, 'rows': rows}


class EventProgramView(EventPublicAccessMixin, DetailView):
    """The event program: vertical time agenda with date/area/game filters."""
    model = Event
    template_name = 'events/event_program.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if not event.can_view_program(self.request.user):
            raise Http404
        return event

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        today = timezone.localdate()
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None

        is_manager = bool(user_profile and event.is_manager(user_profile))
        can_create_table = bool(user_profile and event.can_create_table(user_profile))

        # ── Date filtering ────────────────────────────────────────────────
        event_dates = event.dates.all()
        show_past = self.request.GET.get('show_past') == '1'

        # "All days" (date=all) lists every day one after the other; it's the
        # default until the event starts. Single-day events don't need it.
        has_many_dates = len(event_dates) > 1
        selected_date_str = self.request.GET.get('date')
        selected_date = None
        all_days = False
        if selected_date_str == 'all':
            all_days = has_many_dates
        elif selected_date_str:
            try:
                selected_date = datetime.date.fromisoformat(selected_date_str)
            except ValueError:
                pass
        elif has_many_dates and event_dates[0].date > today:
            all_days = True

        if not selected_date and not all_days:
            future_dates = event_dates.filter(date__gte=today)
            if future_dates.exists():
                selected_date = future_dates.first().date
            elif event_dates.exists():
                selected_date = event_dates.first().date

        # Dates shown in pills (past hidden unless show_past)
        visible_dates = event_dates if show_past else event_dates.filter(date__gte=today)
        has_past_dates = event_dates.filter(date__lt=today).exists()

        # ── Area filtering ────────────────────────────────────────────────
        play_areas = event.play_areas.all()
        selected_area_id = self.request.GET.get('area')
        selected_area = None
        if selected_area_id:
            try:
                selected_area = play_areas.get(id=selected_area_id)
            except PlayArea.DoesNotExist:
                pass

        # ── Game filtering ────────────────────────────────────────────────
        selected_game_id = self.request.GET.get('game')
        selected_game = None
        if selected_game_id:
            try:
                selected_game_id = int(selected_game_id)
                selected_game = Game.objects.filter(id=selected_game_id).first()
                if not selected_game:
                    selected_game_id = None
            except (ValueError, TypeError):
                selected_game_id = None

        # ── Category filtering ────────────────────────────────────────────
        categories = event.table_categories.all()
        selected_category_id = self.request.GET.get('category')
        selected_category = None
        if selected_category_id:
            try:
                selected_category = categories.get(id=selected_category_id)
            except (EventTableCategory.DoesNotExist, ValueError):
                selected_category_id = None

        # ── Tables queryset ───────────────────────────────────────────────
        tables_qs = (
            event.tables
            .select_related('game', 'author', 'author__user', 'play_area', 'physical_table', 'category')
            .prefetch_related(
                Prefetch('player_set', queryset=Player.objects.select_related('user_profile__user', 'guest_profile'))
            )
        )
        if selected_date:
            tables_qs = tables_qs.filter(date=selected_date)
        elif all_days:
            tables_qs = tables_qs.filter(date__in=[d.date for d in visible_dates])
        if selected_area:
            # Effective area: from the assigned station, or the table's own area.
            tables_qs = tables_qs.filter(
                Q(physical_table__play_area=selected_area) |
                Q(physical_table__isnull=True, play_area=selected_area)
            )
        if selected_game_id:
            tables_qs = tables_qs.filter(game_id=selected_game_id)
        if selected_category:
            tables_qs = tables_qs.filter(category=selected_category)

        tables_qs = tables_qs.order_by('date', 'time')

        # ── Flag scheduling conflicts (same station, overlapping time) ─────
        if all_days:
            conflict_ids = set().union(
                *(_station_conflict_ids(event, d.date) for d in visible_dates))
        else:
            conflict_ids = _station_conflict_ids(event, selected_date)
        tables_list = list(tables_qs)
        for t in tables_list:
            t.has_conflict = t.id in conflict_ids

        # ── View mode: vertical agenda (default) or station/area grid ──────
        # The grid is per day, so "all days" is always an agenda.
        view_mode = 'grid' if self.request.GET.get('view') == 'grid' and not all_days else 'list'
        agenda_days = [
            {
                'date': day,
                'slots': _program_slots(day_tables),
            }
            for day, day_tables in groupby(tables_list, key=lambda tb: tb.date)
        ]
        grid = _build_program_grid(event, tables_list, selected_area) if view_mode == 'grid' else None

        # ── Games present in this event (for the filter modal) ────────────
        game_ids = (
            Table.objects
            .filter(event=event, game__isnull=False)
            .values_list('game_id', flat=True)
            .distinct()
        )
        games_in_event = Game.objects.filter(id__in=game_ids).order_by('name')

        context.update({
            'event': event,
            'is_manager': is_manager,
            'can_create_table': can_create_table,
            'event_dates': event_dates,
            'visible_dates': visible_dates,
            'has_past_dates': has_past_dates,
            'show_past': show_past,
            'play_areas': play_areas,
            'selected_date': selected_date,
            'all_days': all_days,
            'has_many_dates': has_many_dates,
            'selected_area': selected_area,
            'selected_game_id': selected_game_id,
            'selected_game': selected_game,
            'categories': categories,
            'selected_category_id': selected_category_id,
            'selected_category': selected_category,
            # Shown on the mobile "Filters" button; the day is navigation, not a filter
            'active_filter_count': sum(bool(f) for f in (selected_area, selected_category, selected_game)),
            'view_mode': view_mode,
            'view_qs': '&view=grid' if view_mode == 'grid' else '',
            'agenda_days': agenda_days,
            'grid': grid,
            'has_tables': bool(tables_list),
            'has_conflicts': bool(conflict_ids),
            'games_in_event': games_in_event,
            'today': today,
            'is_concluded': event.is_concluded(today),
        })
        context['meta'] = event.as_meta(self.request)
        return context


class EventJoinView(LoginRequiredMixin, View):
    """Register the logged-in user as a participant of the event."""

    event_model = Event

    def post(self, request, slug):
        event = get_object_or_404(self.event_model, slug=slug)
        user_profile = request.user.user_profile
        if not event.is_published and (event.is_location_event or not event.can_manage(request.user)):
            raise Http404
        if event.is_location_event and not event.host_location.can_join_events(user_profile):
            raise PermissionDenied(_('This event is reserved for members.'))
        if event.is_concluded():
            messages.info(request, _("This event has already ended, registration is closed."))
            return redirect(event)
        participant, created = event.participants.get_or_create(user_profile=user_profile)
        if created:
            # Shown once by the detail page as a confirmation modal with the share CTA
            request.session['event_just_joined'] = event.get_absolute_url()
        else:
            messages.info(request, _("You are already registered for this event."))
        return redirect(event)


class EventLeaveView(LoginRequiredMixin, View):
    """Unregister the logged-in user from the event (not allowed once it ended)."""

    event_model = Event

    def post(self, request, slug):
        event = get_object_or_404(self.event_model, slug=slug)
        if event.is_concluded():
            messages.info(request, _("This event has already ended, you can't leave it."))
            return redirect(event)
        deleted, _rows = event.participants.filter(user_profile=request.user.user_profile).delete()
        if deleted:
            messages.success(request, _("You are no longer attending this event."))
        return redirect(event)


class EventSavePhoneView(LoginRequiredMixin, View):
    """Save the phone number a participant enters from the event page banner."""

    def post(self, request, slug):
        get_object_or_404(Event, slug=slug)
        user_profile = request.user.user_profile
        raw = (request.POST.get('phone') or '').strip()
        # intl-tel-input posts E.164, but validate server-side too: parse with
        # region IT so national numbers still work if JS is disabled.
        number = to_python(raw, region='IT') if raw else None
        if number and number.is_valid():
            user_profile.phone = number
            user_profile.save(update_fields=['phone'])
            messages.success(request, _("Phone number saved."))
        else:
            messages.error(request, _("Please enter a valid phone number."))
        return redirect('event_detail', slug=slug)


class EventTableDetailView(BaseTableDetailView):
    template_name = 'events/event_table_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'table_slug'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(event__slug=self.kwargs['event_slug'])

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(Event, slug=kwargs['event_slug'])
        if not event.is_published:
            user_profile = request.user.user_profile if request.user.is_authenticated else None
            if not (request.user.is_superuser or (user_profile and event.is_manager(user_profile))):
                raise Http404
        return super().dispatch(request, *args, **kwargs)

    def get_comment_redirect(self):
        return redirect('event_table_detail',
                        event_slug=self.kwargs['event_slug'],
                        table_slug=self.object.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = get_object_or_404(Event, slug=self.kwargs['event_slug'])
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        table = self.get_object()
        # Phone buttons on participants are visible only to the table author,
        # event managers, event table creators ("table admin") and superusers.
        can_view_player_phones = bool(
            self.request.user.is_superuser
            or (user_profile and (
                table.author_id == user_profile.id
                or event.can_create_table(user_profile)
            ))
        )
        context.update({
            'event': event,
            'is_event_manager': self.is_table_host,  # an event table: its host is the event
            'can_view_player_phones': can_view_player_phones,
        })
        return context


@login_required
def event_table_create_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    user_profile = request.user.user_profile

    if not event.can_create_table(user_profile) and not request.user.is_superuser:
        messages.error(request, _("You don't have permission to create tables at this event."), extra_tags="danger")
        return redirect('event_detail', slug=event_slug)

    if not event.dates.exists():
        messages.error(request, _("You must define at least one date for the event before creating tables."), extra_tags="danger")
        return redirect('event_detail', slug=event_slug)

    initial = {}
    if date_param := request.GET.get('date'):
        initial['date'] = date_param
    if area_param := request.GET.get('area'):
        try:
            initial['play_area'] = PlayArea.objects.get(id=area_param, event=event)
        except PlayArea.DoesNotExist:
            pass

    if request.method == 'POST':
        form = EventTableForm(request.POST, request.FILES, event=event)
        link_formset = TableLinkFormSet(request.POST)
        if form.is_valid() and link_formset.is_valid():
            table = form.save(commit=False)
            table.author = user_profile
            table.save()
            form.save_m2m()
            link_formset.instance = table
            link_formset.save()
            if request.POST.get("join_table"):
                with transaction.atomic():
                    table.players.add(user_profile)
            messages.success(request, _("Table was created successfully"))
            _warn_station_conflict(request, table)
            return redirect('event_table_detail', event_slug=event_slug, table_slug=table.slug)
    else:
        form = EventTableForm(initial=initial, event=event)
        link_formset = TableLinkFormSet()

    return render(request, 'events/event_table_add_or_edit.html', {
        'form': form,
        'event': event,
        'link_formset': link_formset,
        'links_formset_open': _links_formset_open(link_formset),
    })


@login_required
def event_table_update_view(request, event_slug, table_slug):
    event = get_object_or_404(Event, slug=event_slug)
    table = get_object_or_404(Table, slug=table_slug, event=event)
    user_profile = request.user.user_profile

    if not (request.user.is_superuser or table.author == user_profile or event.is_manager(user_profile)):
        messages.error(request, _("You don't have permission to edit this table."), extra_tags="danger")
        return redirect('event_table_detail', event_slug=event_slug, table_slug=table_slug)

    if request.method == 'POST':
        form = EventTableForm(request.POST, request.FILES, instance=table, event=event)
        link_formset = TableLinkFormSet(request.POST, instance=table)
        if form.is_valid() and link_formset.is_valid():
            table = form.save(commit=False)
            table.save()
            form.save_m2m()
            link_formset.save()
            messages.success(request, _("Table was updated successfully"))
            _warn_station_conflict(request, table)
            return redirect('event_table_detail', event_slug=event_slug, table_slug=table.slug)
    else:
        form = EventTableForm(instance=table, event=event)
        link_formset = TableLinkFormSet(instance=table)

    return render(request, 'events/event_table_add_or_edit.html', {
        'form': form,
        'event': event,
        'table': table,
        'link_formset': link_formset,
        'links_formset_open': _links_formset_open(link_formset),
    })


class EventManageIndexView(LoginRequiredMixin, DetailView):
    context_object_name = 'event'
    queryset = Event.objects.all()
    template_name = 'events/event_manage_index.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        if not event.can_manage(self.request.user):
            raise Http404
        return event

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        if event.is_location_event:
            return context
        if event.status == Event.DRAFT:
            context['missing_publish_requirements'] = event.missing_publish_requirements()
        elif event.is_published:
            # Spelled out in the "back to draft" confirmation: these people lose the page.
            context['participant_count'] = event.participants.count()
            context['table_count'] = event.tables.count()
        return context


class EventPublishView(EventManagerMixin, View):
    """Publish a draft event right away. Admins hear about it, so they can block
    an abusive one after the fact."""

    def post(self, request, slug):
        event = self._get_event()
        if event.status == Event.BLOCKED:
            messages.error(request, _("This event was blocked by an admin and can't be published."),
                           extra_tags="danger")
        elif event.is_published:
            messages.info(request, _("This event is already published."))
        elif missing := event.missing_publish_requirements():
            messages.error(request, _("Before publishing: %(missing)s.") % {
                'missing': ', '.join(str(item).lower() for item in missing)}, extra_tags="danger")
        else:
            event.status = Event.PUBLISHED
            event.save(update_fields=['status', 'updated_at'])
            # The event is already published: a mail error must not turn it into a 500.
            try:
                emails.send_admin_notification_event_published(event, request.user.user_profile)
            except Exception:
                logger.exception("Could not notify the admin about event %s", event.pk)
            messages.success(request, _("Your event is published and visible to everyone."))
        return redirect('event-manage', slug=slug)


class EventUnpublishView(EventManagerMixin, View):
    """Bring a published event back to draft, hiding it from everyone but its managers."""

    def post(self, request, slug):
        event = self._get_event()
        if event.is_published:
            event.status = Event.DRAFT
            event.save(update_fields=['status', 'updated_at'])
            messages.success(request, _("The event is back to draft and no longer visible to the public."))
        return redirect('event-manage', slug=slug)


# ── Event management sub-views ────────────────────────────────────────────────

class LocationEventManageIndexView(EventManageIndexView):
    queryset = LocationEvent.objects.select_related('host_location')

    def get_queryset(self):
        return super().get_queryset().filter(host_location__slug=self.kwargs['location_slug'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        can_manage_location_events = event.can_publish(self.request.user)
        can_approve_event = can_manage_location_events and event.status == LocationEvent.DRAFT
        context.update(
            can_manage_location_events=can_manage_location_events,
            can_approve_event=can_approve_event,
            has_publishable_date=can_approve_event and event.has_publishable_date(),
        )
        if can_manage_location_events:
            context['location_event_tables'] = _location_event_tables(event)
        return context


class LocationEventTableCreateView(LoginRequiredMixin, View):
    def get(self, request, location_slug, slug):
        return self._create(request, location_slug, slug, LocationEvent.objects.select_related('host_location'))

    @transaction.atomic
    def post(self, request, location_slug, slug):
        return self._create(request, location_slug, slug, LocationEvent.objects.select_for_update(of=('self',)))

    def _create(self, request, location_slug, slug, events):
        event = get_object_or_404(events, host_location__slug=location_slug, slug=slug)
        if not event.can_publish(request.user):
            raise PermissionDenied
        if not event.date:
            messages.error(request, _('Set the event date before adding tables.'))
            return redirect(event.action_url('manage-dates'))
        return create_location_table(request, event.host_location, event)


class LocationEventApproveView(LoginRequiredMixin, View):
    @transaction.atomic
    def post(self, request, location_slug, slug):
        events = LocationEvent.objects.select_for_update(of=('self',)).select_related('host_location')
        event = get_object_or_404(events, host_location__slug=location_slug, slug=slug)
        if not event.can_publish(request.user):
            raise PermissionDenied

        if event.status != LocationEvent.DRAFT:
            messages.info(request, _("Only events awaiting approval can be approved."))
        elif not event.has_publishable_date():
            messages.error(request, _("Add an upcoming date before publishing."))
            return redirect(event.action_url('manage-dates'))
        else:
            event.status = LocationEvent.PUBLISHED
            event.save(update_fields=['status', 'updated_at'])
            messages.success(request, _("Event approved and published."))
        return redirect(event.action_url('manage'))


class EventManageDataView(EventManagerMixin, UpdateView):
    model = Event
    form_class = EventManageDataForm
    template_name = 'events/event_manage_data.html'
    context_object_name = 'event'

    def get_object(self, queryset=None):
        return self._get_event()

    def get_success_url(self):
        messages.success(self.request, _("Event updated successfully"))
        return self.object.action_url('manage')


class LocationEventManageDataView(EventManageDataView):
    event_model = LocationEvent
    model = LocationEvent
    form_class = LocationEventForm
    template_name = 'events/location_event_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['location'] = self.object.host_location
        return context

    def form_valid(self, form):
        with transaction.atomic():
            event = get_object_or_404(LocationEvent.objects.select_for_update(of=('self',)), pk=self.object.pk,
                                      host_location__slug=self.kwargs['location_slug'])
            if not event.can_manage(self.request.user):
                raise PermissionDenied
            # Schedule and publication can be updated from their own screens.
            self.object = form.save(commit=False)
            fields = ['name', 'description', 'updated_at']
            if 'cover' in form.changed_data:
                fields.append('cover')
            self.object.save(update_fields=fields)
        return redirect(self.get_success_url())


class EventManageDatesView(EventManagerMixin, View):
    template_name = 'events/event_manage_dates.html'

    def get(self, request, slug):
        return self.render_dates(request, self._get_event(), EventDateForm())

    @transaction.atomic
    def post(self, request, slug):
        event = self._get_event()
        form = EventDateForm(request.POST)
        if form.is_valid():
            EventDate.objects.update_or_create(
                event=event, date=form.cleaned_data['date'],
                defaults={
                    'opening_time': form.cleaned_data['opening_time'],
                    'closing_time': form.cleaned_data['closing_time'],
                },
            )
            messages.success(request, _("Date added."))
            return redirect('event-manage-dates', slug=slug)
        return self.render_dates(request, event, form)

    def render_dates(self, request, event, form):
        return render(request, self.template_name, {'event': event, 'dates': event.dates.all(), 'form': form})


class LocationEventManageDatesView(EventManagerMixin, View):
    event_model = LocationEvent

    def get(self, request, location_slug, slug):
        event = self._get_event()
        initial = {'date': event.date, 'opening_time': event.opening_time, 'closing_time': event.closing_time}
        return self.render_dates(request, event, LocationEventDateForm(initial=initial if event.date else {}))

    @transaction.atomic
    def post(self, request, location_slug, slug):
        event = get_object_or_404(LocationEvent.objects.select_for_update(of=('self',)), pk=self._get_event().pk,
                                  host_location__slug=location_slug)
        if not event.can_manage(request.user):
            raise PermissionDenied
        form = LocationEventDateForm(request.POST)
        if form.is_valid():
            for field, value in form.cleaned_data.items():
                setattr(event, field, value)
            event.save(update_fields=['date', 'opening_time', 'closing_time', 'updated_at'])
            messages.success(request, _("Date saved."))
            return redirect(event.action_url('manage'))
        return self.render_dates(request, event, form)

    def render_dates(self, request, event, form):
        return render(request, 'events/location_event_date.html', {'event': event, 'form': form})


class EventManageDateUpdateView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        event_date = get_object_or_404(EventDate, pk=pk, event=event)
        form = EventDateTimesForm(request.POST, instance=event_date)
        if form.is_valid():
            form.save()
            messages.success(request, _("Opening hours updated."))
        else:
            messages.error(request, _("Invalid time."))
        return redirect('event-manage-dates', slug=slug)


class EventManageDateDeleteView(EventManagerMixin, View):
    @transaction.atomic
    def post(self, request, slug, pk):
        event = Event.objects.select_for_update().get(pk=self._get_event().pk)
        occurrence = get_object_or_404(EventDate, pk=pk, event=event)
        if event.status == Event.PUBLISHED and not event.dates.exclude(pk=pk).exists():
            messages.error(request, _("A published event needs at least one date. Add a replacement first."))
            return redirect('event-manage-dates', slug=slug)
        occurrence.delete()
        messages.success(request, _("Date removed."))
        return redirect('event-manage-dates', slug=slug)


class EventManageAreasView(EventManagerMixin, View):
    template_name = 'events/event_manage_areas.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'areas': event.play_areas.all(),
            'form': PlayAreaForm(event=event),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = PlayAreaForm(request.POST, event=event)
        if form.is_valid():
            area = form.save(commit=False)
            area.event = event
            max_order = event.play_areas.aggregate(m=Max('order'))['m'] or 0
            area.order = max_order + 1
            area.save()
            messages.success(request, _("Play area added."))
            return redirect('event-manage-areas', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'areas': event.play_areas.all(),
            'form': form,
        })


class EventManageAreaDeleteView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        PlayArea.objects.filter(pk=pk, event=event).delete()
        messages.success(request, _("Play area removed."))
        return redirect('event-manage-areas', slug=slug)


class EventManageAreasReorderView(EventManagerMixin, View):
    def post(self, request, slug):
        import json
        from django.http import JsonResponse
        event = self._get_event()
        try:
            data = json.loads(request.body)
            for item in data.get('areas', []):
                PlayArea.objects.filter(pk=item['id'], event=event).update(order=item['order'])
            return JsonResponse({'success': True})
        except Exception:
            return JsonResponse({'success': False}, status=400)


class EventManageCategoriesView(EventManagerMixin, View):
    template_name = 'events/event_manage_categories.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'categories': event.table_categories.all(),
            'form': EventTableCategoryForm(),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = EventTableCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.event = event
            max_order = event.table_categories.aggregate(m=Max('order'))['m'] or 0
            category.order = max_order + 1
            category.save()
            messages.success(request, _("Category added."))
            return redirect('event-manage-categories', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'categories': event.table_categories.all(),
            'form': form,
        })


class EventManageCategoryDeleteView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        EventTableCategory.objects.filter(pk=pk, event=event).delete()
        messages.success(request, _("Category removed."))
        return redirect('event-manage-categories', slug=slug)


class EventManageCategoriesReorderView(EventManagerMixin, View):
    def post(self, request, slug):
        import json
        from django.http import JsonResponse
        event = self._get_event()
        try:
            data = json.loads(request.body)
            for item in data.get('categories', []):
                EventTableCategory.objects.filter(pk=item['id'], event=event).update(order=item['order'])
            return JsonResponse({'success': True})
        except Exception:
            return JsonResponse({'success': False}, status=400)


class EventManageGamesView(EventManagerMixin, View):
    """The event's library and its tags, managed on the same page."""

    def get(self, request, slug):
        event = self._get_event()
        return render(request, 'events/event_manage_games.html', {
            'event': event,
            'entries': library_queryset(event),
            'tags': event.game_tags.all(),
            'tag_form': EventGameTagForm(event=event),
        })


class EventManageGamesToggleView(EventManagerMixin, View):
    """Show or hide the game library on the public event page."""

    def post(self, request, slug):
        event = self._get_event()
        event.enable_public_games = request.POST.get('enabled') == 'on'
        event.save(update_fields=['enable_public_games'])
        if event.enable_public_games:
            messages.success(request, _("The game library is now visible on the event page."))
        else:
            messages.success(request, _("The game library is now hidden from the event page."))
        return redirect('event-manage-games', slug=slug)


class EventManageGameAddView(EventManagerMixin, View):
    template_name = 'events/event_manage_game_detail.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event, 'entry': None, 'form': EventGameForm(event=event), 'is_new': True,
        })

    def post(self, request, slug):
        event = self._get_event()
        form = EventGameForm(request.POST, event=event)
        if form.is_valid():
            entry = form.save(commit=False)
            entry.event = event
            entry.save()
            form.save_m2m()
            messages.success(request, _("Game «%(name)s» added to the library.") % {'name': entry.game.name})
            if 'add_another' in request.POST:
                return redirect('event-manage-game-add', slug=slug)
            return redirect('event-manage-games', slug=slug)
        return render(request, self.template_name, {
            'event': event, 'entry': None, 'form': form, 'is_new': True,
        })


class EventManageGameDetailView(EventManagerMixin, View):
    template_name = 'events/event_manage_game_detail.html'

    def get(self, request, slug, game_uuid):
        event = self._get_event()
        entry = get_object_or_404(EventGame.objects.select_related('game'), uuid=game_uuid, event=event)
        return render(request, self.template_name, {
            'event': event, 'entry': entry, 'form': EventGameForm(instance=entry, event=event), 'is_new': False,
        })

    def post(self, request, slug, game_uuid):
        event = self._get_event()
        entry = get_object_or_404(EventGame.objects.select_related('game'), uuid=game_uuid, event=event)
        form = EventGameForm(request.POST, instance=entry, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, _("Game updated."))
            return redirect('event-manage-games', slug=slug)
        return render(request, self.template_name, {
            'event': event, 'entry': entry, 'form': form, 'is_new': False,
        })


class EventManageGameDeleteView(EventManagerMixin, View):
    def post(self, request, slug, game_uuid):
        event = self._get_event()
        entry = get_object_or_404(EventGame.objects.select_related('game'), uuid=game_uuid, event=event)
        game_name = entry.game.name
        entry.delete()
        messages.success(request, _("Game «%(name)s» removed from the library.") % {'name': game_name})
        return redirect('event-manage-games', slug=slug)


class EventManageGameTagAddView(EventManagerMixin, View):
    def post(self, request, slug):
        event = self._get_event()
        form = EventGameTagForm(request.POST, event=event)
        if form.is_valid():
            tag = form.save(commit=False)
            tag.event = event
            tag.order = (event.game_tags.aggregate(m=Max('order'))['m'] or 0) + 1
            tag.save()
            messages.success(request, _("Tag added."))
        else:
            messages.error(request, ' '.join(form.errors.get('name', [])))
        return redirect('event-manage-games', slug=slug)


class EventManageGameTagUpdateView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        tag = get_object_or_404(EventGameTag, pk=pk, event=event)
        form = EventGameTagForm(request.POST, instance=tag, event=event)
        if form.is_valid():
            form.save()
            messages.success(request, _("Tag updated."))
        else:
            messages.error(request, ' '.join(form.errors.get('name', [])))
        return redirect('event-manage-games', slug=slug)


class EventManageGameTagDeleteView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        EventGameTag.objects.filter(pk=pk, event=event).delete()
        messages.success(request, _("Tag removed."))
        return redirect('event-manage-games', slug=slug)


class EventManageGameTagsReorderView(EventManagerMixin, View):
    def post(self, request, slug):
        event = self._get_event()
        try:
            data = json.loads(request.body)
            for item in data.get('tags', []):
                EventGameTag.objects.filter(pk=item['id'], event=event).update(order=item['order'])
            return JsonResponse({'success': True})
        except Exception:
            return JsonResponse({'success': False}, status=400)


class EventManageParticipantsView(EventManagerMixin, View):
    template_name = 'events/event_manage_participants.html'

    def can_manage_event(self, event, user):
        return event.can_publish(user) if event.is_location_event else super().can_manage_event(event, user)

    def get(self, request, slug, location_slug=None):
        event = self._get_event()
        participants = event.participants.select_related('user_profile__user').order_by('-created_at')
        return render(request, self.template_name, {
            'event': event,
            'participants': participants,
        })


class EventManagePhysicalTablesView(EventManagerMixin, View):
    template_name = 'events/event_manage_physical_tables.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'physical_tables': event.physical_tables.select_related('play_area'),
            'form': PhysicalTableForm(event=event),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = PhysicalTableForm(request.POST, event=event)
        if form.is_valid():
            station = form.save(commit=False)
            station.event = event
            max_order = event.physical_tables.aggregate(m=Max('order'))['m'] or 0
            station.order = max_order + 1
            station.save()
            messages.success(request, _("Station added."))
            return redirect('event-manage-stations', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'physical_tables': event.physical_tables.select_related('play_area'),
            'form': form,
        })


class EventManagePhysicalTableDeleteView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        PhysicalTable.objects.filter(pk=pk, event=event).delete()
        messages.success(request, _("Station removed."))
        return redirect('event-manage-stations', slug=slug)


class EventManagePhysicalTablesReorderView(EventManagerMixin, View):
    def post(self, request, slug):
        import json
        from django.http import JsonResponse
        event = self._get_event()
        try:
            data = json.loads(request.body)
            for item in data.get('stations', []):
                PhysicalTable.objects.filter(pk=item['id'], event=event).update(order=item['order'])
            return JsonResponse({'success': True})
        except Exception:
            return JsonResponse({'success': False}, status=400)


class EventManageManagersView(EventManagerMixin, View):
    template_name = 'events/event_manage_managers.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'managers': event.managers.all(),
            'form': AddEventManagerForm(),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = AddEventManagerForm(request.POST)
        if form.is_valid():
            manager = form.cleaned_data['manager']
            event.managers.add(manager)
            messages.success(request, _("Manager added."))
            return redirect('event-manage-managers', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'managers': event.managers.all(),
            'form': form,
        })


class EventManageManagerRemoveView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        from webapp.models import UserProfile as UP
        manager = get_object_or_404(UP, pk=pk)
        event.managers.remove(manager)
        messages.success(request, _("Manager removed."))
        return redirect('event-manage-managers', slug=slug)


class EventManageTableCreatorsView(EventManagerMixin, View):
    template_name = 'events/event_manage_table_creators.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'table_creators': event.allowed_table_creators.all(),
            'form': AddTableCreatorForm(),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = AddTableCreatorForm(request.POST)
        if form.is_valid():
            table_creator = form.cleaned_data['table_creator']
            event.allowed_table_creators.add(table_creator)
            messages.success(request, _("Table creator added."))
            return redirect('event-manage-table-creators', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'table_creators': event.allowed_table_creators.all(),
            'form': form,
        })


class EventManageTableCreatorRemoveView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        from webapp.models import UserProfile as UP
        table_creator = get_object_or_404(UP, pk=pk)
        event.allowed_table_creators.remove(table_creator)
        messages.success(request, _("Table creator removed."))
        return redirect('event-manage-table-creators', slug=slug)


class EventManageLocationsView(EventManagerMixin, View):
    template_name = 'events/event_manage_locations.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'sponsor_locations': event.sponsor_locations.all(),
            'form': AddSponsorLocationForm(),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = AddSponsorLocationForm(request.POST)
        if form.is_valid():
            location = form.cleaned_data['location']
            event.sponsor_locations.add(location)
            messages.success(request, _("Location added."))
            return redirect('event-manage-locations', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'sponsor_locations': event.sponsor_locations.all(),
            'form': form,
        })


class EventManageLocationRemoveView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        location = get_object_or_404(Location, pk=pk)
        event.sponsor_locations.remove(location)
        messages.success(request, _("Location removed."))
        return redirect('event-manage-locations', slug=slug)
