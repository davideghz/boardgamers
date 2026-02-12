from collections import defaultdict

from django.contrib import messages
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q, Count, Subquery, OuterRef
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from django.views import generic, View
from django.views.generic import DetailView, CreateView

from webapp.forms import LocationForm, AddLocationManagerForm, TransferOwnershipForm
from webapp.messages import MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS
from webapp.models import Location, Table, UserProfile, Comment, Game, LocationFollower


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
        # nearby_locations = Location.objects.annotate(distance=DbDistance('point', user_location)).filter(distance__lt=50000, is_public=True).order_by('distance')
        nearby_locations = Location.objects.annotate(distance=DbDistance('point', user_location)).filter(is_public=True).order_by('distance')
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

        # Check if user is following location
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        is_following = False
        is_manager = False
        followers_count = location.followers.count()

        if user_profile:
            is_following = LocationFollower.objects.filter(user_profile=user_profile, location=location).exists()
            is_manager = location.creator == user_profile or user_profile in location.managers.all()

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

        # Sottoquery per contare le partite giocate per ogni gioco nella location
        played_count = Table.objects.filter(
            game=OuterRef('pk'),
            location=location
        ).values('game').annotate(
            count=Count('id', distinct=True)
        ).values('count')

        # # Sottoquery per trovare il giocatore con più vittorie per ogni gioco
        # top_player = UserProfile.objects.filter(
        #     joined_tables__game=OuterRef('pk'),
        #     player__position=1,
        #     joined_tables__location=location
        # ).annotate(
        #     win_count=Count('joined_tables', distinct=True)
        # ).order_by('-win_count').values('nickname')[:1]
        #
        # # Query principale per i giochi più giocati
        # popular_games = Game.objects.annotate(
        #     play_count=Subquery(played_count),
        #     top_winner=Subquery(top_player)
        # ).filter(play_count__gt=0).order_by('-play_count')[:10]

        popular_games = Game.objects.annotate(
            play_count=Subquery(played_count)
        ).filter(play_count__gt=0).order_by('-play_count')[:10]

        # Calcolo dei top winner con ex aequo
        winners = UserProfile.objects.filter(
            joined_tables__location=location,
            player__position=1
        ).values(
            'joined_tables__game', 'nickname'
        ).annotate(
            win_count=Count('joined_tables', distinct=True)
        )

        winners_by_game = defaultdict(lambda: {'max': 0, 'winners': []})

        for entry in winners:
            game_id = entry['joined_tables__game']
            nickname = entry['nickname']
            win_count = entry['win_count']

            current_max = winners_by_game[game_id]['max']
            if win_count > current_max:
                winners_by_game[game_id]['max'] = win_count
                winners_by_game[game_id]['winners'] = [nickname]
            elif win_count == current_max:
                winners_by_game[game_id]['winners'].append(nickname)

        for game in popular_games:
            top = winners_by_game.get(game.id)
            game.top_winners = top['winners'] if top else []

        # Query per i giocatori con numero di partite e posizioni
        player_stats = UserProfile.objects.filter(
            Q(joined_tables__location=location)
        ).annotate(
            play_count=Count('joined_tables', distinct=True),
            first_place=Count('joined_tables', filter=Q(player__position=1), distinct=True),
            second_place=Count('joined_tables', filter=Q(player__position=2), distinct=True),
            third_place=Count('joined_tables', filter=Q(player__position=3), distinct=True)
        ).order_by('-first_place', '-second_place', '-third_place', '-play_count')[:15]

        # Inserisco i dati nel contesto
        context = super().get_context_data(**kwargs)
        context['future_tables'] = future_tables
        context['past_tables'] = past_tables
        context['past_tables_count'] = past_tables_count
        context['future_tables_count'] = future_tables_count
        context['tables_count'] = past_tables_count + future_tables_count
        context['total_gamers_count'] = total_gamers_count
        context['popular_games'] = popular_games
        context['player_stats'] = player_stats
        context['is_following'] = is_following
        context['is_manager'] = is_manager
        context['followers_count'] = followers_count

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


class LocationUpdateView(LoginRequiredMixin, SuccessMessageMixin, generic.UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was updated successfully"

    def dispatch(self, request, *args, **kwargs):
        # First check authentication (handled by LoginRequiredMixin)
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        location = self.get_object()
        user_profile = request.user.user_profile
        # Check if user is owner or manager
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to edit this location.")
        return response

    def form_valid(self, form):
        location = form.save(commit=False)
        # Don't change the creator
        location.save()
        return super(LocationUpdateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("account-locations")


class LocationManageIndexView(LoginRequiredMixin, generic.DetailView):
    """Landing page for location management with navigation to sub-sections"""
    model = Location
    template_name = 'locations/location_manage_index.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        location = self.get_object()
        user_profile = request.user.user_profile
        # Check if user is owner or manager
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to manage this location.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.get_object()
        context['is_owner'] = location.creator == self.request.user.user_profile
        return context


class LocationManageManagersView(LoginRequiredMixin, generic.DetailView):
    """View to manage location managers (accessible to owners and managers)"""
    model = Location
    template_name = 'locations/location_manage_managers.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        location = self.get_object()
        user_profile = request.user.user_profile
        # Check if user is owner or manager
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to manage this location.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.get_object()
        context['managers'] = location.managers.all()
        context['is_owner'] = location.creator == self.request.user.user_profile
        context['add_manager_form'] = AddLocationManagerForm()
        context['transfer_ownership_form'] = TransferOwnershipForm()
        return context


class LocationManageDataView(LoginRequiredMixin, SuccessMessageMixin, generic.UpdateView):
    """View to edit location data (accessible to owners and managers)"""
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_manage_data.html'
    success_message = "Location was updated successfully"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        location = self.get_object()
        user_profile = request.user.user_profile
        # Check if user is owner or manager
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to edit this location.")
        return response

    def form_valid(self, form):
        location = form.save(commit=False)
        # Don't change the creator
        location.save()
        return super(LocationManageDataView, self).form_valid(form)

    def get_success_url(self):
        return reverse("location-manage", kwargs={'slug': self.object.slug})


class FollowLocationView(LoginRequiredMixin, View):
    @staticmethod
    def post(request, *args, **kwargs):
        location = get_object_or_404(Location, slug=kwargs['slug'])
        profile = request.user.user_profile

        follow, created = LocationFollower.objects.get_or_create(
            user_profile=profile, location=location
        )

        if created:
            # Nuovo follow
            messages.success(request, f"Hai iniziato a seguire {location.name}.")
        else:
            # Già seguiva → unfollow
            follow.delete()
            messages.success(request, f"Hai smesso di seguire {location.name}.")

        return redirect('location-detail', slug=location.slug)


class AddLocationManagerView(LoginRequiredMixin, View):
    """View to add a manager to a location (owner and managers)"""

    def post(self, request, *args, **kwargs):
        location = get_object_or_404(Location, slug=kwargs['slug'])
        user_profile = request.user.user_profile

        # Allow owner and managers to add managers
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to add managers.")

        # Get the manager to add from POST data
        manager_id = request.POST.get('manager')
        if not manager_id:
            messages.error(request, "No manager selected.")
            return redirect('location-manage-managers', slug=location.slug)

        try:
            manager = UserProfile.objects.get(id=manager_id)

            # Don't add owner as manager
            if manager == location.creator:
                messages.warning(request, "The owner is already the owner.")
                return redirect('location-manage-managers', slug=location.slug)

            # Add manager
            location.managers.add(manager)
            messages.success(request, f"{manager.nickname} has been added as a manager.")
        except UserProfile.DoesNotExist:
            messages.error(request, "User not found.")

        return redirect('location-manage-managers', slug=location.slug)


class RemoveLocationManagerView(LoginRequiredMixin, View):
    """View to remove a manager from a location (owner and managers)"""

    def post(self, request, *args, **kwargs):
        location = get_object_or_404(Location, slug=kwargs['slug'])
        user_profile = request.user.user_profile
        manager_id = kwargs.get('manager_id')

        # Allow owner and managers to remove managers
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to remove managers.")

        try:
            manager = UserProfile.objects.get(id=manager_id)

            # Don't allow removing the owner
            if manager == location.creator:
                messages.error(request, "Cannot remove the owner.")
                return redirect('location-manage-managers', slug=location.slug)

            # Remove manager
            location.managers.remove(manager)
            messages.success(request, f"{manager.nickname} has been removed as a manager.")
        except UserProfile.DoesNotExist:
            messages.error(request, "Manager not found.")

        return redirect('location-manage-managers', slug=location.slug)


class TransferOwnershipView(LoginRequiredMixin, View):
    """View to transfer ownership of a location (owner only)"""

    def post(self, request, *args, **kwargs):
        location = get_object_or_404(Location, slug=kwargs['slug'])
        user_profile = request.user.user_profile

        # Only owner can transfer ownership
        if location.creator != user_profile:
            raise PermissionDenied("Only the owner can transfer ownership.")

        # Get the new owner from POST data
        new_owner_id = request.POST.get('new_owner')
        if not new_owner_id:
            messages.error(request, "No new owner selected.")
            return redirect('location-managers', slug=location.slug)

        try:
            new_owner = UserProfile.objects.get(id=new_owner_id)

            # Transfer ownership
            old_owner = location.creator
            location.creator = new_owner

            # Remove new owner from managers if they were a manager
            if new_owner in location.managers.all():
                location.managers.remove(new_owner)

            # Optionally add old owner as manager
            add_old_owner_as_manager = request.POST.get('add_as_manager') == 'on'
            if add_old_owner_as_manager:
                location.managers.add(old_owner)

            location.save()
            messages.success(request, f"Ownership transferred to {new_owner.nickname}.")
        except UserProfile.DoesNotExist:
            messages.error(request, "User not found.")

        return redirect('location-detail', slug=location.slug)
