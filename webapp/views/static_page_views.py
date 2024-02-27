from django.db.models import Prefetch
from django.shortcuts import render
from django.utils import timezone
from django.views import generic

from webapp.forms import CustomLoginForm
from webapp.models import Comment, UserProfile, Game, Table


class HomepageView(generic.ListView):
    template_name = "staticpages/home.html"
    context_object_name = "tables"

    def get_queryset(self):
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('players', queryset=UserProfile.objects.select_related('user'))
        games_prefetch = Prefetch('games', queryset=Game.objects.all())
        today = timezone.now().date()
        return Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
            comments_prefetch,
            players_prefetch,
            games_prefetch,
        ).filter(date__gte=today).order_by('date')

    def get_context_data(self, **kwargs):
        context = super(HomepageView, self).get_context_data(**kwargs)
        context['login_form'] = CustomLoginForm()
        return context


import environ
environ.Env.read_env()


def env(request, template_name="staticpages/env.html"):
    env_list = environ.Env()
    DJANGO_SETTINGS_MODULE = env_list('DJANGO_SETTINGS_MODULE')

    return render(request, template_name, {
        'env_list': env_list,
        'DJANGO_SETTINGS_MODULE': DJANGO_SETTINGS_MODULE,
    })
