from django.db.models import Count
from django.views.generic import ListView
from django.views.generic.detail import DetailView
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.middleware import get_v2_template
from webapp.models import Game


class GameListView(ListView):
    model = Game
    template_name = 'games/game_list.html'
    context_object_name = 'games'

    def get_template_names(self):
        return [get_v2_template(self.request, self.template_name)]

    def get_queryset(self):
        queryset = Game.objects.annotate(
            table_count=Count('created_tables', distinct=True),
            player_count=Count('created_tables__players', distinct=True)
        ).order_by('-table_count')

        for game in queryset:
            print(f"Game: {game.name}, Tavoli: {game.table_count}, Giocatori: {game.player_count}")

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['total_games'] = self.get_queryset().count()
        context['meta'] = Meta(
            title=_("Board Games - Board-Gamers.com"),
            description=_("Discover all available board games and create new game tables!"),
        )
        return context


class GameDetailView(DetailView):
    model = Game
    template_name = 'games/game_detail.html'
    context_object_name = 'game'

    def get_template_names(self):
        return [get_v2_template(self.request, self.template_name)]

    def get_queryset(self):
        return Game.objects.annotate(
            table_count=Count('created_tables', distinct=True),
            player_count=Count('created_tables__players', distinct=True)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game = self.get_object()
        context['table_count'] = game.table_count
        context['player_count'] = game.player_count
        context['meta'] = self.get_object().as_meta(self.request)
        return context
