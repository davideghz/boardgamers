from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.views.generic.detail import DetailView
from django.contrib.auth.models import User

from webapp.models import Game


class GameDetailView(DetailView):
    model = Game
    template_name = 'games/game_detail.html'
    context_object_name = 'game'

    def get_queryset(self):
        return Game.objects.annotate(
            table_count=Count('created_tables'),
            player_count=Count('created_tables__players')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game = self.get_object()
        context['table_count'] = game.table_count
        context['player_count'] = game.player_count
        return context
