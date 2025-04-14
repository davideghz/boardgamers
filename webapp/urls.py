from django.contrib.sitemaps.views import sitemap
from django.urls import path, include

from .forms import CustomLoginForm
from .sitemaps import LocationSitemap, GameSitemap, TableSitemap, StaticViewSitemap
from .views import table_views, auth_views, location_views, game_views, static_page_views, profile_views, account_views
from .views.autocompletes import GamesAutocomplete, LocationAutocomplete
from .views.location_views import FollowLocationView

sitemaps = {
  'static': StaticViewSitemap,
  'locations': LocationSitemap,
  'games': GameSitemap,
  'tables': TableSitemap,
}
urlpatterns = [
  # API
  path('api/', include('webapp.api.urls')),  # Include le API

  # STATIC
  path("", static_page_views.homepage_view, name="home"),
  path("privacy", static_page_views.privacy, name="privacy"),
  path("terms", static_page_views.terms, name="terms"),
  path("contacts", static_page_views.contacts, name="contacts"),

  # TABLE
  path("tables/", table_views.TableIndexView.as_view(), name="table-index"),
  path("tables/<slug:slug>/", table_views.TableDetailView.as_view(), name="table-detail"),
  path("tables/<slug:slug>/delete/", table_views.TableDeleteView.as_view(), name="table-delete"),
  path('tables/<slug:slug>/join/', table_views.JoinTableView.as_view(), name='join_table'),
  path('tables/<slug:slug>/leave/', table_views.LeaveTableView.as_view(), name='leave_table'),
  path('comments/<uuid:uuid>/delete/', table_views.CommentDeleteView.as_view(), name='comment-delete'),

  # LOCATIONS
  path("locations/", location_views.index_view, name="locations-index"),
  path("locations/new", location_views.LocationCreateView.as_view(), name="location-create"),
  path("locations/<slug:slug>/edit/", location_views.LocationUpdateView.as_view(), name="location-update"),
  path("locations/<slug:slug>/", location_views.LocationDetailView.as_view(), name="location-detail"),

  # LOCATION TABLES
  path("location/<slug:location_slug>/tables/new/", table_views.table_create_view, name="location-table-create"),
  path("location/<slug:location_slug>/tables/<slug:table_slug>/edit/", table_views.table_update_view, name="location-table-update"),
  path('locations/<slug:slug>/follow/', FollowLocationView.as_view(), name='follow-location'),


  # GAMES
  path("games/", game_views.GameListView.as_view(), name="game-list"),
  path("games/<slug:slug>/", game_views.GameDetailView.as_view(), name="game-detail"),

  # ACCOUNT
  path("account/", account_views.index, name="account-index"),
  path("account/edit-profile/", profile_views.UserProfileUpdateView.as_view(), name='user-profile-edit'),
  path("account/locations/", account_views.locations, name="account-locations"),
  path("account/tables/", account_views.tables, name="account-tables"),
  path("account/notifications/", account_views.notifications, name="account-notifications"),
  path("account/notifications/edit", account_views.edit_notification_preferences, name="account-notifications-edit"),

  # USER PROFILES
  path('users/<str:slug>/', profile_views.UserProfileDetailView.as_view(), name='user-profile-detail'),
  path('users/upload/avatar/', profile_views.upload_avatar, name='upload-avatar'),

  # AUTOCOMPLETES
  path('location-autocomplete/', LocationAutocomplete.as_view(), name='location-autocomplete'),
  path('games-autocomplete/', GamesAutocomplete.as_view(), name='games-autocomplete'),

  # AUTH
  path('accounts/login/', auth_views.CustomLoginView.as_view(authentication_form=CustomLoginForm), name='login'),
  path('accounts/signup/', auth_views.SignupView.as_view(), name='signup'),
  path('accounts/logout/', auth_views.CustomLogoutView.as_view(), name='logout'),
  path('accounts/password_change/', auth_views.CustomPasswordChangeView.as_view(), name='password_change'),
  path('accounts/password_change/done/', auth_views.CustomPasswordChangeDoneView.as_view(), name='password_change_done'),
  path('accounts/password_reset/', auth_views.CustomPasswordResetView.as_view(), name='custom_password_reset'),
  path('accounts/password_reset/done/', auth_views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
  path('accounts/reset/<uidb64>/<token>/', auth_views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
  path('accounts/reset/done/', auth_views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
  path('accounts/email/verify/<uidb64>/<token>/', auth_views.VerifyEmailView.as_view(), name='email_verify'),
  path('accounts/email/verify/', auth_views.send_email_verification_code, name='send_email_verification_code'),

  # SITEMAP
  path('sitemap.xml', sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),

  # DEBUGGING UTILS
  path('debug', static_page_views.debug, name='debug')
]

