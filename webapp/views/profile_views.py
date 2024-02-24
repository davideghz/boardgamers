from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render, redirect
from django.views.generic.detail import DetailView
from django.contrib.auth.models import User

from boardGames.settings import env
from webapp.forms import UserProfileAvatarForm
from webapp.models import UserProfile, Table


class UserProfileDetailView(DetailView):
    model = UserProfile
    template_name = 'profiles/user_profile_detail.html'
    context_object_name = 'userprofile'

    def get_object(self):
        return get_object_or_404(UserProfile, user__username=self.kwargs['username'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_profile = self.get_object()
        # Modifica qui: utilizza la relazione corretta attraverso il modello 'Player'
        context['tables'] = user_profile.joined_tables.all()
        context['form'] = form = UserProfileAvatarForm(instance=user_profile)
        context['env'] = env('AWS_S3_SECRET_ACCESS_KEY')
        return context


@login_required
def upload_avatar(request):
    if request.method == 'POST':
        form = UserProfileAvatarForm(request.POST, request.FILES, instance=request.user.user_profile)
        if form.is_valid():
            form.save()
            return redirect('user-profile-detail', username=request.user.username)

    return redirect('user-profile-detail', username=request.user.username)
