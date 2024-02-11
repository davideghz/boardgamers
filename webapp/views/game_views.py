from django.shortcuts import get_object_or_404
from django.views.generic.detail import DetailView
from django.contrib.auth.models import User

from webapp.models import Game


class GameDetailView(DetailView):
    model = Game
    template_name = 'games/game_detail.html'
    context_object_name = 'game'
