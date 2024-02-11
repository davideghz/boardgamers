from django.contrib import admin
from webapp.models import UserProfile, Table, Comment, State, Player, Location, Game


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    pass


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "author")

    def save_model(self, request, obj, form, change):
        if not obj.slug:
            obj.slug = obj.create_unique_slug()
        super().save_model(request, obj, form, change)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("uuid", "table", "author", "content")


@admin.register(State)
class StateAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ["name"]}


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    pass


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    pass


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    pass
