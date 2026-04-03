import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import CreateView, DetailView, UpdateView

from webapp.forms import (
    EventTableForm, EventForm, EventDateForm, PlayAreaForm,
    AddEventManagerForm, AddSponsorLocationForm,
)
from webapp.models import Event, Table, Player, Game, PlayArea, EventDate, Location
from webapp.views.table_views import BaseTableDetailView


class EventCreateView(LoginRequiredMixin, CreateView):
    model = Event
    form_class = EventForm
    template_name = 'events/event_create.html'

    def form_valid(self, form):
        form.instance.creator = self.request.user.user_profile
        response = super().form_valid(form)
        messages.success(self.request, _("Event created! It will be published once approved by an admin."))
        return response

    def get_success_url(self):
        return reverse('event-manage', kwargs={'slug': self.object.slug})


class EventManagerMixin(LoginRequiredMixin):
    """Ensures the logged-in user is a manager of the event (resolved via slug kwarg)."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response
        event = self._get_event()
        user_profile = request.user.user_profile
        if not (request.user.is_superuser or event.is_manager(user_profile)):
            raise PermissionDenied
        return response

    def _get_event(self):
        if not hasattr(self, '_event_cache'):
            self._event_cache = get_object_or_404(Event, slug=self.kwargs['slug'])
        return self._event_cache


class EventDetailView(DetailView):
    model = Event
    template_name = 'events/event_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        if event.status != Event.APPROVED:
            if not user_profile or not event.is_manager(user_profile):
                raise Http404
        return event

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.object
        today = timezone.now().date()
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None

        is_manager = bool(user_profile and event.is_manager(user_profile))
        can_create_table = bool(user_profile and event.can_create_table(user_profile))

        # ── Date filtering ────────────────────────────────────────────────
        event_dates = event.dates.all()
        show_past = self.request.GET.get('show_past') == '1'

        selected_date_str = self.request.GET.get('date')
        selected_date = None
        if selected_date_str:
            try:
                selected_date = datetime.date.fromisoformat(selected_date_str)
            except ValueError:
                pass

        if not selected_date:
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

        # ── Tables queryset ───────────────────────────────────────────────
        tables_qs = (
            Table.objects
            .filter(event=event)
            .select_related('game', 'author', 'author__user', 'play_area')
            .prefetch_related(
                Prefetch('player_set', queryset=Player.objects.select_related('user_profile__user', 'guest_profile'))
            )
        )
        if selected_date:
            tables_qs = tables_qs.filter(date=selected_date)
        if selected_area:
            tables_qs = tables_qs.filter(play_area=selected_area)
        if selected_game_id:
            tables_qs = tables_qs.filter(game_id=selected_game_id)

        tables_qs = tables_qs.order_by('time')

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
            'selected_area': selected_area,
            'selected_game_id': selected_game_id,
            'selected_game': selected_game,
            'tables': tables_qs,
            'games_in_event': games_in_event,
            'today': today,
        })
        return context


class EventTableDetailView(BaseTableDetailView):
    template_name = 'events/event_table_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'table_slug'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(event__slug=self.kwargs['event_slug'])

    def dispatch(self, request, *args, **kwargs):
        event = get_object_or_404(Event, slug=kwargs['event_slug'])
        if event.status != Event.APPROVED:
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
        context.update({
            'event': event,
            'is_event_manager': bool(user_profile and event.is_manager(user_profile)),
        })
        return context


@login_required
def event_table_create_view(request, event_slug):
    event = get_object_or_404(Event, slug=event_slug)
    user_profile = request.user.user_profile

    if not event.can_create_table(user_profile) and not request.user.is_superuser:
        messages.error(request, _("You don't have permission to create tables at this event."), extra_tags="danger")
        return redirect('event_detail', slug=event_slug)

    initial = {'event': event}
    if date_param := request.GET.get('date'):
        initial['date'] = date_param
    if area_param := request.GET.get('area'):
        try:
            initial['play_area'] = PlayArea.objects.get(id=area_param, event=event)
        except PlayArea.DoesNotExist:
            pass

    if request.method == 'POST':
        form = EventTableForm(request.POST, event=event)
        if form.is_valid():
            table = form.save(commit=False)
            table.author = user_profile
            table.event = event
            table.save()
            form.save_m2m()
            with transaction.atomic():
                table.players.add(user_profile)
            messages.success(request, _("Table was created successfully"))
            return redirect('event_table_detail', event_slug=event_slug, table_slug=table.slug)
    else:
        form = EventTableForm(initial=initial, event=event)

    return render(request, 'events/event_table_add_or_edit.html', {'form': form, 'event': event})


@login_required
def event_table_update_view(request, event_slug, table_slug):
    event = get_object_or_404(Event, slug=event_slug)
    table = get_object_or_404(Table, slug=table_slug, event=event)
    user_profile = request.user.user_profile

    if not (request.user.is_superuser or table.author == user_profile or event.is_manager(user_profile)):
        messages.error(request, _("You don't have permission to edit this table."), extra_tags="danger")
        return redirect('event_table_detail', event_slug=event_slug, table_slug=table_slug)

    if request.method == 'POST':
        form = EventTableForm(request.POST, instance=table, event=event)
        if form.is_valid():
            table = form.save(commit=False)
            table.event = event
            table.save()
            form.save_m2m()
            messages.success(request, _("Table was updated successfully"))
            return redirect('event_table_detail', event_slug=event_slug, table_slug=table.slug)
    else:
        form = EventTableForm(instance=table, event=event)

    return render(request, 'events/event_table_add_or_edit.html', {'form': form, 'event': event, 'table': table})


class EventManageIndexView(LoginRequiredMixin, DetailView):
    model = Event
    template_name = 'events/event_manage_index.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        event = super().get_object(queryset)
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        if not (self.request.user.is_superuser or (user_profile and event.is_manager(user_profile))):
            raise Http404
        return event


# ── Event management sub-views ────────────────────────────────────────────────

class EventManageDataView(EventManagerMixin, UpdateView):
    model = Event
    form_class = EventForm
    template_name = 'events/event_manage_data.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_object(self, queryset=None):
        return self._get_event()

    def get_success_url(self):
        messages.success(self.request, _("Event updated successfully"))
        return reverse('event-manage', kwargs={'slug': self.object.slug})


class EventManageDatesView(EventManagerMixin, View):
    template_name = 'events/event_manage_dates.html'

    def _event(self):
        return self._get_event()

    def get(self, request, slug):
        event = self._event()
        return render(request, self.template_name, {
            'event': event,
            'dates': event.dates.all(),
            'form': EventDateForm(),
        })

    def post(self, request, slug):
        event = self._event()
        form = EventDateForm(request.POST)
        if form.is_valid():
            date = form.cleaned_data['date']
            EventDate.objects.get_or_create(event=event, date=date)
            messages.success(request, _("Date added."))
            return redirect('event-manage-dates', slug=slug)
        return render(request, self.template_name, {
            'event': event,
            'dates': event.dates.all(),
            'form': form,
        })


class EventManageDateDeleteView(EventManagerMixin, View):
    def post(self, request, slug, pk):
        event = self._get_event()
        EventDate.objects.filter(pk=pk, event=event).delete()
        messages.success(request, _("Date removed."))
        return redirect('event-manage-dates', slug=slug)


class EventManageAreasView(EventManagerMixin, View):
    template_name = 'events/event_manage_areas.html'

    def get(self, request, slug):
        event = self._get_event()
        return render(request, self.template_name, {
            'event': event,
            'areas': event.play_areas.all(),
            'form': PlayAreaForm(),
        })

    def post(self, request, slug):
        event = self._get_event()
        form = PlayAreaForm(request.POST)
        if form.is_valid():
            area = form.save(commit=False)
            area.event = event
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
