from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Prefetch, Q, Count
from django.shortcuts import render
from django.utils import timezone
from django.urls import reverse
from django.views import generic
from django.views.generic import DetailView, CreateView

from webapp.forms import LocationForm
from webapp.messages import MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS
from webapp.models import Location, Table, UserProfile, Comment, Game


def index_view(request, template_name="locations/location_index.html"):
    user_location = None
    user_created_locations = None
    location_message = None
    nearby_locations = None

    if request.user.is_authenticated:
        user_created_locations = request.user.user_profile.locations.all()
        try:
            profile = UserProfile.objects.only('latitude', 'longitude', 'point').filter(user=request.user).first()
            if profile and profile.latitude is not None and profile.longitude is not None:
                user_location = Point(float(profile.longitude), float(profile.latitude), srid=4326)
        except (TypeError, ValueError):
            pass

    if user_location:
        nearby_locations = Location.objects.annotate(distance=DbDistance('point', user_location)).filter(distance__lt=50000, is_public=True).order_by('distance')
    else:
        nearby_locations = Location.objects.annotate(random_order=Count('id')).filter(is_public=True).order_by('?')[:10]
        location_message = MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS

    context = {
        'nearby_locations': nearby_locations,
        'location_message': location_message,
        'user_created_locations': user_created_locations,
    }

    return render(request, template_name, context)


class LocationDetailView(DetailView):
    model = Location
    template_name = 'locations/location_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_context_data(self, **kwargs):
        today = timezone.now().date()
        location = self.get_object()

        # Prefetching per ottimizzare le query
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('players', queryset=UserProfile.objects.select_related('user'))
        games_prefetch = Prefetch('game', queryset=Game.objects.all())

        # Query per i tavoli futuri di questa location
        future_tables = Table.objects.filter(
            location=location,
            date__gte=today
        ).select_related('author', 'author__user', 'location').prefetch_related(
            comments_prefetch, players_prefetch, games_prefetch
        ).order_by('date')

        # Query per i tavoli passati di questa location
        past_tables = Table.objects.filter(
            location=location,
            date__lt=today
        ).select_related('author', 'author__user', 'location').prefetch_related(
            comments_prefetch, players_prefetch, games_prefetch
        ).order_by('-date')

        # Conteggio dei tavoli passati e futuri
        past_tables_count = past_tables.count()
        future_tables_count = future_tables.count()

        # Conta i giocatori unici che hanno partecipato a tavoli in questa location
        total_gamers_count = UserProfile.objects.filter(
            Q(joined_tables__location=location) | Q(created_tables__location=location)
        ).distinct().count()

        # Inserisco i dati nel contesto
        context = super().get_context_data(**kwargs)
        context['future_tables'] = future_tables
        context['past_tables'] = past_tables
        context['past_tables_count'] = past_tables_count
        context['future_tables_count'] = future_tables_count
        context['tables_count'] = past_tables_count + future_tables_count
        context['total_gamers_count'] = total_gamers_count

        return context


class LocationCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was created successfully"

    def form_valid(self, form):
        form.instance.creator = self.request.user.user_profile
        response = super(LocationCreateView, self).form_valid(form)
        # with transaction.atomic():
        #     self.object.players.add(self.request.user.user_profile)
        return response

    def get_success_url(self):
        return reverse("account-locations")


class LocationUpdateView(SuccessMessageMixin, generic.UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was updated successfully"

    def form_valid(self, form):
        location = form.save(commit=False)
        creator = self.request.user.user_profile
        location.creator = creator
        location.save()
        return super(LocationUpdateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("account-locations")
