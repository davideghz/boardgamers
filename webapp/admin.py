from django.contrib import admin
from webapp.models import UserProfile, Table, Comment, Player, Location, Game


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "slug", "user", "is_email_verified")


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0
    fields = ('user_profile', 'position', 'score')
    readonly_fields = ('user_profile',)


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("title", "location", "slug", "author")
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
    list_display = ("name", "leaderboard_enabled")
    list_editable = ("leaderboard_enabled",)
