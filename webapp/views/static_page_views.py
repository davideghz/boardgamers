import json

from django.contrib import messages
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.gis.measure import Distance

from django.db.models import Prefetch, Count
from django.shortcuts import render, redirect
from django.urls import reverse, translate_url
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import get_language_info, gettext_lazy as _

from meta.views import Meta
import mistune
import nh3

from webapp import emails
from webapp.forms import CustomLoginForm, ContactForm
from webapp.messages import MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS, MSG_CONTACT_MESSAGE_SENT_SUCCESSFULLY, \
    MSG_CONTACT_MESSAGE_ERROR
from webapp.models import Comment, UserProfile, Game, Table, Location, FAQ, Player

# for debug page
import environ
environ.Env.read_env()
from django.conf import settings


def homepage_view(request):
    user_location = None
    user_created_locations = None
    user_created_locations_ids = []

    if request.user.is_authenticated:
        user_created_locations = request.user.user_profile.locations.all()
        user_created_locations_ids = user_created_locations.values_list('id', flat=True) if user_created_locations else []
        try:
            profile = UserProfile.objects.only('latitude', 'longitude', 'point').filter(user=request.user).first()
            if profile and profile.latitude and profile.longitude:
                user_location = Point(float(profile.longitude), float(profile.latitude), srid=4326)
        except (TypeError, ValueError):
            pass

    today = timezone.now().date()

    comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
    players_prefetch = Prefetch('player_set', queryset=Player.objects.select_related('user_profile__user', 'guest_profile'))
    games_prefetch = Prefetch('game', queryset=Game.objects.all())

    # Query per i tavoli futuri
    future_tables = Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
        comments_prefetch, players_prefetch, games_prefetch
    ).filter(date__gte=today, location__show_tables_in_homepage=True, event__isnull=True).order_by('date')

    # Query per i tavoli passati
    past_tables = Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
        comments_prefetch, players_prefetch, games_prefetch
    ).filter(date__lt=today, location__show_tables_in_homepage=True, event__isnull=True).order_by('-date')[:12]

    # Se la posizione dell'utente è disponibile, ordina i tavoli futuri per distanza e filtra le locations vicine
    if user_location:
        future_tables = future_tables.annotate(distance=DbDistance('location__point', user_location)).order_by('date')
        if user_created_locations is not None:
            user_created_locations = user_created_locations.annotate(distance=DbDistance('point', user_location)).order_by('distance')
        nearby_locations = (Location.objects.annotate(distance=DbDistance('point', user_location)).filter(is_public=True)
                            .exclude(id__in=user_created_locations_ids)
                            .order_by('distance'))
        location_message = None  # Nessun messaggio se la posizione è presente
    else:
        # Se la posizione non è disponibile, mostra 10 locations randomiche
        nearby_locations = (Location.objects.annotate(random_order=Count('id'))
                            .filter(is_public=True)
                            .exclude(id__in=user_created_locations_ids)
                            .order_by('?')[:10])
        location_message = MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS

    context = {
        'future_tables': future_tables,
        'past_tables': past_tables,
        'nearby_locations': nearby_locations,
        'location_message': location_message,
        'login_form': CustomLoginForm(),
        'user_created_locations': user_created_locations,
        'meta': Meta(
            title=_("Find Board Game Tables Near You - Board-Gamers.com"),
            description=_("Discover board game tables near you, create new games and meet other players."),
        )
    }

    return render(request, "staticpages/home.html", context)


def privacy(request, template_name="staticpages/privacy.html"):
    return render(request, template_name, {
        'meta': Meta(
            title=_("Privacy Policy - Board-Gamers.com"),
            description=_("Read our privacy policy: how we collect, use and protect your personal data."),
        )
    })


def terms(request, template_name="staticpages/terms.html"):
    return render(request, template_name, {
        'meta': Meta(
            title=_("Terms of Service - Board-Gamers.com"),
            description=_("Read our terms of service: rules, responsibilities and platform usage conditions."),
        )
    })


def contacts(request):
    # Pre-popola il form se l'utente è autenticato
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

    return render(request, 'staticpages/contacts.html', {
        'form': form,
        'meta': Meta(
            title=_("Contacts - Board-Gamers.com"),
            description=_("Contact the boardgamers team: reports, suggestions or questions about the platform."),
        )
    })


def about(request):
    faqs = FAQ.objects.filter(is_active=True).select_related('category').order_by('category__order', 'order')
    about_stats = {
        'locations': Location.objects.filter(is_public=True).count(),
        'tables': Table.objects.count(),
        'players': UserProfile.objects.count(),
    }

    faq_jsonld = None
    if faqs:
        faq_jsonld = json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": faq.question,
                    "acceptedAnswer": {
                        "@type": "Answer",
                        "text": nh3.clean(mistune.html(faq.answer), tags=set()),
                    }
                }
                for faq in faqs
            ]
        }, ensure_ascii=False)

    return render(request, 'staticpages/about.html', {
        'faqs': faqs,
        'faq_jsonld': faq_jsonld,
        'about_stats': about_stats,
        'meta': Meta(
            title=_("About Board-Gamers.com - For Clubs & Associations"),
            description=_("Discover why board game clubs and associations choose Board-Gamers.com: free forever, open source, member management, tables, rankings and more."),
        )
    })


def select_language(request):
    next_param = request.GET.get("next")  # es. "/tables/..." oppure None

    select_language_path = reverse("select-language")

    # Fallback a home se next non c'è, non è un path interno sicuro, o punta a select-language stesso
    if not next_param or not url_has_allowed_host_and_scheme(
        next_param, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        next_path = reverse("home")
    elif next_param.startswith(("http://", "https://")):
        next_path = reverse("home")
    else:
        next_path = next_param

    # Evita loop: se next punta a select-language (con qualsiasi query string), usa home
    if next_path.rstrip("/").split("?")[0] == select_language_path.rstrip("/"):
        next_path = reverse("home")

    absolute_next = request.build_absolute_uri(next_path)

    languages = []
    for code, name in settings.LANGUAGES:
        info = get_language_info(code)  # per avere il nome locale, se vuoi
        languages.append({
            "code": code,
            "name": info.get("name_local") or name,   # es. “Italiano”, “English”
            "next": translate_url(absolute_next, code)
        })

    return render(request, "staticpages/select_language.html", {
        "languages": languages,
    })


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


def test_widget(request, template_name="staticpages/test_widget.html"):
    return render(request, template_name, {})
