from dal import autocomplete
from django.db.models import Q, Case, When, Value, IntegerField
from django.db.models.functions import Lower

from webapp.models import Game, Location


class LocationAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return Location.objects.none()

        qs = Location.objects.annotate(
            is_user_location=Case(
                When(creator=self.request.user.user_profile, then=Value(1)),
                When(is_public=True, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by('is_user_location', Lower('name'))

        if self.q:
            qs = qs.filter(name__istartswith=self.q)
        return qs


class GamesAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return Game.objects.none()

        qs = Game.objects.all()
        if self.q:
            qs = qs.filter(name__istartswith=self.q)
        return qs
