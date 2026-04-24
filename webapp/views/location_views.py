from collections import defaultdict
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch, Q, Count, Subquery, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.urls import reverse
from django.utils.translation import gettext, gettext_lazy as _
from django.views import generic, View
from django.views.generic import DetailView, CreateView

from meta.views import Meta

from webapp.forms import LocationForm, AddLocationManagerForm, TransferOwnershipForm, MemberForm, ApproveMembershipForm, \
    MembershipRequestForm, MembershipEditForm, LocationGameForm, LocationPermissionsForm
from webapp.messages import MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS
from webapp.models import Location, Table, UserProfile, Comment, Game, LocationFollower, Member, Membership, LocationGame, \
    TelegramGroupConfig, Player


def index_view(request, template_name="locations/location_index.html"):
    user_location = None
    user_created_locations = None
    location_message = None
    nearby_locations = None
    followed_location_ids = set()

    if request.user.is_authenticated:
        user_created_locations = request.user.user_profile.locations.all()
        followed_location_ids = set(request.user.user_profile.followed_locations.values_list('location_id', flat=True))
        try:
            profile = UserProfile.objects.only('latitude', 'longitude', 'point').filter(user=request.user).first()
            if profile and profile.latitude and profile.longitude:
                user_location = Point(float(profile.longitude), float(profile.latitude), srid=4326)
        except (TypeError, ValueError):
            pass

    if user_location:
        if user_created_locations is not None:
            user_created_locations = user_created_locations.annotate(distance=DbDistance('point', user_location)).order_by('distance')
        nearby_locations = Location.objects.annotate(distance=DbDistance('point', user_location)).filter(is_public=True).order_by('distance')
    else:
        nearby_locations = Location.objects.annotate(random_order=Count('id')).filter(is_public=True).order_by('?')
        location_message = MSG_INSERT_ADDRESS_TO_FIND_NEAR_LOCATIONS

    context = {
        'nearby_locations': nearby_locations,
        'location_message': location_message,
        'user_created_locations': user_created_locations,
        'followed_location_ids': followed_location_ids,
        'meta': Meta(
            title=_("Game Locations - Board-Gamers.com"),
            description=_("Discover all board game locations near you. Find the perfect place for your next game!"),
        )
    }

    return render(request, template_name, context)


class LocationDetailView(DetailView):
    model = Location
    template_name = 'locations/location_detail.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_context_data(self, **kwargs):
        today = timezone.localdate()
        location = self.get_object()

        # Check if user is following location
        user_profile = self.request.user.user_profile if self.request.user.is_authenticated else None
        is_following = False
        is_manager = False
        followers_count = location.followers.count()

        has_pending_membership = False
        is_active_member = False
        if user_profile:
            is_following = LocationFollower.objects.filter(user_profile=user_profile, location=location).exists()
            is_manager = location.creator == user_profile or user_profile in location.managers.all()
            if not is_manager:
                has_pending_membership = Membership.objects.filter(
                    member__location=location,
                    member__user_profile=user_profile,
                    status=Membership.PENDING,
                ).exists()
                if not has_pending_membership:
                    is_active_member = Membership.objects.filter(
                        member__location=location,
                        member__user_profile=user_profile,
                        status=Membership.ACTIVE,
                    ).exists()

        # Prefetching per ottimizzare le query
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('player_set', queryset=Player.objects.select_related('user_profile__user', 'guest_profile'))
        games_prefetch = Prefetch('game', queryset=Game.objects.all())

        # Query per i tavoli futuri di questa location
        future_tables = Table.objects.filter(
            location=location,
            date__gte=today,
            event__isnull=True
        ).select_related('author', 'author__user', 'location').prefetch_related(
            comments_prefetch, players_prefetch, games_prefetch
        ).order_by('date')

        # Query per i tavoli passati di questa location
        past_tables = Table.objects.filter(
            location=location,
            date__lt=today,
            event__isnull=True
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
        context['has_pending_membership'] = has_pending_membership
        context['is_active_member'] = is_active_member
        context['meta'] = self.get_object().as_meta(self.request)

        return context


class LocationCreateView(LoginRequiredMixin, SuccessMessageMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was created successfully"

    def get_form_class(self):
        return LocationForm

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
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        location = self.get_object()
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to edit this location.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return LocationForm

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
        context['meta'] = Meta(
            title=_("Management %(name)s - Boardgamers.com") % {'name': location.name},
            description=_("Game nights in %(address)s") % {'address': location.address},
        )
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
        context['meta'] = Meta(
            title=_("Managers %(name)s - Boardgamers.com") % {'name': location.name},
            description=_("Manage managers of %(name)s location: add, remove and transfer ownership.") % {'name': location.name},
        )
        return context


class LocationManageDataView(LoginRequiredMixin, SuccessMessageMixin, generic.UpdateView):
    """View to edit location data (accessible to owners and managers)"""
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_manage_data.html'
    success_message = "Location was updated successfully"

    def get_form_class(self):
        return LocationForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        location = self.get_object()
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied("You don't have permission to edit this location.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        location = form.save(commit=False)
        # Don't change the creator
        location.save()
        return super(LocationManageDataView, self).form_valid(form)

    def get_success_url(self):
        return reverse("location-manage", kwargs={'slug': self.object.slug})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.get_object()
        context['meta'] = Meta(
            title=_("Edit %(name)s - Boardgamers.com") % {'name': location.name},
            description=_("Game nights in %(address)s") % {'address': location.address},
        )
        return context


class LocationManagePermissionsView(LoginRequiredMixin, SuccessMessageMixin, generic.UpdateView):
    """View to manage table creation/join permissions for a location."""
    model = Location
    form_class = LocationPermissionsForm
    template_name = 'locations/location_manage_permissions.html'
    success_message = _("Permissions updated successfully")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        location = self.get_object()
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("location-manage", kwargs={'slug': self.object.slug})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['location'] = self.get_object()
        return context


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


# ---- Member Management Views ----

def _require_membership_enabled(location):
    """Raise Http404 if membership is not enabled for this location."""
    if not location.enable_membership:
        raise Http404


class LocationManageMembersView(LoginRequiredMixin, generic.DetailView):
    """View to list and manage members of a location (accessible to owners and managers)"""
    model = Location
    template_name = 'locations/location_manage_members.html'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if not request.user.is_authenticated:
            return response

        location = self.get_object()
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage this location."))
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.get_object()
        members = location.members.prefetch_related('memberships').all()
        context['members'] = members
        context['is_owner'] = location.creator == self.request.user.user_profile
        context['meta'] = Meta(
            title=_("Members %(name)s - Boardgamers.com") % {'name': location.name},
            description=_("Manage members of %(name)s location.") % {'name': location.name},
        )
        return context


class MemberDetailEditView(LoginRequiredMixin, View):
    """View to see and edit a member's details (GET+POST). Accessible to owners and managers."""

    def _check_permission(self, request, location):
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage this location."))

    def get(self, request, slug, member_uuid):
        location = get_object_or_404(Location, slug=slug)
        self._check_permission(request, location)
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        memberships = member.memberships.select_related('approved_by').all()
        form = MemberForm(instance=member)
        membership_forms = {
            ms.uuid: MembershipEditForm(initial={
                'status': ms.status,
                'start_date': ms.start_date.isoformat() if ms.start_date else '',
                'end_date': ms.end_date.isoformat() if ms.end_date else '',
                'notes': ms.notes,
            })
            for ms in memberships
        }
        return render(request, 'locations/location_manage_member_detail.html', {
            'location': location,
            'member': member,
            'form': form,
            'memberships': memberships,
            'membership_forms': membership_forms,
            'meta': Meta(
                title=_("Member %(name)s - Boardgamers.com") % {'name': member.full_name},
            ),
        })

    def post(self, request, slug, member_uuid):
        location = get_object_or_404(Location, slug=slug)
        self._check_permission(request, location)
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        memberships = member.memberships.select_related('approved_by').all()
        form = MemberForm(request.POST, instance=member)
        if form.is_valid():
            form.save()
            messages.success(request, _("Member updated successfully."))
            return redirect('location-manage-members', slug=location.slug)
        membership_forms = {
            ms.uuid: MembershipEditForm(initial={
                'status': ms.status,
                'start_date': ms.start_date.isoformat() if ms.start_date else '',
                'end_date': ms.end_date.isoformat() if ms.end_date else '',
                'notes': ms.notes,
            })
            for ms in memberships
        }
        return render(request, 'locations/location_manage_member_detail.html', {
            'location': location,
            'member': member,
            'form': form,
            'memberships': memberships,
            'membership_forms': membership_forms,
            'meta': Meta(
                title=_("Member %(name)s - Boardgamers.com") % {'name': member.full_name},
            ),
        })


class AddMemberView(LoginRequiredMixin, View):
    """View to manually add a member to a location (owner and managers)"""

    def _check_permission(self, request, location):
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage this location."))

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        self._check_permission(request, location)
        FormClass = MemberForm
        form = FormClass()
        return render(request, 'locations/location_manage_member_detail.html', {
            'location': location,
            'member': None,
            'form': form,
            'is_new': True,
            'meta': Meta(
                title=_("Add Member - %(name)s") % {'name': location.name},
            ),
        })

    def post(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        self._check_permission(request, location)
        FormClass = MemberForm
        form = FormClass(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.location = location
            member.save()
            messages.success(request, _("Member %(name)s added successfully.") % {'name': member.full_name})
            return redirect('location-manage-members', slug=location.slug)
        return render(request, 'locations/location_manage_member_detail.html', {
            'location': location,
            'member': None,
            'form': form,
            'is_new': True,
            'meta': Meta(
                title=_("Add Member - %(name)s") % {'name': location.name},
            ),
        })


class ApproveMembershipView(LoginRequiredMixin, View):
    """View to approve or reject a pending membership (owner and managers)"""

    def post(self, request, slug, member_uuid):
        location = get_object_or_404(Location, slug=slug)
        _require_membership_enabled(location)
        user_profile = request.user.user_profile

        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage memberships."))

        member = get_object_or_404(Member, uuid=member_uuid, location=location)

        action = request.POST.get('action')  # 'approve' or 'reject'

        if action == 'reject':
            # Reject the latest pending membership
            pending = member.memberships.filter(status=Membership.PENDING).first()
            if pending:
                pending.status = Membership.REJECTED
                pending.save()
                messages.success(request, _("Membership for %(name)s rejected.") % {'name': member.full_name})
            return redirect('location-manage-members', slug=location.slug)

        if action == 'approve':
            form = ApproveMembershipForm(request.POST)
            if form.is_valid():
                import datetime
                pending = member.memberships.filter(status=Membership.PENDING).first()
                if pending:
                    pending.status = Membership.ACTIVE
                    pending.start_date = form.cleaned_data['start_date']
                    pending.end_date = form.cleaned_data['end_date']
                    pending.notes = form.cleaned_data.get('notes', '')
                    pending.approved_by = user_profile
                    pending.save()
                    messages.success(request, _("Membership for %(name)s approved.") % {'name': member.full_name})
                return redirect('location-manage-members', slug=location.slug)

        return redirect('location-manage-members', slug=location.slug)


class EditMembershipView(LoginRequiredMixin, View):
    """View to edit an existing membership (owner and managers)."""

    def post(self, request, slug, member_uuid, membership_uuid):
        location = get_object_or_404(Location, slug=slug)
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage memberships."))
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        membership = get_object_or_404(Membership, uuid=membership_uuid, member=member)
        form = MembershipEditForm(request.POST)
        if form.is_valid():
            membership.status = form.cleaned_data['status']
            membership.start_date = form.cleaned_data['start_date'] or None
            membership.end_date = form.cleaned_data['end_date'] or None
            membership.notes = form.cleaned_data.get('notes', '')
            membership.save()
            messages.success(request, _("Membership updated successfully."))
        else:
            for field, errors in form.errors.items():
                label = form.fields[field].label if field != '__all__' else None
                for error in errors:
                    msg = f"{label}: {error}" if label else error
                    messages.error(request, msg, extra_tags='danger')
        return redirect('location-member-detail', slug=location.slug, member_uuid=member.uuid)


class AddMembershipView(LoginRequiredMixin, View):
    """View to create a new PENDING membership for an existing member (owner and managers)."""

    def post(self, request, slug, member_uuid):
        location = get_object_or_404(Location, slug=slug)
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage memberships."))
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        Membership.objects.create(member=member, status=Membership.PENDING)
        messages.success(request, _("New membership created."))
        return redirect('location-member-detail', slug=location.slug, member_uuid=member.uuid)


class DownloadMembersCSVView(LoginRequiredMixin, View):
    """Download a CSV of all members for a location."""

    def get(self, request, slug):
        import csv
        location = get_object_or_404(Location, slug=slug)
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage this location."))

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="members-{location.slug}.csv"'
        response.write('\ufeff')  # BOM for Excel UTF-8

        writer = csv.writer(response)
        writer.writerow([
            _('First Name'), _('Last Name'), _('Code'), _('Email'),
            _('Phone'), _('Username'), _('Membership Status'),
            _('Start Date'), _('End Date'),
        ])

        members = location.members.prefetch_related('memberships', 'user_profile').order_by('last_name', 'first_name')
        for member in members:
            latest = member.memberships.first()
            writer.writerow([
                member.first_name,
                member.last_name,
                member.code,
                member.email,
                member.phone_number,
                member.user_profile.nickname if member.user_profile else '',
                latest.get_status_display() if latest else '',
                latest.start_date.isoformat() if latest and latest.start_date else '',
                latest.end_date.isoformat() if latest and latest.end_date else '',
            ])

        return response


class DeleteMembershipView(LoginRequiredMixin, View):
    """View to delete a membership (owner and managers)."""

    def post(self, request, slug, member_uuid, membership_uuid):
        location = get_object_or_404(Location, slug=slug)
        _require_membership_enabled(location)
        user_profile = request.user.user_profile
        if location.creator != user_profile and user_profile not in location.managers.all():
            raise PermissionDenied(_("You don't have permission to manage memberships."))
        member = get_object_or_404(Member, uuid=member_uuid, location=location)
        membership = get_object_or_404(Membership, uuid=membership_uuid, member=member)
        membership.delete()
        messages.success(request, _("Membership deleted."))
        return redirect('location-member-detail', slug=location.slug, member_uuid=member.uuid)


class RequestMembershipView(LoginRequiredMixin, View):
    """View for a logged-in user to request a membership for a location."""

    def _get_existing_membership(self, user_profile, location):
        """Returns a blocking membership (PENDING or ACTIVE) if it exists."""
        return Membership.objects.filter(
            member__location=location,
            member__user_profile=user_profile,
            status__in=[Membership.PENDING, Membership.ACTIVE],
        ).first()

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.enable_membership:
            raise PermissionDenied(_("This location does not accept membership requests."))
        user_profile = request.user.user_profile
        if self._get_existing_membership(user_profile, location):
            messages.warning(request, _("You already have a pending or active membership for this location."))
            return redirect('location-detail', slug=location.slug)
        form = MembershipRequestForm()
        return render(request, 'locations/location_request_membership.html', {
            'location': location,
            'form': form,
            'meta': Meta(
                title=_("Request Membership - %(name)s") % {'name': location.name},
            ),
        })

    def post(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.enable_membership:
            raise PermissionDenied(_("This location does not accept membership requests."))
        form = MembershipRequestForm(request.POST)
        user_profile = request.user.user_profile

        if form.is_valid():
            # Check if user already has a member record for this location
            member, created = Member.objects.get_or_create(
                location=location,
                user_profile=user_profile,
                defaults={
                    'first_name': request.user.first_name or user_profile.nickname,
                    'last_name': request.user.last_name or '',
                    'email': request.user.email or '',
                }
            )

            # Check if there's already a pending or active membership
            if member.memberships.filter(status__in=[Membership.PENDING, Membership.ACTIVE]).exists():
                messages.warning(request, _("You already have a pending or active membership for this location."))
                return redirect('location-detail', slug=location.slug)

            # Create pending membership
            Membership.objects.create(
                member=member,
                status=Membership.PENDING,
                notes=form.cleaned_data.get('notes', ''),
            )
            messages.success(request, _("Membership request sent. A manager will review it."))
            return redirect('location-detail', slug=location.slug)

        return render(request, 'locations/location_request_membership.html', {
            'location': location,
            'form': form,
        })


# ---- Game Library Management Views ----

def _check_location_manager(request, location):
    """Raise PermissionDenied if the current user is not owner or manager of the location."""
    user_profile = request.user.user_profile
    if location.creator != user_profile and user_profile not in location.managers.all():
        raise PermissionDenied(_("You don't have permission to manage this location."))


class LocationManageGamesView(LoginRequiredMixin, View):
    """List all games in a location's library."""

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        location_games = location.location_games.select_related('game', 'owner_member').all()
        return render(request, 'locations/location_manage_games.html', {
            'location': location,
            'location_games': location_games,
            'meta': Meta(title=_("Games – %(name)s") % {'name': location.name}),
        })


class AddLocationGameView(LoginRequiredMixin, View):
    """Add a game to a location's library."""

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        form = LocationGameForm(location=location)
        return render(request, 'locations/location_manage_game_detail.html', {
            'location': location,
            'location_game': None,
            'form': form,
            'is_new': True,
            'meta': Meta(title=_("Add Game – %(name)s") % {'name': location.name}),
        })

    def post(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        form = LocationGameForm(request.POST, location=location)
        if form.is_valid():
            location_game = form.save(commit=False)
            location_game.location = location
            location_game.save()
            messages.success(request, _("Game «%(name)s» added to the library.") % {'name': location_game.game.name})
            return redirect('location-manage-games', slug=location.slug)
        return render(request, 'locations/location_manage_game_detail.html', {
            'location': location,
            'location_game': None,
            'form': form,
            'is_new': True,
            'meta': Meta(title=_("Add Game – %(name)s") % {'name': location.name}),
        })


class LocationGameDetailView(LoginRequiredMixin, View):
    """Edit details of a game in a location's library."""

    def get(self, request, slug, game_uuid):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        location_game = get_object_or_404(LocationGame, uuid=game_uuid, location=location)
        form = LocationGameForm(instance=location_game, location=location)
        return render(request, 'locations/location_manage_game_detail.html', {
            'location': location,
            'location_game': location_game,
            'form': form,
            'is_new': False,
            'meta': Meta(title=_("%(game)s – %(name)s") % {'game': location_game.game.name, 'name': location.name}),
        })

    def post(self, request, slug, game_uuid):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        location_game = get_object_or_404(LocationGame, uuid=game_uuid, location=location)
        form = LocationGameForm(request.POST, instance=location_game, location=location)
        if form.is_valid():
            form.save()
            messages.success(request, _("Game updated successfully."))
            return redirect('location-manage-games', slug=location.slug)
        return render(request, 'locations/location_manage_game_detail.html', {
            'location': location,
            'location_game': location_game,
            'form': form,
            'is_new': False,
            'meta': Meta(title=_("%(game)s – %(name)s") % {'game': location_game.game.name, 'name': location.name}),
        })


class DeleteLocationGameView(LoginRequiredMixin, View):
    """Remove a game from a location's library."""

    def post(self, request, slug, game_uuid):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        location_game = get_object_or_404(LocationGame, uuid=game_uuid, location=location)
        game_name = location_game.game.name
        location_game.delete()
        messages.success(request, _("Game «%(name)s» removed from the library.") % {'name': game_name})
        return redirect('location-manage-games', slug=location.slug)


class LocationManageWidgetView(LoginRequiredMixin, View):
    """Show embeddable widget snippet for a location."""

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        return render(request, 'locations/location_manage_widget.html', {
            'location': location,
            'meta': Meta(title=_("Widget – %(name)s") % {'name': location.name}),
        })


class LocationManageTelegramView(LoginRequiredMixin, View):
    """Telegram bot configuration for a location."""

    def get(self, request, slug):
        from django.conf import settings as django_settings
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        configs = location.telegram_configs.filter(active=True)
        return render(request, 'locations/location_manage_telegram.html', {
            'location': location,
            'configs': configs,
            'bot_username': django_settings.TELEGRAM_BOT_USERNAME,
            'meta': Meta(title=_("Telegram – %(name)s") % {'name': location.name}),
        })


class DisconnectTelegramGroupView(LoginRequiredMixin, View):
    """Deactivate a Telegram group config for a location."""

    def post(self, request, slug, config_id):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)
        TelegramGroupConfig.objects.filter(id=config_id, location=location).update(active=False)
        return redirect('location-manage-telegram', slug=slug)


class LocationManageTableStatsView(LoginRequiredMixin, View):
    """Generate a copy-pasteable status message for tables in a date range."""

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)

        today = date.today()
        date_from_str = request.GET.get('date_from', '')
        date_to_str = request.GET.get('date_to', '')

        try:
            date_from = date.fromisoformat(date_from_str) if date_from_str else today
        except ValueError:
            date_from = today
        try:
            date_to = date.fromisoformat(date_to_str) if date_to_str else date_from
        except ValueError:
            date_to = date_from

        if date_to < date_from:
            date_to = date_from

        submitted = bool(request.GET)
        show_full = request.GET.get('show_full') == 'on' if submitted else True
        show_closed = request.GET.get('show_closed') == 'on' if submitted else True
        show_names = request.GET.get('show_names') == 'on' if submitted else False

        tables = (
            Table.objects
            .filter(location=location, date__gte=date_from, date__lte=date_to)
            .select_related('game')
            .prefetch_related(
                Prefetch(
                    'player_set',
                    queryset=Player.objects.select_related('user_profile', 'guest_profile__owner'),
                )
            )
            .order_by('date', 'time')
        )

        location_url = request.build_absolute_uri(reverse('location-detail', args=[location.slug]))
        message_text = self._build_message(list(tables), date_from, date_to, show_full, show_closed, show_names, location_url)

        return render(request, 'locations/location_manage_table_stats.html', {
            'location': location,
            'date_from': date_from.isoformat(),
            'date_to': date_to.isoformat(),
            'show_full': show_full,
            'show_closed': show_closed,
            'show_names': show_names,
            'message_text': message_text,
            'meta': Meta(title=_("Table stats – %(name)s") % {'name': location.name}),
        })

    def _build_message(self, tables, date_from, date_to, show_full, show_closed, show_names, location_url):
        lines = []

        if date_from == date_to:
            lines.append(gettext('Tables of %(date)s') % {'date': date_from.strftime('%d/%m/%Y')})
        else:
            lines.append(gettext('Tables from %(date_from)s to %(date_to)s') % {
                'date_from': date_from.strftime('%d/%m/%Y'),
                'date_to': date_to.strftime('%d/%m/%Y'),
            })

        active_tables = [t for t in tables if t.status in (Table.OPEN, Table.ONGOING)]
        closed_tables = [t for t in tables if t.status == Table.CLOSED]

        def table_label(t):
            name = t.game.name if t.game else (t.title if t.title else gettext('Table'))
            return f'*{name}*'

        def fmt_players(t):
            names = [p.display_name for p in t.player_set.all()]
            return ', '.join(names) if names else '—'

        available_tables = [t for t in active_tables if t.total_players < t.max_players]
        full_tables = [t for t in active_tables if t.total_players >= t.max_players]

        if available_tables:
            lines.append('')
            lines.append(gettext('🟢 Available seats:'))
            for t in available_tables:
                occupied = t.total_players
                seats = gettext('%(occupied)s/%(max)s seats') % {'occupied': occupied, 'max': t.max_players}
                line = f'• {table_label(t)}: {seats}'
                if show_names:
                    line += f' – {fmt_players(t)}'
                lines.append(line)

        if show_full and full_tables:
            lines.append('')
            lines.append(gettext('🟡 Full tables:'))
            for t in full_tables:
                occupied = t.total_players
                seats = gettext('%(occupied)s/%(max)s seats') % {'occupied': occupied, 'max': t.max_players}
                line = f'• {table_label(t)}: {seats}'
                if show_names:
                    line += f' – {fmt_players(t)}'
                lines.append(line)

        if show_closed and closed_tables:
            lines.append('')
            lines.append(gettext('🔴 Closed tables:'))
            for t in closed_tables:
                line = f'• {table_label(t)}'
                if show_names:
                    line += f': {fmt_players(t)}'
                lines.append(line)

        if not active_tables and not closed_tables:
            lines.append('')
            lines.append(gettext('No tables found for this period.'))

        lines.append('')
        lines.append(gettext('Join a table: %(url)s') % {'url': location_url})

        return '\n'.join(lines)


class DownloadGamesCSVView(LoginRequiredMixin, View):
    """Download a CSV of all games in a location's library."""

    def get(self, request, slug):
        import csv
        location = get_object_or_404(Location, slug=slug)
        _check_location_manager(request, location)

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="games-{location.slug}.csv"'
        response.write('\ufeff')  # BOM for Excel UTF-8

        writer = csv.writer(response)
        writer.writerow([
            _('Game'), _('Ownership'), _('Owner Member'), _('Physical Location'), _('Notes'),
        ])

        location_games = location.location_games.select_related('game', 'owner_member').all()
        for lg in location_games:
            writer.writerow([
                lg.game.name,
                lg.get_ownership_display(),
                str(lg.owner_member) if lg.owner_member else '',
                lg.get_physical_location_display(),
                lg.notes,
            ])

        return response


class LocationCalendarView(View):
    """Calendar view: physical tables × days. Mock data — no DB changes."""

    template_name = 'locations/location_calendar.html'

    _MOCK_TABLES = [
        {'id': 1, 'nome': 'Tavolo 1', 'sala': 'Sala Grande'},
        {'id': 2, 'nome': 'Tavolo 2', 'sala': 'Sala Grande'},
        {'id': 3, 'nome': 'Tavolo 3', 'sala': 'Sala Grande'},
        {'id': 4, 'nome': 'Tavolo 4', 'sala': 'Sala Grande'},
        {'id': 5, 'nome': 'Tavolo 5', 'sala': 'Sala Grande'},
    ]

    _MOCK_SESSION_DURATION_H = 3  # assumed duration for overlap check

    @staticmethod
    def _times_overlap(t1, t2, duration_h):
        from datetime import datetime as dt
        d1 = dt(2000, 1, 1, t1.hour, t1.minute)
        d2 = dt(2000, 1, 1, t2.hour, t2.minute)
        return abs((d1 - d2).total_seconds()) / 3600 < duration_h

    def _assign_sessions_to_tables(self, sessions_by_date):
        """Greedy: assign each session to the first physical table with no time conflict."""
        assignment = defaultdict(list)
        dur = self._MOCK_SESSION_DURATION_H
        for day, sessions in sessions_by_date.items():
            for session in sorted(sessions, key=lambda s: s.time):
                for pt in self._MOCK_TABLES:
                    existing = assignment[(pt['id'], day)]
                    if not any(self._times_overlap(session.time, e.time, dur) for e in existing):
                        existing.append(session)
                        break
        return assignment

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.enable_calendar:
            raise Http404
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        dates = [monday + timedelta(days=i) for i in range(35)]  # 5 weeks

        # Real sessions from DB
        sessions_qs = Table.objects.filter(
            location=location,
            date__gte=dates[0],
            date__lte=dates[-1],
        ).select_related('game').order_by('date', 'time')
        sessions_by_date = defaultdict(list)
        for s in sessions_qs:
            sessions_by_date[s.date].append(s)

        assignment = self._assign_sessions_to_tables(sessions_by_date)

        # Date headers
        date_headers = []
        prev_month = None
        for d in dates:
            date_headers.append({
                'date': d,
                'is_today': d == today,
                'is_weekend': d.weekday() >= 5,
                'month_changed': d.month != prev_month,
            })
            prev_month = d.month

        # Grid rows
        rows = []
        for pt in self._MOCK_TABLES:
            cells = []
            for dh in date_headers:
                d = dh['date']
                cells.append({
                    'sessions': assignment.get((pt['id'], d), []),
                    'is_today': dh['is_today'],
                    'is_weekend': dh['is_weekend'],
                    'month_changed': dh['month_changed'],
                    'date': d,
                })
            rows.append({'table': pt, 'cells': cells})

        is_manager = False
        if request.user.is_authenticated:
            try:
                up = request.user.user_profile
                is_manager = location.creator == up or up in location.managers.all()
            except Exception:
                pass

        return render(request, self.template_name, {
            'location': location,
            'date_headers': date_headers,
            'rows': rows,
            'today': today,
            'is_manager': is_manager,
        })
