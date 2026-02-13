from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.forms import UserProfileForm, UserNotificationPreferencesForm
from webapp.models import Notification


@login_required
def index(request, template_name='accounts/account_index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
        'meta': Meta(
            title='Il Mio Account - Boardgamers',
            description='Gestisci il tuo profilo boardgamers: visualizza le tue attività, notifiche e impostazioni.',
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
            title='Modifica Profilo - Boardgamers',
            description='Modifica il tuo profilo boardgamers: aggiorna foto, bio e preferenze di gioco.',
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
            title='Le Mie Location - Boardgamers',
            description='Gestisci le tue location: crea nuove location, modifica dati e gestisci i tuoi tavoli di gioco.',
        )
    })


@login_required
def tables(request, template_name='accounts/account_tables.html'):
    user = request.user
    created_tables = user.user_profile.created_tables.all()
    joined_tables = user.user_profile.joined_tables.all()

    return render(request, template_name, {
        'user': user,
        'created_tables': created_tables,
        'joined_tables': joined_tables,
        'meta': Meta(
            title='I Miei Tavoli - Boardgamers',
            description='Gestisci i tuoi tavoli di gioco: crea nuove partite, modifica tavoli esistenti e visualizza le tue statistiche.',
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
            title='Notifiche - Boardgamers',
            description='Visualizza le tue notifiche: nuovi tavoli, commenti, inviti e aggiornamenti della community.',
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
            title='Preferenze Notifiche - Boardgamers',
            description='Configura le tue preferenze di notifica: scegli quali aggiornamenti ricevere e come.',
        )
    })
