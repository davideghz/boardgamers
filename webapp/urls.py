from django.contrib.sitemaps.views import sitemap
from django.urls import path, include

from .forms import CustomLoginForm
from .sitemaps import LocationSitemap, GameSitemap, TableSitemap, StaticViewSitemap
from .views import table_views, auth_views, location_views, game_views, static_page_views, profile_views, account_views
from .views.table_views import AddGuestToTableView, RemoveGuestFromTableView
from .views.autocompletes import GamesAutocomplete, LocationAutocomplete, UserProfileAutocomplete, MemberAutocomplete
from .views.location_views import FollowLocationView

sitemaps = {
    'static': StaticViewSitemap,
    'locations': LocationSitemap,
    'games': GameSitemap,
    'tables': TableSitemap,
}
urlpatterns = [
    # API
    # path('api/', include('webapp.api.urls')),  # Include le API

    # STATIC
    path("", static_page_views.homepage_view, name="home"),
    path("privacy", static_page_views.privacy, name="privacy"),
    path("terms", static_page_views.terms, name="terms"),
    path("contacts", static_page_views.contacts, name="contacts"),
    path("about", static_page_views.about, name="about"),
    path("select-language", static_page_views.select_language, name="select-language"),

    # TABLE
    path("tables/", table_views.TableIndexView.as_view(), name="table-index"),
    path("tables/<slug:slug>/", table_views.TableDetailView.as_view(), name="table-detail"),
    path("tables/<slug:slug>/delete/", table_views.TableDeleteView.as_view(), name="table-delete"),
    path('tables/<slug:slug>/join/', table_views.JoinTableView.as_view(), name='join_table'),
    path('tables/<slug:slug>/leave/', table_views.LeaveTableView.as_view(), name='leave_table'),
    path('comments/<uuid:uuid>/delete/', table_views.CommentDeleteView.as_view(), name='comment-delete'),
    path("tables/<slug:slug>/players/", table_views.table_players_view, name="table-players"),
    path("tables/<slug:slug>/players/remove/<int:player_id>/", table_views.remove_player_view, name="remove-player"),
    path("tables/<slug:slug>/add_external/<int:available_seats>/", table_views.add_external_player,
         name="add_external_player"),
    path("tables/<slug:slug>/players/add/", table_views.AddTablePlayerView.as_view(), name="table-add-player"),
    path("tables/<slug:slug>/remove_external/", table_views.remove_external_player, name="remove_external_player"),
    path("tables/<slug:slug>/clear_external/", table_views.clear_external_players, name="clear_external_players"),

    # TABLE GUESTS
    path('tables/<slug:slug>/guests/add/', AddGuestToTableView.as_view(), name='table-add-guest'),
    path('tables/<slug:slug>/guests/remove/<int:player_id>/', RemoveGuestFromTableView.as_view(), name='table-remove-guest'),

    # LOCATIONS
    path("locations/", location_views.index_view, name="locations-index"),
    path("locations/<slug:slug>/", location_views.LocationDetailView.as_view(), name="location-detail"),
    path("locations/new", location_views.LocationCreateView.as_view(), name="location-create"),
    path('locations/<slug:slug>/follow/', FollowLocationView.as_view(), name='follow-location'),

    # LOCATION MANAGEMENT
    path("locations/<slug:slug>/manage/", location_views.LocationManageIndexView.as_view(), name="location-manage"),
    path("locations/<slug:slug>/manage/data/", location_views.LocationManageDataView.as_view(),
         name="location-manage-data"),
    path("locations/<slug:slug>/manage/managers/", location_views.LocationManageManagersView.as_view(),
         name="location-manage-managers"),
    path("locations/<slug:slug>/manage/managers/add/", location_views.AddLocationManagerView.as_view(),
         name="location-add-manager"),
    path("locations/<slug:slug>/manage/managers/remove/<int:manager_id>/",
         location_views.RemoveLocationManagerView.as_view(), name="location-remove-manager"),
    path("locations/<slug:slug>/manage/managers/transfer-ownership/", location_views.TransferOwnershipView.as_view(),
         name="location-transfer-ownership"),

    # LOCATION MEMBERS
    path("locations/<slug:slug>/manage/members/", location_views.LocationManageMembersView.as_view(),
         name="location-manage-members"),
    path("locations/<slug:slug>/manage/members/csv/", location_views.DownloadMembersCSVView.as_view(),
         name="location-members-csv"),
    path("locations/<slug:slug>/manage/members/add/", location_views.AddMemberView.as_view(),
         name="location-add-member"),
    path("locations/<slug:slug>/manage/members/<uuid:member_uuid>/", location_views.MemberDetailEditView.as_view(),
         name="location-member-detail"),
    path("locations/<slug:slug>/manage/members/<uuid:member_uuid>/approve/",
         location_views.ApproveMembershipView.as_view(), name="location-approve-membership"),
    path("locations/<slug:slug>/manage/members/<uuid:member_uuid>/memberships/add/",
         location_views.AddMembershipView.as_view(), name="location-add-membership"),
    path("locations/<slug:slug>/manage/members/<uuid:member_uuid>/memberships/<uuid:membership_uuid>/delete/",
         location_views.DeleteMembershipView.as_view(), name="location-delete-membership"),
    path("locations/<slug:slug>/manage/members/<uuid:member_uuid>/memberships/<uuid:membership_uuid>/",
         location_views.EditMembershipView.as_view(), name="location-edit-membership"),
    path("locations/<slug:slug>/request-membership/", location_views.RequestMembershipView.as_view(),
         name="location-request-membership"),

    # LOCATION TELEGRAM
    path("locations/<slug:slug>/manage/telegram/", location_views.LocationManageTelegramView.as_view(),
         name="location-manage-telegram"),

    # LOCATION GAMES
    path("locations/<slug:slug>/manage/widget/", location_views.LocationManageWidgetView.as_view(),
         name="location-manage-widget"),
    path("locations/<slug:slug>/manage/games/", location_views.LocationManageGamesView.as_view(),
         name="location-manage-games"),
    path("locations/<slug:slug>/manage/games/csv/", location_views.DownloadGamesCSVView.as_view(),
         name="location-games-csv"),
    path("locations/<slug:slug>/manage/games/add/", location_views.AddLocationGameView.as_view(),
         name="location-add-game"),
    path("locations/<slug:slug>/manage/games/<uuid:game_uuid>/", location_views.LocationGameDetailView.as_view(),
         name="location-game-detail"),
    path("locations/<slug:slug>/manage/games/<uuid:game_uuid>/delete/", location_views.DeleteLocationGameView.as_view(),
         name="location-delete-game"),

    # LOCATION TABLES
    path("location/<slug:location_slug>/tables/new/", table_views.table_create_view, name="location-table-create"),
    path("location/<slug:location_slug>/tables/<slug:table_slug>/edit/", table_views.table_update_view,
         name="location-table-update"),

    # GAMES
    path("games/", game_views.GameListView.as_view(), name="game-list"),
    path("games/<slug:slug>/", game_views.GameDetailView.as_view(), name="game-detail"),

    # ACCOUNT
    path("account/", account_views.index, name="account-index"),
    path("account/edit-profile/", profile_views.UserProfileUpdateView.as_view(), name='user-profile-edit'),
    path("account/change-email/", profile_views.change_email, name='change-email'),
    path("account/locations/", account_views.locations, name="account-locations"),
    path("account/tables/", account_views.tables, name="account-tables"),
    path("account/notifications/", account_views.notifications, name="account-notifications"),
    path("account/notifications/edit", account_views.edit_notification_preferences, name="account-notifications-edit"),
    path("account/memberships/", account_views.memberships, name="account-memberships"),
    path("account/guests/", account_views.guests, name="account-guests"),
    path("account/guests/create/", account_views.create_guest, name="account-guest-create"),
    path("account/guests/<int:guest_id>/delete/", account_views.delete_guest, name="account-guest-delete"),

    # USER PROFILES
    path('users/<str:slug>/', profile_views.UserProfileDetailView.as_view(), name='user-profile-detail'),
    path('users/upload/avatar/', profile_views.upload_avatar, name='upload-avatar'),

    # AUTOCOMPLETES
    path('location-autocomplete/', LocationAutocomplete.as_view(), name='location-autocomplete'),
    path('games-autocomplete/', GamesAutocomplete.as_view(), name='games-autocomplete'),
    path('userprofile-autocomplete/', UserProfileAutocomplete.as_view(), name='userprofile-autocomplete'),
    path('member-autocomplete/<slug:location_slug>/', MemberAutocomplete.as_view(), name='member-autocomplete'),

    # AUTH
    path('accounts/login/', auth_views.CustomLoginView.as_view(authentication_form=CustomLoginForm), name='login'),
    path('accounts/signup/', auth_views.SignupView.as_view(), name='signup'),
    path('accounts/logout/', auth_views.CustomLogoutView.as_view(), name='logout'),
    path('accounts/password_change/', auth_views.CustomPasswordChangeView.as_view(), name='password_change'),
    path('accounts/password_change/done/', auth_views.CustomPasswordChangeDoneView.as_view(),
         name='password_change_done'),
    path('accounts/password_reset/', auth_views.CustomPasswordResetView.as_view(), name='custom_password_reset'),
    path('accounts/password_reset/done/', auth_views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth_views.CustomPasswordResetConfirmView.as_view(),
         name='password_reset_confirm'),
    path('accounts/reset/done/', auth_views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
    path('accounts/email/verify/<uidb64>/<token>/', auth_views.VerifyEmailView.as_view(), name='email_verify'),
    path('accounts/email/verify/', auth_views.send_email_verification_code, name='send_email_verification_code'),

    # SITEMAP
    path('sitemap.xml', sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"),

    # DEBUGGING UTILS
    path('debug', static_page_views.debug, name='debug'),
    path('test-widget', static_page_views.test_widget, name='test_widget'),

]
