from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.forms import UserProfileForm, UserNotificationPreferencesForm, GuestProfileForm, \
    MemberPersonalDataForm
from webapp.models import (
    Event, EventDate, EventParticipant, EventParticipantDate, GuestProfile, Location, Member, Membership,
    Notification, Table,
)
from webapp.services.appointments import paginate_appointments, with_matching_day


@login_required
def index(request, template_name='accounts/account_index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
        'manages_events': Event.objects.managed_by(user.user_profile).exists(),
        'meta': Meta(
            title=_("My Account - Board-Gamers.com"),
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
            title=_("My Events - Board-Gamers.com"),
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
            title=_("Edit Profile - Board-Gamers.com"),
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
            title=_("My Locations - Board-Gamers.com"),
            description=_("Manage your locations: create new locations, edit data and manage your game tables."),
        )
    })


@login_required
def tables(request, template_name='accounts/account_tables.html'):
    user_profile = request.user.user_profile
    base_qs = (
        Table.objects.visible_to(request.user)
        .filter(Q(author=user_profile) | Q(players=user_profile))
        .distinct()
    )
    # Locations of the user's tables: the only ones worth offering in the filter.
    my_locations = list(Location.objects.filter(tables__in=base_qs).distinct().order_by('name'))

    tab = 'past' if request.GET.get('tab') == 'past' else 'upcoming'
    q = request.GET.get('q', '').strip()
    location_slug = request.GET.get('location', '').strip()

    qs = base_qs.select_related('author', 'location', 'game')
    if location_slug:
        qs = qs.filter(location__slug=location_slug)
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(game__name__icontains=q))
    today = timezone.localdate()
    if tab == 'past':
        qs = qs.filter(date__lt=today).order_by('-date', '-time')
    else:
        qs = qs.filter(date__gte=today).order_by('date', 'time')

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, template_name, {
        'tables': page_obj.object_list,
        'paginator': paginator,
        'page_obj': page_obj,
        'is_paginated': page_obj.has_other_pages(),
        'tab': tab,
        'q': q,
        'selected_location': location_slug,
        'selected_location_obj': next((loc for loc in my_locations if loc.slug == location_slug), None),
        'location_picker_sections': [(_("Locations of your tables"), my_locations)] if my_locations else [],
        'has_filters': bool(q or location_slug),
        'meta': Meta(
            title=_("My Tables - Board-Gamers.com"),
            description=_("Manage your game tables: create new games, edit existing tables and view your statistics."),
        )
    })


@login_required
def activities(request):
    user = request.user
    profile = user.user_profile
    activity_type = request.GET.get('type', 'all')
    if activity_type not in ('events', 'tables'):
        activity_type = 'all'
    past = request.GET.get('tab') == 'past'
    today = timezone.localdate()
    period = {'date__lt' if past else 'date__gte': today}
    query = request.GET.get('q', '').strip()[:200]
    venue = request.GET.get('location', '').strip()[:144]

    my_tables = Table.objects.visible_to(user).filter(players=profile)
    registrations = EventParticipant.objects.filter(event_id=OuterRef('pk'), user_profile=profile)
    my_events = Event.objects.filter(Exists(registrations) | Exists(my_tables.filter(event_id=OuterRef('pk'))))
    if not user.is_superuser:
        my_events = my_events.filter(Q(status=Event.PUBLISHED) | Q(pk__in=Event.objects.managed_by(profile)))

    locations = Location.objects.filter(
        Q(pk__in=my_tables.order_by().values('location_id'))
        | Q(pk__in=my_tables.order_by().values('event__venue_location_id'))
        | Q(pk__in=my_events.order_by().values('venue_location_id')),
    ).order_by('name', 'pk')

    tables = my_tables.filter(**period)
    # Registrations without a day nor a table: a day inferred from a cancelled booking is not a choice.
    undated = EventParticipant.objects.filter(user_profile=profile).exclude(
        selected_dates__inferred_from_booking=False,
    ).exclude(Exists(my_tables.filter(event_id=OuterRef('event_id'))))
    # They follow the event's own days: its next one, or its last one once the event is over.
    event_days = Exists(undated.filter(event_id=OuterRef('event_id')))
    if past:
        event_days &= ~Exists(EventDate.objects.filter(event_id=OuterRef('event_id'), date__gte=today))
    dates = EventDate.objects.filter(event_id=OuterRef('pk'), **period).filter(
        Exists(EventParticipantDate.objects.filter(
            event_date_id=OuterRef('pk'), participant__user_profile=profile, inferred_from_booking=False,
        )) | Exists(my_tables.filter(event_id=OuterRef('event_id'), date=OuterRef('date'))) | event_days,
    )
    # Events without any day stay in the upcoming tab, after dated activities.
    events = with_matching_day(
        my_events, dates, newest_first=past,
        undated=None if past else undated.filter(event_id=OuterRef('pk'), event__dates__isnull=True),
    )
    if venue:
        tables = tables.filter(Q(location__slug=venue) | Q(event__venue_location__slug=venue))
        events = events.filter(venue_location__slug=venue)
    if query:
        tables = tables.filter(Q(title__icontains=query) | Q(description__icontains=query)
                               | Q(game__name__icontains=query) | Q(event__name__icontains=query))
        events = events.filter(Q(name__icontains=query) | Q(description__icontains=query))

    sources = {}
    if activity_type != 'events':
        sources['table'] = tables.select_related(
            'author', 'location', 'game', 'event__venue_location', 'event__organizer_location', 'event__master_event',
        )
    if activity_type != 'tables':
        sources['event'] = events.select_related('organizer_location', 'venue_location', 'master_event')
    page, items = paginate_appointments(sources, request.GET.get('page'), newest_first=past)
    return render(request, 'accounts/account_activities.html', {
        'activity_type': activity_type, 'tab': 'past' if past else 'upcoming',
        'items': items, 'page_obj': page, 'paginator': page.paginator, 'is_paginated': page.has_other_pages(),
        'q': query, 'selected_location': venue, 'locations': locations,
        'has_filters': bool(query or venue),
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
            title=_("Notifications - Board-Gamers.com"),
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
            title=_("My Memberships - Board-Gamers.com"),
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
            title=_("My details - %(name)s") % {'name': member.location.name},
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
            title=_("Notification Preferences - Board-Gamers.com"),
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
