from django.contrib.gis.db.models.functions import GeometryDistance
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geos import Point, fromstr
from django.contrib.gis.measure import Distance
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.db.models import Prefetch
from django.shortcuts import render
from django.utils import timezone
from django.views import generic

from webapp.forms import CustomLoginForm
from webapp.models import Comment, UserProfile, Game, Table, Location


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
from django.conf import settings


def debug(request, template_name="staticpages/debug.html"):
    env_list = environ.Env()
    DJANGO_SETTINGS_MODULE = env_list('DJANGO_SETTINGS_MODULE')

    g = GeoIP2()

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        user_ip = x_forwarded_for.split(',')[0]
    else:
        user_ip = request.META.get('REMOTE_ADDR')

    if user_ip == '127.0.0.1':
        user_ip = '93.66.88.167'

    city = g.city(user_ip)
    user_point = g.geos(user_ip)

    pozzobonelli = Point(9.1948628, 45.5216581, srid=4326)
    cherso = Point(9.1979062, 45.5206266, srid=4326)

    print('--------- Pozzobonelli > Cherso -----------')
    print(pozzobonelli.distance(cherso)*111.139)

    tables = (Table.objects.filter(location__point__distance_lt=(user_point, Distance(m=55000)))
              .annotate(distance=DbDistance('location__point', user_point))
              .order_by('distance'))

    return render(request, template_name, {
        'DJANGO_SETTINGS_MODULE': DJANGO_SETTINGS_MODULE,
        'AWS_STORAGE_BUCKET_NAME': settings.AWS_STORAGE_BUCKET_NAME,
        'AWS_S3_CUSTOM_DOMAIN': settings.AWS_S3_CUSTOM_DOMAIN,
        'user_ip': user_ip,
        'city': city,
        'user_point': user_point,
        'tables': tables,
    })
