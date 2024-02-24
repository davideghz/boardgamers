from django.urls import path

from .forms import CustomLoginForm
from .views import table_views, auth_views, location_views, game_views, static_page_views, profile_views
from .views.autocompletes import GamesAutocomplete, LocationAutocomplete

urlpatterns = [
  # STATIC
  path("", static_page_views.HomepageView.as_view(), name="home"),

  # TABLE
  path("tables/", table_views.TableIndexView.as_view(), name="table-index"),
  path("tables/<slug:slug>/", table_views.TableDetailView.as_view(), name="table-detail"),
  path("tables/new", table_views.TableCreateView.as_view(), name="table-create"),
  path("tables/<slug:slug>/edit", table_views.TableUpdateView.as_view(), name="table-update"),
  path("tables/<slug:slug>/delete", table_views.TableDeleteView.as_view(), name="table-delete"),
  path('tables/<slug:slug>/join', table_views.JoinTableView.as_view(), name='join_table'),
  path('tables/<slug:slug>/leave', table_views.LeaveTableView.as_view(), name='leave_table'),
  path('comments/<uuid:uuid>/delete', table_views.CommentDeleteView.as_view(), name='comment-delete'),

  # LOCATIONS
  path("locations/new", location_views.LocationCreateView.as_view(), name="location-create"),
  path("locations/<slug:slug>/edit", location_views.LocationUpdateView.as_view(), name="location-create"),
  path("locations/<slug:slug>/", location_views.LocationDetailView.as_view(), name="location-detail"),

  # GAMES
  path("games/<slug:slug>/", game_views.GameDetailView.as_view(), name="game-detail"),

  # USER PROFILES
  path('users/<str:username>/', profile_views.UserProfileDetailView.as_view(), name='user-profile-detail'),
  path('users/<str:username>/edit', profile_views.UserProfileUpdateView.as_view(), name='user-profile-edit'),
  path('users/upload-avatar/', profile_views.upload_avatar, name='upload-avatar'),

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

]
