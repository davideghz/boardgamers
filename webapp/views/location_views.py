from django.views.generic import DetailView

from webapp.models import Location, Table


class LocationDetailView(DetailView):
    model = Location
    template_name = 'locations/location_detail.html'  # Assicurati di creare questo template
    slug_field = 'slug'  # Specifica che userai il campo 'slug' per la ricerca
    slug_url_kwarg = 'slug'  # Il nome del parametro keyword nell'URL che contiene lo slug

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        location = self.get_object()
        context['tables'] = Table.objects.filter(location=location).order_by('-date', '-time')
        return context
