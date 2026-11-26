from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST, require_safe
from meta.views import Meta

from webapp.forms import AddEventManagerForm, EventDateForm, MasterEventForm, SponsorForm
from webapp.models import Event, MasterEvent, MasterEventDate, MasterEventDateParticipant
from webapp.services.event_attendance import manifestation_attendance
from webapp.services.master_catalog import MasterCatalog
from webapp.services.master_events import linkable_events, public_children, public_program, set_master


def managed_master(request, slug, *, lock=False):
    masters = MasterEvent.objects.select_for_update() if lock else MasterEvent.objects.all()
    master = get_object_or_404(masters, slug=slug)
    if not master.can_manage(request.user):
        raise PermissionDenied
    return master


@require_safe
def visible_master(request, slug):
    master = get_object_or_404(MasterEvent.objects.select_related('venue_location'), slug=slug)
    can_manage = master.can_manage(request.user)
    can_approve = MasterEvent.can_approve(request.user)
    if not (master.is_published or can_manage or can_approve):
        raise Http404
    return master, can_manage, can_approve


@require_safe
def detail(request, slug):
    master, can_manage, can_approve = visible_master(request, slug)
    days = list(master.dates.all())
    attendance = manifestation_attendance(master, days)
    today = timezone.localdate()
    registration_open = master.is_published and any(day.date >= today for day in days)
    can_register = registration_open and request.user.is_authenticated
    selected = set()
    if can_register:
        selected = set(request.user.user_profile.master_event_registrations.filter(
            master_event_date__master_event=master, master_event_date__date__gte=today,
        ).values_list('master_event_date_id', flat=True))
    for day in days:
        day.expected = len(attendance[day.date])
        day.selectable = can_register and day.date >= today
        day.selected = day.pk in selected
    return render(request, 'masters/detail.html', {
        'master': master, 'can_manage': can_manage, 'can_approve': can_approve and master.status == Event.DRAFT,
        'events': public_children(master), 'tables': public_program(master),
        'sponsors': master.sponsors.all(),
        'has_catalog': MasterCatalog(master).games().exists(),
        'days': days, 'registration_open': registration_open, 'can_register': can_register,
        'unique_people': len(set().union(*attendance.values())),
        'person_days': sum(map(len, attendance.values())),
        'meta': Meta(title=master.name),
    })


@require_safe
def catalog(request, slug):
    master, *_permissions = visible_master(request, slug)
    catalog = MasterCatalog(master)
    games = catalog.games()
    q = request.GET.get('q', '').strip()
    if q:
        games = games.filter(name__icontains=q)
    paginator = Paginator(games, 24)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'masters/catalog.html', {
        'master': master, 'entries': catalog.entries(page_obj.object_list), 'q': q,
        'page_obj': page_obj, 'paginator': paginator, 'is_paginated': page_obj.has_other_pages(),
        'meta': Meta(title=_('Game catalog – %(name)s') % {'name': master.name}),
    })


@login_required
@require_http_methods(['GET', 'HEAD', 'POST'])
@transaction.atomic
def edit(request, slug=None):
    master = managed_master(request, slug, lock=request.method == 'POST') if slug else MasterEvent()
    form = MasterEventForm(request.POST if request.method == 'POST' else None, instance=master)
    if request.method == 'POST' and form.is_valid():
        master = form.save()
        if not slug:
            master.managers.add(request.user.user_profile)
        return redirect('master-event-manage', slug=master.slug)
    calendar_initial = {}
    if slug and (selected := request.GET.get('day')):
        try:
            day = master.dates.filter(date=date.fromisoformat(selected)).first()
        except ValueError:
            day = None
        if day:
            calendar_initial = {'date': day.date, 'opening_time': day.opening_time, 'closing_time': day.closing_time}
    date_form = EventDateForm(initial=calendar_initial)
    if calendar_initial:
        date_form.fields['date'].widget.attrs['readonly'] = True
    return render(request, 'masters/edit.html', {
        'master': master, 'form': form, 'date_form': date_form,
        'manager_form': AddEventManagerForm(),
        'sponsors': master.sponsors.all() if master.pk else (),
        'linked_events': master.events.select_related('organizer_location').order_by('name', 'pk') if master.pk else (),
        'linkable_events': linkable_events(request.user, master).select_related('organizer_location').order_by(
            'name', 'pk') if master.pk else (),
        'meta': Meta(title=master.name or _('Create festival')),
    })


@login_required
@require_POST
@transaction.atomic
def register(request, slug):
    master = get_object_or_404(MasterEvent.objects.select_for_update(), slug=slug, status=Event.PUBLISHED)
    destination = master.get_absolute_url() + '#master-event-attendance'
    eligible = set(master.dates.filter(date__gte=timezone.localdate()).values_list('pk', flat=True))
    if not eligible:
        messages.error(request, _('Registration is closed.'))
        return redirect(destination)
    try:
        selected = {int(value) for value in request.POST.getlist('days')}
    except ValueError:
        selected = None
    if selected is None or selected - eligible:
        messages.error(request, _('Choose a date in the festival calendar.'))
        return redirect(destination)

    profile = request.user.user_profile
    profile.master_event_registrations.filter(master_event_date_id__in=eligible - selected).delete()
    MasterEventDateParticipant.objects.bulk_create([
        MasterEventDateParticipant(user_profile=profile, master_event_date_id=pk) for pk in selected
    ], ignore_conflicts=True)
    messages.success(request, _('Festival registration updated.'))
    return redirect(destination)


@login_required
@require_POST
@transaction.atomic
def calendar(request, slug):
    master = managed_master(request, slug, lock=True)
    if request.POST.get('remove'):
        try:
            day_id = int(request.POST['remove'])
        except ValueError:
            raise Http404
        day = get_object_or_404(master.dates, pk=day_id)
        try:
            with transaction.atomic():
                day.delete()
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, _('Date removed.'))
    else:
        form = EventDateForm(request.POST)
        if form.is_valid():
            MasterEventDate.objects.update_or_create(
                master_event=master, date=form.cleaned_data['date'], defaults={
                    'opening_time': form.cleaned_data['opening_time'], 'closing_time': form.cleaned_data['closing_time']})
            messages.success(request, _('Date saved.'))
        else:
            messages.error(request, _('Invalid date or times.'))
    return redirect(reverse('master-event-manage', args=[slug]) + '#master-event-dates')


@login_required
@require_POST
@transaction.atomic
def managers(request, slug):
    master = managed_master(request, slug, lock=True)
    if request.POST.get('remove'):
        try:
            profile_id = int(request.POST['remove'])
        except ValueError:
            raise Http404
        profile = get_object_or_404(master.managers, pk=profile_id)
        if master.managers.count() > 1:
            master.managers.remove(profile)
        else:
            messages.error(request, _('Keep at least one manager.'))
    else:
        form = AddEventManagerForm(request.POST)
        if form.is_valid():
            master.managers.add(form.cleaned_data['manager'])
        else:
            messages.error(request, _('Select a manager'))
    return redirect('master-event-manage', slug=slug)


@login_required
@require_POST
def link(request, slug):
    master = managed_master(request, slug)
    unlink = 'remove' in request.POST
    try:
        event_id = int(request.POST['remove' if unlink else 'event'])
    except (KeyError, ValueError):
        raise Http404
    events = master.events.all() if unlink else linkable_events(request.user, master)
    event = get_object_or_404(events, pk=event_id)
    try:
        set_master(event, master, request.user, unlink=unlink)
    except (Event.DoesNotExist, MasterEvent.DoesNotExist):
        raise Http404
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(request, _('Event unlinked.') if unlink else _('Event linked.'))
    return redirect(reverse('master-event-manage', args=[slug]) + '#master-event-events')


@login_required
@require_http_methods(['GET', 'HEAD', 'POST'])
@transaction.atomic
def sponsors(request, slug, pk=None):
    is_post = request.method == 'POST'
    master = managed_master(request, slug, lock=is_post)
    destination = reverse('master-event-manage', args=[slug]) + '#master-event-sponsors'
    linked_sponsors = master.sponsors.select_for_update(of=('self',)) if is_post else master.sponsors.all()
    sponsor = get_object_or_404(linked_sponsors, pk=pk) if pk is not None else None
    if is_post and sponsor and 'remove' in request.POST:
        master.sponsors.remove(sponsor)
        messages.success(request, _('Sponsor removed.'))
        return redirect(destination)

    form = SponsorForm(request.POST if is_post else None, request.FILES if is_post else None, instance=sponsor)
    if is_post and form.is_valid():
        if not sponsor or form.has_changed():
            edited = form.save(commit=False)
            if sponsor and sponsor.master_events.exclude(pk=master.pk).exists():
                # A manager's changes apply only to this manifestation.
                original_id = sponsor.pk
                edited.pk = None
                edited.save(force_insert=True)
                master.sponsors.remove(original_id)
            else:
                edited.save()
            master.sponsors.add(edited)
            messages.success(request, _('Sponsor updated.') if sponsor else _('Sponsor added.'))
        return redirect(destination)

    title = _('Edit sponsor') if sponsor else _('Add sponsor')
    return render(request, 'masters/sponsor.html', {
        'master': master, 'form': form, 'sponsor': sponsor, 'title': title, 'meta': Meta(title=title),
    })


@login_required
@require_POST
def approve(request, slug):
    if not MasterEvent.can_approve(request.user):
        raise PermissionDenied
    master = get_object_or_404(MasterEvent, slug=slug)
    try:
        if master.approve(request.user):
            messages.success(request, _('%(name)s was published.') % {'name': master.name})
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('master-event-detail', slug=slug)
