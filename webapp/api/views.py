from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils.timezone import now
from webapp.models import Table, Location
from webapp.api.serializers import TableSerializer


class TableViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Table.objects.all()
    serializer_class = TableSerializer

    @action(detail=False, methods=['get'], url_path='by-location/(?P<location_slug>[-\w]+)')
    def by_location(self, request, location_slug=None):
        location = get_object_or_404(Location, slug=location_slug)
        tables = Table.objects.filter(location=location).order_by('-date', '-time')
        serializer = self.get_serializer(tables, many=True)
        return Response(serializer.data)
