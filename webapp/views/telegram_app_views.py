"""The Telegram Mini App shell.

BotFather points a single Mini App short name at this one URL, so the page
cannot know which location it was opened for until the Telegram JS bridge hands
it the signed `initData`. It therefore renders an empty shell and fetches
everything from the bootstrap endpoint.
"""

from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.clickjacking import xframe_options_exempt

# Stand-in the client substitutes with a real slug. The `slug` URL converter
# accepts underscores, so this reverses cleanly.
SLUG_PLACEHOLDER = '__slug__'


@xframe_options_exempt
def miniapp(request):
    """Serve the Mini App shell.

    `xframe_options_exempt` is not optional: Telegram Web embeds Mini Apps in an
    iframe, and the project's default X-Frame-Options DENY would render this as
    a blank page on desktop.
    """
    strings = {
        'loading': _('Loading tables…'),
        'outside_telegram': _('Open this page from Telegram to see the tables.'),
        'no_location': _('This link does not specify a location.'),
        'unknown_location': _('Location not found.'),
        'generic_error': _('Something went wrong. Try reopening the app.'),
        'no_tables': _('No upcoming tables here yet.'),
        'seats_free': _('%(count)s seats left'),
        'one_seat_free': _('1 seat left'),
        'no_seats': _('Full'),
        'unlimited': _('Unlimited seats'),
        'joined': _('You are in'),
        'join': _('Join'),
        'leave': _('Leave'),
        'working': _('One moment…'),
        'connect_title': _('Connect your account to book'),
        'connect_body': _(
            'Link your Telegram account to Board-Gamers and you can join a '
            'table straight from here.'),
        'connect_action': _('Connect account'),
    }
    return render(request, 'telegram/miniapp.html', {
        'strings': strings,
        'bootstrap_url': reverse('telegram-miniapp-bootstrap'),
        'join_url': reverse('telegram-miniapp-join', kwargs={'slug': SLUG_PLACEHOLDER}),
        'leave_url': reverse('telegram-miniapp-leave', kwargs={'slug': SLUG_PLACEHOLDER}),
        'slug_placeholder': SLUG_PLACEHOLDER,
        # Absolute: this one is opened in the external browser, where the
        # Telegram OAuth flow actually works.
        'connect_url': request.build_absolute_uri(reverse('connect-telegram')),
    })
