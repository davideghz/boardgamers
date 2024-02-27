from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse
from django.views import generic
from django.views.generic import DetailView, CreateView

from webapp.forms import LocationForm
from webapp.models import Location, Table, UserProfile


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


class LocationCreateView(SuccessMessageMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was created successfully"

    def form_valid(self, form):
        location = form.save(commit=False)
        creator = self.request.user.user_profile
        location.creator = creator
        location.save()
        return super(LocationCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("account-locations")


class LocationUpdateView(SuccessMessageMixin, generic.UpdateView):
    model = Location
    form_class = LocationForm
    template_name = 'locations/location_add_or_edit.html'
    success_message = "Location was updated successfully"

    def form_valid(self, form):
        location = form.save(commit=False)
        creator = self.request.user.user_profile
        location.creator = creator
        location.save()
        return super(LocationUpdateView, self).form_valid(form)

    def get_success_url(self):
        return reverse("account-locations")
