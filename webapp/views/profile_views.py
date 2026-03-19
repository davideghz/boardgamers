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
        context['has_social_auth'] = self.request.user.social_auth.exists()
        return context

    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     user = self.get_object().user
    #     context['user'] = user
    #     return context


@login_required
def change_email(request):
    if request.method == 'POST':
        new_email = request.POST.get('new_email', '').strip()
        password = request.POST.get('password', '')
        if not new_email:
            messages.error(request, _("Email cannot be empty."))
        elif User.objects.filter(email=new_email).exclude(pk=request.user.pk).exists():
            messages.error(request, _("This email is already in use."))
        elif not request.user.check_password(password):
            messages.error(request, _("Wrong password."))
        else:
            request.user.email = new_email
            request.user.username = new_email
            request.user.save(update_fields=['email', 'username'])
            messages.success(request, _("Email updated successfully."))
    return redirect('user-profile-edit')


def upload_avatar(request):
    default_url = reverse('user-profile-detail', args=[request.user.user_profile.slug])
    next_url = request.POST.get('next') or request.GET.get('next') or default_url
    if request.method == 'POST':
        form = UserProfileAvatarForm(request.POST, request.FILES, instance=request.user.user_profile)
        if form.is_valid():
            form.save()
    return redirect(next_url)
