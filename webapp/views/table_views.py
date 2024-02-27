from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import generic
from django.utils.translation import gettext_lazy as _

from webapp.forms import TableForm, CustomLoginForm, CommentForm, JoinTableForm
from webapp.models import Table, Comment, Player, UserProfile, Game


class IsAuthorOrAdminTestMixin(UserPassesTestMixin):
    def test_func(self):
        obj = self.get_object()
        return obj.author.user == self.request.user or self.request.user.is_staff


class TableIndexView(generic.ListView):
    template_name = "tables/table_index.html"
    context_object_name = "tables"

    def get_queryset(self):
        comments_prefetch = Prefetch('comments', queryset=Comment.objects.select_related('author', 'author__user'))
        players_prefetch = Prefetch('players', queryset=UserProfile.objects.select_related('user'))
        games_prefetch = Prefetch('games', queryset=Game.objects.all())
        return Table.objects.select_related('author', 'author__user', 'location').prefetch_related(
            comments_prefetch,
            players_prefetch,
            games_prefetch,
        ).all().order_by('date')

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


class TableCreateView(LoginRequiredMixin, SuccessMessageMixin, generic.CreateView):
    model = Table
    form_class = TableForm
    template_name = "tables/table_add_or_edit.html"
    success_message = _("Table was created successfully")

    def form_valid(self, form):
        form.instance.author = self.request.user.user_profile
        response = super(TableCreateView, self).form_valid(form)
        with transaction.atomic():
            self.object.players.add(self.request.user.user_profile)
        return response

    def get_success_url(self):
        table_slug = self.object.slug
        return reverse("table-detail", kwargs={"slug": table_slug})


class TableUpdateView(LoginRequiredMixin, IsAuthorOrAdminTestMixin, SuccessMessageMixin, generic.UpdateView):
    model = Table
    form_class = TableForm
    template_name = "tables/table_add_or_edit.html"
    success_message = _("Table was updated successfully")

    def get_success_url(self):
        table_slug = self.object.slug
        return reverse("table-detail", kwargs={"slug": table_slug})


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
