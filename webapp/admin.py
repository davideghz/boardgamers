from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from webapp.models import UserProfile, Table, Comment, Player, Location, Game, LocationFollower, Notification


@admin.register(UserAdmin)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'date_joined', 'is_staff')
    ordering = ('-date_joined',)  # opzionale: ordina per data


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "created_at", "user", "is_email_verified")


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0
    fields = ('user_profile', 'position', 'score')
    readonly_fields = ('user_profile',)


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("title", "location", "author", "date", "time", "status", "leaderboard_status")
    inlines = [PlayerInline]

    def save_model(self, request, obj, form, change):
        if not obj.slug:
            obj.slug = obj.create_unique_slug()
        super().save_model(request, obj, form, change)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("uuid", "table", "author", "content")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("user_profile", "table", "position", "score")
    list_filter = ("user_profile", "table", "score", "position")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    pass


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("name", "leaderboard_enabled", "created_at")
    list_editable = ("leaderboard_enabled",)


@admin.register(LocationFollower)
class LocationFollowerAdmin(admin.ModelAdmin):
    pass


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'table', 'location', 'is_read', 'sent')
    list_editable = ('is_read', 'sent',)

