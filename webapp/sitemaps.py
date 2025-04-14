from django.contrib.gis.geos import Point
from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from .models import Location, Game, Table


class StaticViewSitemap(Sitemap):
    def items(self):
        return ['home', 'locations-index', 'privacy', 'terms', 'contacts']

    def changefreq(self, item):
        if item == 'home':
            return 'daily'
        if item == 'locations-index':
            return 'weekly'
        return 'never'

    def priority(self, item):
        if item == 'home':
            return 0.8
        if item == 'locations-index':
            return 0.5
        return 0.3

    def location(self, item):
        return reverse(item)

    def lastmod(self, item):
        if item == 'home':
            last_table = Table.objects.order_by('-updated_at').first()
            return last_table.updated_at if last_table else None
        if item == 'locations-index':
            last_location = Location.objects.order_by('-created_at').first()
            return last_location.created_at if last_location else None
        return None


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
    changefreq = "monthly"
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
        return reverse('location-detail', args=[obj.slug])
