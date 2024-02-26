from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse_lazy
from django.views.generic import UpdateView
from django.views.generic.detail import DetailView
from django.contrib.auth.models import User

from boardGames.settings import env
from webapp.forms import UserProfileAvatarForm, UserProfileForm
from webapp.models import UserProfile, Table


class UserProfileDetailView(DetailView):
    model = UserProfile
    template_name = 'profiles/user_profile_detail.html'
    context_object_name = 'userprofile'

    def get_object(self):
        return get_object_or_404(UserProfile, slug=self.kwargs['slug'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_profile = self.get_object()
        # Modifica qui: utilizza la relazione corretta attraverso il modello 'Player'
        context['tables'] = user_profile.joined_tables.all()
        context['form'] = form = UserProfileAvatarForm(instance=user_profile)
        context['env'] = env('AWS_S3_SECRET_ACCESS_KEY')
        return context


class UserProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = UserProfile
    form_class = UserProfileForm
    template_name = 'accounts/account_edit_profile.html'

    def get_object(self, queryset=None):
        return UserProfile.objects.get(user=self.request.user)

    def get_success_url(self):
        return reverse_lazy('user-profile-detail', args=[self.request.user.slug])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.get_object().user
        context['user'] = user
        return context


def upload_avatar(request):
    if request.method == 'POST':
        form = UserProfileAvatarForm(request.POST, request.FILES, instance=request.user.user_profile)
        if form.is_valid():
            form.save()
            return redirect('user-profile-detail', username=request.user.user_profile.slug)

    return redirect('user-profile-detail', username=request.user.user_profile.slug)
