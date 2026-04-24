from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.measure import Distance
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.messages.views import SuccessMessageMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import generic, View
from meta.views import Meta

from webapp.forms import TableForm, CustomLoginForm, CommentForm, AddTablePlayerForm
from webapp.messages import MSG_VERIFY_EMAIL_BEFORE_PROCEEDING
from webapp.models import Table, Comment, Player, UserProfile, Game, Location, CommentType, GuestProfile, Membership
from webapp.views.decorators import only_author_or_admin_can_edit, only_admin_can_edit_closed_table, author_or_admin_required


class IsAuthorOrAdminTestMixin(UserPassesTestMixin):
    def test_func(self):
        obj = self.get_object()
        user = self.request.user
        if obj.author.user == user or user.is_superuser:
            return True
        location = getattr(obj, 'location', None)
        if location and user.is_authenticated:
            up = user.user_profile
            if location.creator_id == up.id or location.managers.filter(id=up.id).exists():
                return True
        return False


class IsNotClosedMixin(UserPassesTestMixin):
    """
    Impedisce l'accesso (GET/POST) se l'oggetto è in stato CLOSED.
    Da usare insieme a IsAuthorOrAdminTestMixin.
    """
    closed_status = Table.CLOSED  # così è override-abile se mai cambiasse

    def test_func(self):
        obj = self.get_object()
        return obj.status != self.closed_status

    def handle_no_permission(self):
        # Se oggetto esiste ed è chiuso, rendi chiaro il motivo
        obj = getattr(self, "object", None)
        if obj and obj.status == self.closed_status:
            raise PermissionDenied("Non è possibile eliminare un tavolo chiuso.")
        return super().handle_no_permission()


class TableIndexView(generic.ListView):
    template_name = "tables/table_index.html"
    context_object_name = "tables"

    def get_queryset(self):
        return Table.objects.none()

    def get_context_data(self, **kwargs):
        context = super(TableIndexView, self).get_context_data(**kwargs)

        g = GeoIP2()
        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            user_ip = x_forwarded_for.split(',')[0]
        else:
            user_ip = self.request.META.get('REMOTE_ADDR')
        if user_ip == '127.0.0.1':
            user_ip = '93.66.88.167'
        user_point = g.geos(user_ip)

        today = timezone.localdate()
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('player_set', queryset=Player.objects.select_related('user_profile__user', 'guest_profile'))
        games_prefetch = Prefetch('game', queryset=Game.objects.all())

        base_qs = (Table.objects
                   .select_related('author', 'author__user', 'location')
                   .prefetch_related(comments_prefetch, players_prefetch, games_prefetch)
                   .filter(location__show_tables_in_homepage=True)
                   .annotate(distance=DbDistance('location__point', user_point)))

        context['future_tables'] = base_qs.filter(date__gte=today).order_by('date', 'distance')
        context['past_tables'] = base_qs.filter(date__lt=today).order_by('-date', 'distance')
        context['login_form'] = CustomLoginForm()
        context['meta'] = Meta(
            title=_("Game Tables - Board-Gamers.com"),
            description=_("Discover all available game tables and join the game!"),
        )
        return context


class BaseTableDetailView(generic.DetailView):
    """Shared logic for both location-table and event-table detail pages."""
    model = Table

    def get_queryset(self):
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        return super().get_queryset().prefetch_related(comments_prefetch)

    def get_comment_redirect(self):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        table = self.get_object()

        if self.request.user.is_authenticated:
            self.request.user.user_profile.notifications.filter(
                Q(notification_type='new_comment') & Q(table=table)
            ).update(is_read=True)

        max_players = table.max_players
        external_players = table.external_players
        today = timezone.localdate()

        players = Player.objects.filter(table=table).select_related(
            'user_profile', 'guest_profile', 'guest_profile__owner'
        ).order_by('position')
        current_players = players.count() + external_players

        leaderboard_enabled = table.game and table.game.leaderboard_enabled
        leaderboard_visible = any(player.position != 99 for player in players)

        user_can_edit_leaderboard = (
            (self.request.user.is_authenticated and leaderboard_enabled and
             ((table.leaderboard_status == table.LEADERBOARD_EDITABLE) and
              self.request.user.user_profile in table.players.all()) or
             self.request.user.is_superuser)
        )

        user_available_guests = None
        if (self.request.user.is_authenticated and
                table.status == Table.OPEN and
                Player.objects.filter(table=table, user_profile=self.request.user.user_profile).exists()):
            already_at_table = players.filter(guest_profile__isnull=False).values_list('guest_profile_id', flat=True)
            user_available_guests = GuestProfile.objects.filter(
                owner=self.request.user.user_profile
            ).exclude(id__in=already_at_table)

        context = super().get_context_data(**kwargs)
        context.update({
            'comment_form': CommentForm(),
            'available_seats': max_players - current_players,
            'available_seats_range': range(max(0, max_players - current_players)),
            'current_players': current_players,
            'availability_percent': round(current_players / max_players * 100),
            'today': today,
            'players': players,
            'leaderboard_enabled': leaderboard_enabled,
            'leaderboard_visible': leaderboard_visible,
            'user_can_edit_leaderboard': user_can_edit_leaderboard,
            'user_available_guests': user_available_guests,
            'meta': table.as_meta(self.request),
        })
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if 'comment_form' in request.POST:
            form = CommentForm(request.POST)
            if form.is_valid():
                comment = form.save(commit=False)
                comment.table = self.object
                comment.author = request.user.user_profile
                comment.save()
                return self.get_comment_redirect()
        context = self.get_context_data(object=self.object)
        return self.render_to_response(context)


class TableDetailView(BaseTableDetailView):
    template_name = "tables/table_detail.html"

    def dispatch(self, request, *args, **kwargs):
        table = get_object_or_404(Table.objects.select_related('event'), slug=kwargs['slug'])
        if table.event_id:
            return redirect('event_table_detail', event_slug=table.event.slug, table_slug=table.slug)
        return super().dispatch(request, *args, **kwargs)

    def get_comment_redirect(self):
        return redirect('table-detail', slug=self.object.slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        table = self.object

        is_active_member = False
        has_pending_membership = False
        is_location_manager = False
        if self.request.user.is_authenticated and table.location:
            up = self.request.user.user_profile
            loc = table.location
            is_location_manager = loc.creator == up or up in loc.managers.all()
            if not is_location_manager:
                has_pending_membership = Membership.objects.filter(
                    member__location=loc,
                    member__user_profile=up,
                    status=Membership.PENDING,
                ).exists()
                is_active_member = Membership.objects.filter(
                    member__location=loc,
                    member__user_profile=up,
                    status=Membership.ACTIVE,
                ).exists()

        context.update({
            'is_active_member': is_active_member,
            'has_pending_membership': has_pending_membership,
            'is_location_manager': is_location_manager,
        })
        return context


@login_required
def table_players_view(request, slug):
    table = get_object_or_404(Table, slug=slug)

    # Solo l'autore del tavolo o l'admin può accedere
    if not (request.user.is_superuser or table.author.user == request.user):
        messages.error(request, "You do not have permission to manage players for this table.", extra_tags="danger")
        return redirect("table-detail", slug=slug)

    players = Player.objects.filter(table=table).select_related("user_profile", "guest_profile", "guest_profile__owner")
    add_player_form = AddTablePlayerForm()

    return render(request, "tables/table_players.html", {
        "table": table,
        "players": players,
        'available_seats': max(0, table.max_players - players.count() - table.external_players),
        'add_player_form': add_player_form,
    })


class AddTablePlayerView(LoginRequiredMixin, View):
    """View to manually add a player to a table (author/admin only)"""

    def post(self, request, *args, **kwargs):
        table = get_object_or_404(Table, slug=kwargs['slug'])

        # Permission check
        if not (request.user.is_superuser or table.author.user == request.user):
            messages.error(request, _("You do not have permission to add players to this table."), extra_tags="danger")
            return redirect("table-players", slug=table.slug)

        # Table status check — autore e admin possono sempre aggiungere
        if table.status == Table.CLOSED and not (request.user.is_superuser or table.author.user == request.user):
            messages.error(request, _("Cannot add players to a closed table."), extra_tags="danger")
            return redirect("table-players", slug=table.slug)

        form = AddTablePlayerForm(request.POST)
        if form.is_valid():
            user_profile = form.cleaned_data['player']

            # Check if already in table
            if Player.objects.filter(table=table, user_profile=user_profile).exists():
                messages.warning(request, _(f"{user_profile.nickname} is already at the table."))
                return redirect("table-players", slug=table.slug)

            # Check available seats (includes guest players)
            current_players = Player.objects.filter(table=table).count() + table.external_players
            if current_players >= table.max_players:
                messages.error(request, _("The table is full."), extra_tags="danger")
                return redirect("table-players", slug=table.slug)

            # Add player
            Player.objects.create(table=table, user_profile=user_profile)

            # Create system comment
            Comment.objects.create(
                table=table,
                content=f"PLAYER_ADDED:{user_profile.nickname}",
                comment_type=CommentType.SYSTEM
            )

            messages.success(request, _(f"{user_profile.nickname} added to the table."))
        else:
            messages.error(request, _("Invalid selection."), extra_tags="danger")

        return redirect("table-players", slug=table.slug)


@login_required
def remove_player_view(request, slug, player_id):
    table = get_object_or_404(Table, slug=slug)
    player = get_object_or_404(Player, id=player_id, table=table)

    # Controllo permessi
    if not (request.user.is_superuser or table.author.user == request.user):
        messages.error(request, _("You don’t have permission to remove players from this table."), extra_tags="danger")
        return redirect("table-players", slug=slug)

    # Controllo stato tavolo — autore e admin possono sempre rimuovere
    if table.status not in [Table.OPEN, Table.ONGOING] and not (request.user.is_superuser or table.author.user == request.user):
        messages.error(request, _("You can remove players only from tables that are open or ongoing."), extra_tags="danger")
        return redirect("table-players", slug=slug)

    # Cascade-remove guests owned by this player
    if player.user_profile:
        guest_players = Player.objects.filter(
            table=table, guest_profile__owner=player.user_profile
        ).select_related('guest_profile')
        for gp in guest_players:
            Comment.objects.create(
                table=table,
                content=f"GUEST_REMOVED:{gp.guest_profile.name}",
                comment_type=CommentType.SYSTEM
            )
        guest_players.delete()

    nickname = player.user_profile.nickname if player.user_profile else player.display_name
    player.delete()

    # Create system comment
    Comment.objects.create(
        table=table,
        content=f"PLAYER_REMOVED:{nickname}",
        comment_type=CommentType.SYSTEM
    )

    messages.success(request, _(f"{nickname} has been removed from the table."))

    return redirect("table-players", slug=slug)


@login_required
def table_create_view(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    initial = {"location": location}

    if not (request.user.user_profile.is_email_verified or request.user.is_superuser):
        messages.error(request, MSG_VERIFY_EMAIL_BEFORE_PROCEEDING, extra_tags="danger")
        return redirect("location-detail", location_slug)

    user_profile = request.user.user_profile
    is_manager = location.creator == user_profile or user_profile in location.managers.all()
    if not is_manager and not request.user.is_superuser:
        perm = location.table_creation_permission
        if perm == location.PERM_MANAGERS_ONLY:
            messages.error(request, _("Only owners and managers can create tables here."), extra_tags="danger")
            return redirect("location-detail", location_slug)
        elif perm == location.PERM_MEMBERS_ONLY:
            from webapp.models import Membership
            is_member = Membership.objects.filter(
                member__location=location,
                member__user_profile=user_profile,
                status=Membership.ACTIVE,
            ).exists()
            if not is_member:
                messages.error(request, _("Only members can create tables here."), extra_tags="danger")
                return redirect("location-detail", location_slug)

    if request.method == "POST":
        form = TableForm(request.POST)
        if form.is_valid():
            table = form.save(commit=False)
            table.author = request.user.user_profile
            table.location = location
            table.save()
            form.save_m2m()

            if request.POST.get("join_table"):
                with transaction.atomic():
                    table.players.add(request.user.user_profile)

            messages.success(request, _("Table was created successfully"))
            return redirect(reverse("table-detail", kwargs={"slug": table.slug}))
    else:
        if date_param := request.GET.get('date'):
            initial['date'] = date_param
        form = TableForm(initial=initial)

    context = {"form": form, "location": location}

    return render(request, "tables/table_add_or_edit.html", context)


@login_required
@only_admin_can_edit_closed_table
@only_author_or_admin_can_edit
def table_update_view(request, location_slug, table_slug):
    table = get_object_or_404(Table, slug=table_slug)

    if table.location is None:  # Controllo di sicurezza per evitare problemi
        table.location = get_object_or_404(Location, slug=location_slug)
        table.save()

    location = table.location  # Ora la location è sempre valida

    if request.method == "POST":
        form = TableForm(request.POST, instance=table)
        if form.is_valid():
            table = form.save(commit=False)
            table.location = location  # Assegna manualmente la location
            table.save()
            form.save_m2m()  # Per salvare correttamente i giochi
            messages.success(request, _("Table was updated successfully"))
            return redirect(reverse("table-detail", kwargs={"slug": table.slug}))
    else:
        form = TableForm(instance=table)

    context = {"form": form, "location": location, "table": table}
    return render(request, "tables/table_add_or_edit.html", context)


@login_required
@author_or_admin_required
def add_external_player(request, slug, available_seats):
    table = get_object_or_404(Table, slug=slug)

    if request.method == "POST":
        if available_seats > 0:
            table.external_players += 1
            table.save()

    return redirect("table-players", slug=slug)


@login_required
@author_or_admin_required
def remove_external_player(request, slug):
    table = get_object_or_404(Table, slug=slug)

    if request.method == "POST":
        if table.external_players > 0:
            table.external_players -= 1
            table.save()

    return redirect("table-players", slug=slug)


@login_required
@author_or_admin_required
def clear_external_players(request, slug):
    table = get_object_or_404(Table, slug=slug)

    if request.method == "POST":
        if table.external_players > 0:
            table.external_players = 0
            table.save()

    return redirect("table-players", slug=slug)


class TableDeleteView(
    LoginRequiredMixin,
    IsAuthorOrAdminTestMixin,
    IsNotClosedMixin,
    SuccessMessageMixin,
    generic.DeleteView
):
    model = Table
    template_name = "tables/table_delete.html"

    slug_field = "slug"
    slug_url_kwarg = "slug"

    success_message = "Table was deleted successfully"

    def get_success_url(self):
        if self.object.event_id:
            return reverse('event_detail', kwargs={'slug': self.object.event.slug})
        return reverse('home')


class CommentDeleteView(LoginRequiredMixin, IsAuthorOrAdminTestMixin, SuccessMessageMixin, generic.DeleteView):
    model = Comment
    # template_name = 'comments/comment_delete.html'
    context_object_name = 'comment'
    success_message = "Comment was deleted successfully"

    def get_object(self, queryset=None):
        uuid = self.kwargs.get('uuid')
        return get_object_or_404(Comment, uuid=uuid)

    def get_success_url(self):
        table = self.get_object().table
        return reverse_lazy('table-detail', kwargs={'slug': table.slug})


class JoinTableView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        if not request.user.user_profile.is_email_verified:
            messages.error(request, 'Verify email to join table.', extra_tags='danger')
            return redirect('table-detail', slug=self.kwargs['slug'])

        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        if table.status == Table.CLOSED:
            messages.error(request, 'The table is closed. You cannot join.', extra_tags='danger')
            return redirect('table-detail', slug=self.kwargs['slug'])

        if table.location and table.location.table_join_permission == table.location.PERM_MEMBERS_ONLY:
            up = request.user.user_profile
            loc = table.location
            is_manager = loc.creator == up or up in loc.managers.all()
            if not is_manager and not request.user.is_superuser:
                from webapp.models import Membership
                is_member = Membership.objects.filter(
                    member__location=loc,
                    member__user_profile=up,
                    status=Membership.ACTIVE,
                ).exists()
                if not is_member:
                    messages.error(request, _('This table is reserved for members.'), extra_tags='danger')
                    return redirect('table-detail', slug=self.kwargs['slug'])

        Player.objects.create(
            user_profile=request.user.user_profile,
            table=table
        )

        # Create simple comment for player joining
        Comment.objects.create(
            table=table,
            content=f"PLAYER_IN:{request.user.user_profile.nickname}",
            comment_type=CommentType.SYSTEM
        )

        messages.success(request, 'Table joined!')
        return redirect('table-detail', slug=self.kwargs['slug'])


class LeaveTableView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        if table.status == Table.CLOSED:
            messages.error(request, 'The table is closed. You cannot leave.', extra_tags='danger')
            return redirect('table-detail', self.kwargs['slug'])

        try:
            player = get_object_or_404(Player, user_profile=request.user.user_profile, table=table)
            nickname = player.user_profile.nickname

            # Cascade-remove guests owned by this user at this table
            guest_players = Player.objects.filter(
                table=table, guest_profile__owner=request.user.user_profile
            ).select_related('guest_profile')
            for gp in guest_players:
                Comment.objects.create(
                    table=table,
                    content=f"GUEST_REMOVED:{gp.guest_profile.name}",
                    comment_type=CommentType.SYSTEM
                )
            guest_players.delete()

            # Create system comment for player leaving before deleting the player
            Comment.objects.create(
                table=table,
                content=f"PLAYER_OUT:{nickname}",
                comment_type=CommentType.SYSTEM
            )

            player.delete()

        except Player.DoesNotExist:
            pass

        return redirect('table-detail', slug=self.kwargs['slug'])


class AddGuestToTableView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        table = get_object_or_404(Table, slug=kwargs['slug'])

        if table.status != Table.OPEN:
            messages.error(request, _("The table is closed."), extra_tags='danger')
            return redirect('table-detail', slug=table.slug)

        # Only players at the table can add guests
        if not Player.objects.filter(table=table, user_profile=request.user.user_profile).exists():
            messages.error(request, _("Only table players can add guests."), extra_tags='danger')
            return redirect('table-detail', slug=table.slug)

        guest_id = request.POST.get('guest_id')
        guest = get_object_or_404(GuestProfile, id=guest_id, owner=request.user.user_profile)

        # Check not already at table
        if Player.objects.filter(table=table, guest_profile=guest).exists():
            messages.warning(request, _("This guest is already at the table."))
            return redirect('table-detail', slug=table.slug)

        # Check seats
        current_count = Player.objects.filter(table=table).count() + table.external_players
        if current_count >= table.max_players:
            messages.error(request, _("The table is full."), extra_tags='danger')
            return redirect('table-detail', slug=table.slug)

        Player.objects.create(table=table, guest_profile=guest)
        Comment.objects.create(
            table=table,
            content=f"GUEST_ADDED:{guest.name}",
            comment_type=CommentType.SYSTEM
        )
        return redirect('table-detail', slug=table.slug)


class RemoveGuestFromTableView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        table = get_object_or_404(Table, slug=kwargs['slug'])
        player = get_object_or_404(Player, id=kwargs['player_id'], table=table, guest_profile__isnull=False)

        # Permission: guest owner or table author
        if not (player.guest_profile.owner == request.user.user_profile or
                table.author == request.user.user_profile or
                request.user.is_superuser):
            messages.error(request, _("You don't have permission to remove this guest."), extra_tags='danger')
            return redirect('table-detail', slug=table.slug)

        name = player.guest_profile.name
        player.delete()
        Comment.objects.create(
            table=table,
            content=f"GUEST_REMOVED:{name}",
            comment_type=CommentType.SYSTEM
        )
        return redirect('table-detail', slug=table.slug)
