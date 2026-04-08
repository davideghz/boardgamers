from django.urls import path, include
from rest_framework.routers import DefaultRouter
from webapp.api.views import TableViewSet, bgg_search_view, bgg_search_external_view, bgg_import_view
from webapp.api.telegram_views import telegram_webhook, generate_setup_token

router = DefaultRouter()
router.register(r'tables', TableViewSet, basename='table')

urlpatterns = [
    path('', include(router.urls)),
    path('telegram/webhook/', telegram_webhook, name='telegram-webhook'),
    path('telegram/generate-token/<slug:slug>/', generate_setup_token, name='telegram-generate-token'),
    path('bgg/search/', bgg_search_view, name='bgg-search'),
    path('bgg/search/external/', bgg_search_external_view, name='bgg-search-external'),
    path('bgg/import/', bgg_import_view, name='bgg-import'),
]
