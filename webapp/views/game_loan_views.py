from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import formats, timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from django.views import View
from django.views.decorators.cache import never_cache

from webapp.forms import LocationGameLoanForm, LocationGameLoanSettingsForm
from webapp.models import Location, LocationGameLoan
from webapp.services.game_loans import (
    GameLoanError, check_game_loan_availability, create_game_loan, default_loan_due_date,
    get_borrowing_member, return_game_loan,
)


@method_decorator(never_cache, name='dispatch')
class LocationGameLoanManageView(LoginRequiredMixin, View):
    def render_page(self, request, location, form):
        statuses = {
            'open': pgettext_lazy('game loan filter', 'Open'),
            'overdue': pgettext_lazy('game loan filter', 'Overdue'),
            'returned': pgettext_lazy('game loan filter', 'Returned'),
            'all': pgettext_lazy('game loan filter', 'All'),
        }
        status = request.GET.get('status', 'open')
        if status not in statuses:
            status = 'open'

        loans = LocationGameLoan.objects.filter(location_game__location=location).select_related(
            'location_game__game', 'member', 'loaned_by', 'returned_by',
        )
        if status == 'overdue':
            loans = loans.filter(returned_at__isnull=True, due_date__lt=timezone.localdate())
        elif status in ('open', 'returned'):
            loans = loans.filter(returned_at__isnull=status == 'open')
        paginator = Paginator(loans, 25)
        page_obj = paginator.get_page(request.GET.get('page'))
        return render(request, 'locations/location_manage_game_loans.html', {
            'location': location,
            'form': form,
            'statuses': statuses,
            'status': status,
            'paginator': paginator,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
        })

    def get(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.is_manager(request.user.user_profile):
            raise PermissionDenied
        return self.render_page(request, location, LocationGameLoanSettingsForm(instance=location))

    def post(self, request, slug):
        location = get_object_or_404(Location, slug=slug)
        if not location.is_manager(request.user.user_profile):
            raise PermissionDenied
        form = LocationGameLoanSettingsForm(request.POST, instance=location)
        if form.is_valid():
            form.save(commit=False).save(update_fields=[*form.Meta.fields, 'updated_at'])
            messages.success(request, _('Game loan settings saved.'))
            return redirect('location-manage-game-loans', slug=slug)
        return self.render_page(request, location, form)


@method_decorator(never_cache, name='dispatch')
class LocationGameLoanCreateView(LoginRequiredMixin, View):
    def render_page(self, request, location_game, form):
        return render(request, 'locations/location_game_loan_checkout.html', {
            'location': location_game.location, 'location_game': location_game, 'form': form,
        })

    def dispatch(self, request, slug, game_uuid):
        if request.user.is_authenticated:
            self.location = get_object_or_404(Location, slug=slug)
            if not self.location.is_manager(request.user.user_profile):
                raise PermissionDenied
            self.location_game = get_object_or_404(self.location.location_games.select_related('game'), uuid=game_uuid)
        return super().dispatch(request, slug, game_uuid)

    def get(self, request, slug, game_uuid):
        try:
            check_game_loan_availability(self.location, self.location_game)
        except GameLoanError as exc:
            messages.warning(request, str(exc))
            return redirect('location-game-detail', slug=slug, game_uuid=game_uuid)
        return self.render_page(request, self.location_game, LocationGameLoanForm(location=self.location))

    def post(self, request, slug, game_uuid):
        form = LocationGameLoanForm(request.POST, location=self.location)
        if form.is_valid():
            try:
                create_game_loan(self.location, self.location_game, request.user.user_profile, **form.cleaned_data)
            except GameLoanError as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, _('Game loan recorded.'))
                return redirect('location-game-detail', slug=slug, game_uuid=game_uuid)
        return self.render_page(request, self.location_game, form)


@method_decorator(never_cache, name='dispatch')
class LocationGameLoanBorrowView(LoginRequiredMixin, View):
    def get(self, request, slug, game_uuid):
        location = get_object_or_404(Location, slug=slug)
        try:
            get_borrowing_member(location, getattr(request.user, 'user_profile', None))
            location_game = get_object_or_404(location.location_games.select_related('game'), uuid=game_uuid)
            check_game_loan_availability(location, location_game)
        except GameLoanError as exc:
            messages.warning(request, str(exc))
            return redirect('location-games', slug=slug)
        return render(request, 'locations/location_game_loan_checkout.html', {
            'location': location, 'location_game': location_game, 'due_date': default_loan_due_date(location),
        })

    def post(self, request, slug, game_uuid):
        location = get_object_or_404(Location, slug=slug)
        profile = getattr(request.user, 'user_profile', None)
        try:
            get_borrowing_member(location, profile)
            location_game = get_object_or_404(location.location_games, uuid=game_uuid)
            loan = create_game_loan(location, location_game, profile)
        except GameLoanError as exc:
            messages.warning(request, str(exc))
        else:
            messages.success(request, _('Game loan recorded. Return by %(date)s.') % {
                'date': formats.date_format(loan.due_date, 'DATE_FORMAT'),
            })
        return redirect('location-games', slug=slug)


class LocationGameLoanReturnView(LoginRequiredMixin, View):
    def post(self, request, slug, loan_uuid):
        location = get_object_or_404(Location, slug=slug)
        profile = request.user.user_profile
        if not location.is_manager(profile):
            raise PermissionDenied
        loan = get_object_or_404(LocationGameLoan, uuid=loan_uuid, location_game__location=location)
        if return_game_loan(location, loan, profile):
            messages.success(request, _('Game return recorded.'))
        else:
            messages.info(request, _('This game loan was already returned.'))
        return redirect('location-manage-game-loans', slug=slug)
