from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.forms import UserProfileForm, UserNotificationPreferencesForm
from webapp.models import Notification, Membership, Table
from django.db.models import Q


@login_required
def index(request, template_name='accounts/account_index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
        'meta': Meta(
            title=_("My Account - Board-Gamers.com"),
            description=_("Manage your profile: view your activities, notifications and settings."),
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
    user = request.user
    user_profile = user.user_profile
    created_tables = user_profile.created_tables.all()
    joined_tables = user_profile.joined_tables.all()

    today = timezone.now().date()
    base_qs = (
        Table.objects
        .filter(Q(author=user_profile) | Q(players=user_profile))
        .select_related('author', 'location', 'game')
        .distinct()
    )
    future_tables = base_qs.filter(date__gte=today).order_by('date', 'time')
    past_tables = base_qs.filter(date__lt=today).order_by('-date', '-time')

    return render(request, template_name, {
        'user': user,
        'created_tables': created_tables,
        'joined_tables': joined_tables,
        'future_tables': future_tables,
        'past_tables': past_tables,
        'meta': Meta(
            title=_("My Tables - Board-Gamers.com"),
            description=_("Manage your game tables: create new games, edit existing tables and view your statistics."),
        )
    })


@login_required
def notifications(request, template_name='accounts/account_notifications.html'):
    user_profile = request.user.user_profile

    # Recupera tutte le notifiche dell'utente
    user_notifications = (Notification.objects.filter(recipient=user_profile)
                          .select_related('table', 'location').order_by('-created_at'))

    # Aggiorna in blocco quelle non ancora lette
    user_notifications.filter(is_read=False).update(is_read=True)

    return render(request, template_name, {
        'notifications': user_notifications,
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
    ).select_related('member__location')

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
def edit_notification_preferences(request):
    profile = request.user.user_profile
    if request.method == 'POST':
        form = UserNotificationPreferencesForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, _("Notification preferences updated"))
            render(request, 'accounts/account_notifications_preferences.html', {'form': form})
    else:
        form = UserNotificationPreferencesForm(instance=profile)

    return render(request, 'accounts/account_notifications_preferences.html', {
        'form': form,
        'meta': Meta(
            title=_("Notification Preferences - Board-Gamers.com"),
            description=_("Configure your notification preferences: choose which updates to receive and how."),
        )
    })
