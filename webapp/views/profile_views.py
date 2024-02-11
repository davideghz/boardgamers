from django.shortcuts import get_object_or_404
from django.views.generic.detail import DetailView
from django.contrib.auth.models import User

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
        return context
