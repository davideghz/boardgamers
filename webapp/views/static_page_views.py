from django.contrib import messages
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.db.models import Prefetch, Count
from django.shortcuts import render, redirect
from django.utils import timezone

from webapp import emails
from webapp.forms import CustomLoginForm, ContactForm
from webapp.messages import MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS, MSG_CONTACT_MESSAGE_SENT_SUCCESSFULLY, \
    MSG_CONTACT_MESSAGE_ERROR
from webapp.models import Comment, UserProfile, Game, Table, Location

# for debug page
import environ
environ.Env.read_env()
from django.conf import settings


def homepage_view(request):
    user_location = None
    user_created_locations = None

    if request.user.is_authenticated:
        user_created_locations = request.user.user_profile.locations.all()
        try:
            profile = UserProfile.objects.only('latitude', 'longitude', 'point').filter(user=request.user).first()
            if profile and profile.latitude is not None and profile.longitude is not None:
                user_location = Point(float(profile.longitude), float(profile.latitude), srid=4326)
        except (TypeError, ValueError):
            pass

    today = timezone.now().date()

    comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
    players_prefetch = Prefetch('players', queryset=UserProfile.objects.select_related('user'))
    games_prefetch = Prefetch('game', queryset=Game.objects.all())

    # Query per i tavoli futuri
    future_tables = Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
        comments_prefetch, players_prefetch, games_prefetch
    ).filter(date__gte=today).order_by('date')

    # Query per i tavoli passati
    past_tables = Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
        comments_prefetch, players_prefetch, games_prefetch
    ).filter(date__lt=today).order_by('-date')[:12]

    # Se la posizione dell'utente è disponibile, ordina i tavoli futuri per distanza e filtra le locations vicine
    if user_location:
        future_tables = future_tables.annotate(distance=DbDistance('location__point', user_location)).order_by('date', 'distance')
        nearby_locations = Location.objects.annotate(distance=DbDistance('point', user_location)).filter(distance__lt=50000, is_public=True).order_by('distance')
        location_message = None  # Nessun messaggio se la posizione è presente
    else:
        # Se la posizione non è disponibile, mostra 10 locations randomiche
        nearby_locations = Location.objects.annotate(random_order=Count('id')).filter(is_public=True).order_by('?')[:10]
        location_message = MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS

    context = {
        'future_tables': future_tables,
        'past_tables': past_tables,
        'nearby_locations': nearby_locations,
        'location_message': location_message,
        'login_form': CustomLoginForm(),
        'user_created_locations': user_created_locations,
    }

    return render(request, "staticpages/home.html", context)


def privacy(request, template_name="staticpages/privacy.html"):
    return render(request, template_name, {})


def terms(request, template_name="staticpages/terms.html"):
    return render(request, template_name, {})


def test_login(request, template_name="staticpages/test_login.html"):
    return render(request, template_name, {})


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


def contacts(request):
    # Prepopola il form se l'utente è autenticato
    initial_data = {}
    if request.user.is_authenticated:
        initial_data = {
            'name': request.user.first_name or request.user.username,
            'email': request.user.email,
        }

    if request.method == 'POST':
        form = ContactForm(request.POST, initial=initial_data)
        if form.is_valid():
            emails.send_admin_contact_message(form.cleaned_data)
            messages.success(request, MSG_CONTACT_MESSAGE_SENT_SUCCESSFULLY)
            return redirect('contacts')
        else:
            messages.error(request, MSG_CONTACT_MESSAGE_ERROR, extra_tags='danger')
    else:
        form = ContactForm(initial=initial_data)

    return render(request, 'staticpages/contacts.html', {'form': form})
