from django.db.models import Count, Q
from django.views.generic import ListView
from django.views.generic.detail import DetailView
from django.utils.translation import gettext_lazy as _

from meta.views import Meta

from webapp.models import Game, Location
from webapp.services.game_loans import can_view_game_library, is_active_member


class GameListView(ListView):
    model = Game
    template_name = 'games/game_list.html'
    context_object_name = 'games'
    paginate_by = 24  # fills whole rows of the 2/3/4-column grid

    def get_queryset(self):
        self.q = self.request.GET.get('q', '').strip()
        queryset = Game.objects.annotate(
            table_count=Count('created_tables', distinct=True),
            player_count=Count('created_tables__players', distinct=True)
        )
        if self.q:
            queryset = queryset.filter(Q(name__icontains=self.q) | Q(description__icontains=self.q))
        # name as tie-breaker keeps pages stable across games with the same table count
        return queryset.order_by('-table_count', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['q'] = self.q
        context['meta'] = Meta(
            title=_("Board Games - Board-Gamers.com"),
            description=_("Discover all available board games and create new game tables!"),
        )
        return context


class GameDetailView(DetailView):
    model = Game
    template_name = 'games/game_detail.html'
    context_object_name = 'game'

    def get_queryset(self):
        return Game.objects.annotate(
            table_count=Count('created_tables', distinct=True),
            player_count=Count('created_tables__players', distinct=True)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        game = self.object
        context['table_count'] = game.table_count
        context['player_count'] = game.player_count
        context['meta'] = game.as_meta(self.request)
        context['locations'] = (
            Location.objects
            .filter(tables__game=game)
            .annotate(game_table_count=Count('tables', distinct=True))
            .order_by('-game_table_count')
        )
        params = self.request.GET
        from_location = params.get('from_location')
        if from_location:
            location = Location.objects.filter(
                slug=from_location, location_games__game=game, location_games__is_archived=False,
            ).first()
            profile = getattr(self.request.user, 'user_profile', None)
            if location and can_view_game_library(location, is_member=is_active_member(location, profile)):
                context['back_location'] = location
                context['back_library_query'] = {key: params[key] for key in ('q', 'page') if key in params}
        return context
