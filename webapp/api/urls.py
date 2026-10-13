from django.urls import path, re_path
from webapp.api.views import tables_by_location_view, bgg_search_view, bgg_search_external_view, bgg_import_view
from webapp.views.pwa_views import push_subscribe
from webapp.api.search_views import user_search_view, location_search_view, member_search_view
from webapp.api.telegram_views import telegram_webhook, generate_setup_token
from webapp.api.telegram_app_api import (
    bootstrap as telegram_miniapp_bootstrap,
    detail as telegram_miniapp_detail,
    guest_add as telegram_miniapp_guest_add,
    guest_remove as telegram_miniapp_guest_remove,
    join as telegram_miniapp_join,
    leave as telegram_miniapp_leave,
)

urlpatterns = [
    re_path(r'^tables/by-location/(?P<location_slugs>[\w,-]+)/$', tables_by_location_view,
            name='tables-by-location'),
    path('telegram/webhook/', telegram_webhook, name='telegram-webhook'),
    path('telegram/generate-token/<slug:slug>/', generate_setup_token, name='telegram-generate-token'),
    path('telegram/app/bootstrap/', telegram_miniapp_bootstrap, name='telegram-miniapp-bootstrap'),
    path('telegram/app/tables/<slug:slug>/join/', telegram_miniapp_join, name='telegram-miniapp-join'),
    path('telegram/app/tables/<slug:slug>/leave/', telegram_miniapp_leave, name='telegram-miniapp-leave'),
    path('telegram/app/tables/<slug:slug>/', telegram_miniapp_detail, name='telegram-miniapp-detail'),
    path('telegram/app/tables/<slug:slug>/guests/add/', telegram_miniapp_guest_add, name='telegram-miniapp-guest-add'),
    path('telegram/app/tables/<slug:slug>/guests/<int:player_id>/remove/', telegram_miniapp_guest_remove, name='telegram-miniapp-guest-remove'),
    path('bgg/search/', bgg_search_view, name='bgg-search'),
    path('bgg/search/external/', bgg_search_external_view, name='bgg-search-external'),
    path('bgg/import/', bgg_import_view, name='bgg-import'),
    path('users/search/', user_search_view, name='user-search'),
    path('locations/search/', location_search_view, name='location-search'),
    path('locations/<slug:slug>/members/search/', member_search_view, name='member-search'),
    path('push/subscribe/', push_subscribe, name='push-subscribe'),
]
