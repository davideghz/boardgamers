from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.api.search_views import location_result
from webapp.forms import UserProfileForm, UserNotificationPreferencesForm, GuestProfileForm, \
    MemberPersonalDataForm, location_filter_picker
from webapp.models import (
    Event, GuestProfile, Member, Membership, Notification, Table,
)
from webapp.services.appointments import paginate_appointments
from webapp.services.my_activities import my_activities
from webapp.services.viewer import get_viewer


@login_required
def index(request, template_name='accounts/account_index.html'):
    user = request.user
    viewer = get_viewer(request)
    upcoming = viewer.upcoming_participations

    return render(request, template_name, {
        'user': user,
        # Counters on the entries, and the entries only some users need
        'upcoming_activities_count': len(upcoming.table_ids) + len(upcoming.event_ids),
        'active_memberships_count': len(viewer.member_location_ids),
        'managed_locations_count': len(viewer.managed_location_ids),
        'organizes_tables': Table.objects.filter(author=viewer.profile).exists(),
        'manages_events': viewer.manages_events,
        'meta': Meta(
            title=_("My Account"),
            description=_("Manage your profile: view your activities, notifications and settings."),
        )
    })


@login_required
def events(request, template_name='accounts/account_events.html'):
    user_profile = request.user.user_profile
    staff_events = Event.objects.managed_by(user_profile).prefetch_related('dates')
    owned_events = staff_events.filter(creator=user_profile)
    managed_events = staff_events.exclude(creator=user_profile)
    participating_events = Event.objects.filter(
        participants__user_profile=user_profile,
        status=Event.PUBLISHED,
    ).prefetch_related('dates').distinct()
    return render(request, template_name, {
        'owned_events': owned_events,
        'managed_events': managed_events,
        'participating_events': participating_events,
        'meta': Meta(
            title=_("My Events"),
            description=_("Manage the events you created or coordinate."),
        )
    })


@login_required
def edit_profile(request, template_name='accounts/account_edit_profile.html'):
    user = request.user
    form = UserProfileForm

    return render(request, template_name, {
        'user': user,
        'form': form,
        'meta': Meta(
            title=_("Edit Profile"),
            description=_("Edit your profile: update photo, bio and game preferences."),
        )
    })


@login_required
def locations(request, template_name='accounts/account_locations.html'):
    user = request.user
    user_profile = user.user_profile

    # Separate owned locations from managed locations
    owned_locations = user_profile.locations.all()
    managed_locations = user_profile.managed_locations.all().exclude(
        id__in=owned_locations.values_list('id', flat=True)
    )

    return render(request, template_name, {
        'user': user,
        'owned_locations': owned_locations,
        'managed_locations': managed_locations,
        'meta': Meta(
            title=_("My Locations"),
            description=_("Manage your locations: create new locations, edit data and manage your game tables."),
        )
    })


@login_required
def tables(request):
    """My tables became a view of My activities (plan E5): the tables the user organizes."""
    query = {'type': 'tables', 'role': 'organizer'}
    if request.GET.get('tab') == 'past':
        query['tab'] = 'past'
    for key in ('q', 'location'):
        if request.GET.get(key):
            query[key] = request.GET[key]
    return redirect(reverse('account-activities', query=query))


@login_required
def activities(request):
    user = request.user
    activity_type = request.GET.get('type', 'all')
    if activity_type not in ('events', 'tables'):
        activity_type = 'all'
    past = request.GET.get('tab') == 'past'
    organizer = request.GET.get('role') == 'organizer'
    query = request.GET.get('q', '').replace('\x00', '').strip()[:200]
    venue = request.GET.get('location', '').replace('\x00', '').strip()[:144]
    sources, locations = my_activities(
        user, past=past, organizer=organizer, activity_type=activity_type, venue=venue, query=query)
    page, items = paginate_appointments(sources, request.GET.get('page'), newest_first=past)

    # The active filters as chips (the list pattern of Search, plan E2)
    params = request.GET.copy()
    params.pop('page', None)

    def without(*keys):
        remaining = params.copy()
        for key in keys:
            remaining.pop(key, None)
        return f'?{remaining.urlencode()}' if remaining else '?'

    active_filters = []
    if query:
        active_filters.append((f'«{query}»', without('q')))
    if venue:
        name = next((location.name for location in locations if location.slug == venue), venue)
        active_filters.append((_('Venue: %(name)s') % {'name': name}, without('location')))
    if organizer:
        active_filters.append((_('Organized by me'), without('role')))
    return render(request, 'accounts/account_activities.html', {
        'activity_type': activity_type, 'tab': 'past' if past else 'upcoming', 'past': past, 'organizer': organizer,
        'items': items, 'page_obj': page, 'paginator': page.paginator, 'is_paginated': page.has_other_pages(),
        'q': query, 'selected_location': venue,
        'location_filter_items': [location_result(location) for location in locations],
        'location_picker': location_filter_picker(venue, local_items_id='location-filter-items'),
        'active_filters': active_filters,
        'reset_url': without('q', 'location', 'role'),
        'has_filters': bool(active_filters),
        'meta': Meta(title=_('My activities')),
    })


@login_required
def notifications(request, template_name='accounts/account_notifications.html'):
    user_profile = request.user.user_profile

    # Recupera tutte le notifiche dell'utente
    user_notifications = (Notification.objects.filter(Table.public_condition('table__'), recipient=user_profile)
                          .select_related('table', 'location').order_by('-created_at'))

    # Aggiorna in blocco quelle non ancora lette
    user_notifications.filter(is_read=False).update(is_read=True)

    paginator = Paginator(user_notifications, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, template_name, {
        'notifications': page_obj.object_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'meta': Meta(
            title=_("Notifications"),
            description=_("View your notifications: new tables, comments, invitations and community updates."),
        )
    })


@login_required
def memberships(request, template_name='accounts/account_memberships.html'):
    user_profile = request.user.user_profile
    base_qs = Membership.objects.filter(
        member__user_profile=user_profile
    ).select_related('member__location').prefetch_related('member__location__membership_documents')

    active_memberships = base_qs.filter(
        status__in=[Membership.ACTIVE, Membership.PENDING]
    ).order_by('-start_date')
    past_memberships = base_qs.filter(
        status__in=[Membership.EXPIRED, Membership.REJECTED]
    ).order_by('-end_date')

    return render(request, template_name, {
        'active_memberships': active_memberships,
        'past_memberships': past_memberships,
        'meta': Meta(
            title=_("My Memberships"),
            description=_("View your active and past memberships."),
        )
    })


@login_required
def member_data(request, member_uuid):
    """
    Let a member review and correct the personal data a location holds for
    them. Members are per-location, so this edits one location's record.
    """
    user_profile = request.user.user_profile
    member = get_object_or_404(Member, uuid=member_uuid, user_profile=user_profile)
    if not member.memberships.filter(status__in=[Membership.PENDING, Membership.ACTIVE]).exists():
        raise PermissionDenied(_("This membership is no longer editable."))

    if request.method == 'POST':
        form = MemberPersonalDataForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, _("Your details have been updated."))
            return redirect('account-memberships')
    else:
        form = MemberPersonalDataForm(instance=member)

    return render(request, 'accounts/account_member_data.html', {
        'member': member,
        'location': member.location,
        'form': form,
        'meta': Meta(
            title=_("My details – %(name)s") % {'name': member.location.name},
        ),
    })


@login_required
def edit_notification_preferences(request):
    profile = request.user.user_profile
    has_email = bool(request.user.email)

    if request.method == 'POST' and has_email:
        form = UserNotificationPreferencesForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, _("Notification preferences updated"))
            render(request, 'accounts/account_notifications_preferences.html', {'form': form})
    else:
        form = UserNotificationPreferencesForm(instance=profile)

    return render(request, 'accounts/account_notifications_preferences.html', {
        'form': form,
        'has_email': has_email,
        'meta': Meta(
            title=_("Notification Preferences"),
            description=_("Configure your notification preferences: choose which updates to receive and how."),
        )
    })


@login_required
def guests(request, template_name='accounts/account_guests.html'):
    profile = request.user.user_profile
    guest_list = profile.guest_profiles.all()
    form = GuestProfileForm()
    return render(request, template_name, {
        'guests': guest_list,
        'form': form,
        'meta': Meta(title=_("My guests")),
    })


@login_required
def create_guest(request):
    if request.method == 'POST':
        form = GuestProfileForm(request.POST)
        if form.is_valid():
            guest = form.save(commit=False)
            guest.owner = request.user.user_profile
            guest.save()
            messages.success(request, _("Guest created."))
    return redirect('account-guests')


@login_required
def update_guest(request, guest_id):
    profile = request.user.user_profile
    guest = get_object_or_404(GuestProfile, id=guest_id, owner=profile)
    if request.method == 'POST':
        form = GuestProfileForm(request.POST, instance=guest)
        if form.is_valid():
            form.save()
            messages.success(request, _("Guest updated."))
        else:
            messages.error(request, _("Invalid name."), extra_tags='danger')
    return redirect('account-guests')


@login_required
def delete_guest(request, guest_id):
    profile = request.user.user_profile
    guest = get_object_or_404(GuestProfile, id=guest_id, owner=profile)
    if request.method == 'POST':
        active_count = guest.table_players.select_related('table').filter(
            table__status__in=[Table.OPEN, Table.ONGOING]
        ).count()
        if active_count > 0:
            messages.error(request, _("This guest is currently at an active table and cannot be deleted."), extra_tags='danger')
        else:
            guest.delete()
            messages.success(request, _("Guest deleted."))
    return redirect('account-guests')
