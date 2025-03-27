from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count, Q, Subquery, OuterRef
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import UpdateView
from django.views.generic.detail import DetailView

from boardGames.settings import env
from webapp.forms import UserProfileAvatarForm, UserProfileForm
from webapp.models import UserProfile, Game, Player, Table

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
            play_count=Subquery(played_count),
            win_count=Subquery(win_count)
        ).filter(play_count__gt=0).order_by('-win_count', '-play_count')

        context.update({
            'tables': user_profile.joined_tables.all(),
            'form': UserProfileAvatarForm(instance=user_profile),
            'games_played': games_played,
        })
        return context

class UserProfileUpdateView(LoginRequiredMixin, SuccessMessageMixin, UpdateView):
    model = UserProfile
    form_class = UserProfileForm
    template_name = 'accounts/account_edit_profile.html'
    success_message = _("Profile updated successfully")

    def get_object(self, queryset=None):
        return UserProfile.objects.get(user=self.request.user)

    def get_success_url(self):
        return reverse('user-profile-detail', args=[self.request.user.user_profile.slug])

    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     user = self.get_object().user
    #     context['user'] = user
    #     return context


def upload_avatar(request):
    if request.method == 'POST':
        form = UserProfileAvatarForm(request.POST, request.FILES, instance=request.user.user_profile)
        if form.is_valid():
            form.save()
            return redirect('user-profile-detail', slug=request.user.user_profile.slug)

    return redirect('user-profile-detail', slug=request.user.user_profile.slug)
