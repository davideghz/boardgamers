from django.contrib.gis.geos import Point
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Location, Game, Table


class LocationSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return Location.objects.filter(is_public=True).order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('location-detail', args=[obj.slug])


class GameSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return Game.objects.all().order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('game-detail', args=[obj.slug])


class TableSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.5

    def items(self):
        return Table.objects.all().order_by('-updated_at')

    def lastmod(self, obj):
        return obj.updated_at

    def location(self, obj):
        return reverse('location-table-detail', args=[obj.slug])
