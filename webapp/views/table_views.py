from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.gis.measure import Distance
from django.contrib.gis.db.models.functions import Distance as DbDistance
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.timezone import now
from django.views import generic, View
from django.utils.translation import gettext_lazy as _

from webapp.forms import TableForm, CustomLoginForm, CommentForm, JoinTableForm, PlayerScoreFormSet
from webapp.messages import MSG_VERIFY_EMAIL_BEFORE_PROCEEDING
from webapp.models import Table, Comment, Player, UserProfile, Game, Location
from webapp.views.decorators import only_author_or_admin_can_edit, only_admin_can_edit_closed_table


class IsAuthorOrAdminTestMixin(UserPassesTestMixin):
    def test_func(self):
        obj = self.get_object()
        return obj.author.user == self.request.user or self.request.user.is_superuser


class TableIndexView(generic.ListView):
    template_name = "tables/table_index.html"
    context_object_name = "tables"

    def get_queryset(self):
        g = GeoIP2()

        x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            user_ip = x_forwarded_for.split(',')[0]
        else:
            user_ip = self.request.META.get('REMOTE_ADDR')

        if user_ip == '127.0.0.1':
            user_ip = '93.66.88.167'

        city = g.city(user_ip)
        user_point = g.geos(user_ip)

        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('players', queryset=UserProfile.objects.select_related('user'))
        games_prefetch = Prefetch('game', queryset=Game.objects.all())

        tables = Table.objects \
            .select_related('author', 'author__user', 'location') \
            .prefetch_related(comments_prefetch, players_prefetch, games_prefetch) \
            .filter(location__point__distance_lt=(user_point, Distance(m=122222255000))) \
            .annotate(distance=DbDistance('location__point', user_point)) \
            .order_by('distance', 'date')

        return tables

    def get_context_data(self, **kwargs):
        context = super(TableIndexView, self).get_context_data(**kwargs)
        context['login_form'] = CustomLoginForm()
        return context


class TableDetailView(generic.DetailView):
    model = Table
    template_name = "tables/table_detail.html"

    def get_queryset(self):
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        return super().get_queryset().prefetch_related(comments_prefetch)

    def get_context_data(self, **kwargs):
        table = self.get_object()
        max_players = table.max_players
        current_players = table.players.count()
        today = now().date()

        # Recupero i giocatori ordinati per punteggio
        players = Player.objects.filter(table=table).select_related('user_profile').order_by('position')

        # Controlla se il gioco associato alla tabella ha la leaderboard abilitata
        leaderboard_enabled = table.game and table.game.leaderboard_enabled

        # Verifica se almeno un giocatore ha una posizione diversa da 99
        leaderboard_visible = any(player.position != 99 for player in players)

        # Verifica se utente può modificare leaderboard
        user_can_edit_leaderboard = (
            (leaderboard_enabled and
             ((table.leaderboard_status == table.LEADERBOARD_EDITABLE) and
              self.request.user.user_profile in table.players.all()) or
             self.request.user.is_superuser)
        )

        # Controlliamo se l'utente è un player del tavolo o un admin
        # can_edit_scores = self.request.user.is_superuser or self.request.user.user_profile in table.players.all()

        # Creiamo un formset per tutti i player della partita
        # formset = PlayerScoreFormSet(queryset=players)

        # if not can_edit_scores:
        #     for form in formset.forms:
        #         form.fields['score'].widget.attrs['readonly'] = True  # Rende il campo in sola lettura

        # Zip per creare la lista di tuple (form, player)
        # players_with_forms = list(zip(formset.forms, players))

        context = super().get_context_data(**kwargs)
        context.update({
            'comment_form': CommentForm(),
            'available_seats': max_players - current_players,
            'today': today,
            'players': players,
            'leaderboard_enabled': leaderboard_enabled,
            'leaderboard_visible': leaderboard_visible,
            'user_can_edit_leaderboard': user_can_edit_leaderboard
            # 'players_with_forms': players_with_forms,
            # 'formset': formset,
            # 'can_edit_scores': can_edit_scores
        })
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # Recupera il tavolo
        formset = None  # Inizializza il formset per evitare errori

        # Gestione dei commenti
        if 'comment_form' in request.POST:
            form = CommentForm(request.POST)
            if form.is_valid():
                comment = form.save(commit=False)
                comment.table = self.object
                comment.author = request.user.user_profile
                comment.save()
                return redirect('table-detail', slug=self.object.slug)

        # Gestione aggiornamento punteggi
        # elif 'score_form' in request.POST:
        #     # Verifica se l'utente è un player del tavolo o un admin
        #     if not request.user.is_superuser and request.user.user_profile not in self.object.players.all():
        #         return redirect('table-detail', slug=self.object.slug)  # Blocca il salvataggio
        #
        #     # Se l'utente ha i permessi, processa il formset
        #     formset = PlayerScoreFormSet(
        #         request.POST,
        #         queryset=Player.objects.filter(table=self.object)
        #     )
        #     if formset.is_valid():
        #         formset.save()
        #         return redirect('table-detail', slug=self.object.slug)

        context = self.get_context_data(object=self.object, formset=formset)
        return self.render_to_response(context)


@login_required
def table_create_view(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    initial = {"location": location}

    if not (request.user.user_profile.is_email_verified or request.user.is_superuser):
        messages.error(request, MSG_VERIFY_EMAIL_BEFORE_PROCEEDING, extra_tags="danger")
        return redirect("location-detail", location_slug)

    if request.method == "POST":
        form = TableForm(request.POST)
        if form.is_valid():
            table = form.save(commit=False)
            table.author = request.user.user_profile
            table.location = location
            table.save()
            form.save_m2m()

            with transaction.atomic():
                table.players.add(request.user.user_profile)

            messages.success(request, _("Table was created successfully"))
            return redirect(reverse("table-detail", kwargs={"slug": table.slug}))
    else:
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


class TableDeleteView(LoginRequiredMixin, IsAuthorOrAdminTestMixin, SuccessMessageMixin, generic.DeleteView):
    model = Table
    template_name = "tables/table_delete.html"
    success_message = "Table was deleted successfully"
    success_url_name = 'table-index'


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

        Player.objects.create(
            user_profile=request.user.user_profile,
            table=table
        )

        messages.success(request, 'Table joined!')
        return redirect('table-detail', slug=self.kwargs['slug'])


class LeaveTableView(LoginRequiredMixin, generic.DeleteView):
    model = Player

    def dispatch(self, request, *args, **kwargs):
        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        if table.status == Table.CLOSED:
            messages.error(request, 'The table is closed. You cannot leave.', extra_tags='danger')
            return redirect('table-detail', self.kwargs['slug'])

        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy('table-detail', kwargs={'slug': self.kwargs['slug']})

    def get_object(self):
        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        user_profile = self.request.user.user_profile
        return get_object_or_404(Player, user_profile=user_profile, table=table)
