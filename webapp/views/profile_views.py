from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q, Subquery, OuterRef, Exists, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views.generic import UpdateView
from django.views.generic.detail import DetailView

from django.conf import settings as django_settings

from boardGames.settings import env
from webapp.forms import UserProfileAvatarForm, UserProfileForm
from webapp.models import UserProfile, Game, Player, Table

from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


class UserProfileDetailView(DetailView):
    model = UserProfile
    template_name = 'profiles/user_profile_detail.html'
    context_object_name = 'userprofile'

    def get_object(self):
        return get_object_or_404(UserProfile, slug=self.kwargs['slug'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_profile = self.get_object()

        # Sottoquery per contare le partite giocate per ogni gioco
        played_count = Table.objects.filter(
            game=OuterRef('pk'),
            players=user_profile
        ).values('game').annotate(
            count=Count('id', distinct=True)
        ).values('count')

        # Sottoquery per contare le vittorie per ogni gioco
        win_count = Table.objects.filter(
            game=OuterRef('pk'),
            players=user_profile,
            player__position=1
        ).values('game').annotate(
            count=Count('id', distinct=True)
        ).values('count')

        # Query principale per i giochi giocati
        games_played = Game.objects.annotate(
            play_count=Coalesce(Subquery(played_count), Value(0)),
            win_count=Coalesce(Subquery(win_count), Value(0))
        ).filter(play_count__gt=0).order_by('-win_count', '-play_count')

        context.update({
            'tables': Table.objects.filter(players=user_profile).annotate(
                is_win=Exists(Player.objects.filter(table=OuterRef('pk'), user_profile=user_profile, position=1))
            ).order_by('-is_win', '-date'),
            'form': UserProfileAvatarForm(instance=user_profile),
            'games_played': games_played,
            'meta': self.get_object().as_meta(self.request)
        })
        return context


class UserProfileUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = UserProfile
    form_class = UserProfileForm
    template_name = 'accounts/account_edit_profile.html'
    success_message = _("Profile updated successfully")

    def get_object(self, queryset=None):
        return UserProfile.objects.get(user=self.request.user)

    def get_form_class(self):
        return UserProfileForm

    def get_success_url(self):
        return reverse('user-profile-detail', args=[self.request.user.user_profile.slug])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        social_auths = list(user.social_auth.all())
        connected = {sa.provider for sa in social_auths}
        has_password = user.has_usable_password()

        # For the email section: use the "primary" provider
        first_auth = social_auths[0] if social_auths else None
        context['social_provider'] = first_auth.provider if first_auth else None
        context['has_usable_password'] = has_password
        context['connected_providers'] = connected

        # password counts as a fallback login method only if the user also has an email
        # (Telegram users may have a password but no email, so they can't use email/password login)
        has_password_login = has_password and bool(user.email)

        # Can disconnect only if another login method remains
        context['can_disconnect_google'] = (
            'google-oauth2' in connected and (has_password_login or 'telegram' in connected)
        )
        context['can_disconnect_telegram'] = (
            'telegram' in connected and (has_password_login or 'google-oauth2' in connected)
        )

        # Telegram connect URL (return_to = connect page, for the connect button)
        bot_token = django_settings.SOCIAL_AUTH_TELEGRAM_BOT_TOKEN
        bot_username = getattr(django_settings, 'TELEGRAM_BOT_USERNAME', '')
        if bot_token and ':' in bot_token and bot_username:
            from urllib.parse import quote
            bot_id = bot_token.split(':')[0]
            origin = f"{self.request.scheme}://{self.request.get_host()}"
            return_to = self.request.build_absolute_uri(reverse('connect-telegram'))
            context['telegram_connect_url'] = (
                f"https://oauth.telegram.org/auth"
                f"?bot_id={bot_id}"
                f"&origin={quote(origin, safe='')}"
                f"&request_access=write"
                f"&return_to={quote(return_to, safe='')}"
            )

        return context


@login_required
def change_email(request):
    if request.method == 'POST':
        new_email = request.POST.get('new_email', '').strip()
        password = request.POST.get('password', '')
        if not new_email:
            messages.error(request, _("Email cannot be empty."))
        elif User.objects.filter(email=new_email).exclude(pk=request.user.pk).exists():
            messages.error(request, _("This email is already in use."))
        elif request.user.has_usable_password() and not request.user.check_password(password):
            messages.error(request, _("Wrong password."))
        else:
            # Only sync username to email for users whose username IS their email
            # (Google and email-registered users). Telegram users keep their own username.
            if request.user.username == request.user.email:
                request.user.username = new_email
            request.user.email = new_email
            request.user.save(update_fields=['email', 'username'])
            messages.success(request, _("Email updated successfully."))
    return redirect('user-profile-edit')


@login_required
def connect_telegram_page(request):
    """
    Intermediate page for the Telegram account-linking flow.
    - On first visit: shows a connect button; the return_to URL points back here.
    - After Telegram auth: Telegram redirects here with #tgAuthResult=...; the page's
      JS handler (visible only to authenticated users) intercepts it and redirects
      to social:complete, which links the social account to the current user.
    """
    bot_token = django_settings.SOCIAL_AUTH_TELEGRAM_BOT_TOKEN
    bot_username = getattr(django_settings, 'TELEGRAM_BOT_USERNAME', '')
    connect_url = None
    if bot_token and ':' in bot_token and bot_username:
        from urllib.parse import quote
        bot_id = bot_token.split(':')[0]
        origin = f"{request.scheme}://{request.get_host()}"
        return_to = request.build_absolute_uri()  # this page itself
        connect_url = (
            f"https://oauth.telegram.org/auth"
            f"?bot_id={bot_id}"
            f"&origin={quote(origin, safe='')}"
            f"&request_access=write"
            f"&return_to={quote(return_to, safe='')}"
        )
    return render(request, 'accounts/account_connect_telegram.html', {
        'telegram_connect_url': connect_url,
    })


@login_required
def disconnect_social(request, provider):
    """Disconnect a social auth provider, with safety check."""
    if request.method != 'POST':
        return redirect('user-profile-edit')

    user = request.user
    connected = set(user.social_auth.values_list('provider', flat=True))

    if provider not in connected:
        messages.error(request, _("Account not connected."))
        return redirect('user-profile-edit')

    has_password_login = user.has_usable_password() and bool(user.email)
    other_methods_exist = bool((connected - {provider}) or has_password_login)
    if not other_methods_exist:
        messages.error(request, _("Cannot disconnect: this is your only login method."))
        return redirect('user-profile-edit')

    user.social_auth.filter(provider=provider).delete()
    messages.success(request, _("Account disconnected successfully."))
    return redirect('user-profile-edit')


def upload_avatar(request):
    default_url = reverse('user-profile-detail', args=[request.user.user_profile.slug])
    next_url = request.POST.get('next') or request.GET.get('next') or default_url
    if request.method == 'POST':
        form = UserProfileAvatarForm(request.POST, request.FILES, instance=request.user.user_profile)
        if form.is_valid():
            form.save()
    return redirect(next_url)
