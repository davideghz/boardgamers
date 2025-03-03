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
from django.views import generic
from django.utils.translation import gettext_lazy as _

from webapp.forms import TableForm, CustomLoginForm, CommentForm, JoinTableForm
from webapp.messages import MSG_VERIFY_EMAIL_BEFORE_PROCEEDING
from webapp.models import Table, Comment, Player, UserProfile, Game, Location


class IsAuthorOrAdminTestMixin(UserPassesTestMixin):
    def test_func(self):
        obj = self.get_object()
        return obj.author.user == self.request.user or self.request.user.is_staff


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
        games_prefetch = Prefetch('games', queryset=Game.objects.all())

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


class TableDetailView(LoginRequiredMixin, generic.DetailView):
    model = Table
    template_name = "tables/table_detail.html"

    def get_queryset(self):
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        return super().get_queryset().prefetch_related(comments_prefetch)

    def get_context_data(self, **kwargs):
        table = self.get_object()
        max_players = table.max_players
        current_players = table.players.count()

        context = super().get_context_data(**kwargs)
        context['comment_form'] = CommentForm()
        context['available_seats'] = max_players - current_players
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.table = self.object
            comment.author = request.user.user_profile
            comment.save()
            return redirect('table-detail', slug=self.object.slug)
        context = self.get_context_data(object=self.object, comment_form=form)
        return self.render_to_response(context)


@login_required
def table_create_view(request, location_slug):
    location = get_object_or_404(Location, slug=location_slug)
    initial = {"location": location}

    if not (request.user.user_profile.is_email_verified or request.user.is_staff):
        messages.error(request, MSG_VERIFY_EMAIL_BEFORE_PROCEEDING)
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
def table_update_view(request, location_slug, table_slug):
    table = get_object_or_404(Table, slug=table_slug)

    if table.location is None:  # Controllo di sicurezza per evitare problemi
        table.location = get_object_or_404(Location, slug=location_slug)
        table.save()

    location = table.location  # Ora la location è sempre valida

    if not (request.user == table.author.user or request.user.is_staff):
        messages.error(request, _("You don't have permission to edit this table."))
        return redirect("table-detail", slug=table_slug)

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


class JoinTableView(LoginRequiredMixin, SuccessMessageMixin, generic.CreateView):
    model = Player
    form_class = JoinTableForm
    success_message = "Table joined!"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.user_profile.is_email_verified:
            messages.error(request, 'Verify email to join table.', extra_tags='danger')
            return redirect('table-detail', self.kwargs['slug'])

        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        # Redirect to table detail page using slug
        return reverse_lazy('table-detail', kwargs={'slug': self.kwargs['slug']})

    def form_valid(self, form):
        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        form.instance.user_profile = self.request.user.user_profile
        form.instance.table = table
        return super().form_valid(form)


class LeaveTableView(LoginRequiredMixin, generic.DeleteView):
    model = Player

    def get_success_url(self):
        return reverse_lazy('table-detail', kwargs={'slug': self.kwargs['slug']})

    def get_object(self):
        table = get_object_or_404(Table, slug=self.kwargs['slug'])
        user_profile = self.request.user.user_profile
        return get_object_or_404(Player, user_profile=user_profile, table=table)
