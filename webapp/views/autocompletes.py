from dal import autocomplete

from webapp.models import State, Game, Location


class StateAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        # if not self.request.user.is_authenticated:
        #     return State.objects.none()

        qs = State.objects.all().order_by('name')

        if self.q:
            qs = qs.filter(name__istartswith=self.q)

        return qs


class LocationAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return Location.objects.none()

        qs = Location.objects.all().order_by('name')
        state_id = self.forwarded.get('state', None)
        if state_id:
            qs = qs.filter(state__id=state_id)
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
