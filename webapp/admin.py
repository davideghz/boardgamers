from django.contrib import admin, messages
from django.contrib.admin.widgets import AdminFileWidget
from django.core.exceptions import PermissionDenied, ValidationError
from django.forms import BaseInlineFormSet, ModelForm
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.db.models.deletion import RestrictedError
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django_json_widget.widgets import JSONEditorWidget
from modeltranslation.admin import TabbedTranslationAdmin

from webapp.fields import NetworkLogoImageField
from webapp.forms import BannerChangeListForm, BannerForm, LocationPermissionsForm, NetworkForm, NetworkLogoField, SponsorForm
from webapp.models import UserProfile, Table, TableLink, Comment, Player, Location, Game, LocationFollower, FavoriteUser, Notification, Member, \
    Membership, MembershipDocument, GuestProfile, LocationGame, FAQCategory, FAQ, TelegramGroupConfig, \
    TelegramSetupToken, Event, MasterEvent, Sponsor, PlayArea, EventDate, PushSubscription, \
    PhysicalTable, EventParticipant, EventGame, EventGameTag, LocationGameTag, LocationNetwork, Network, Banner
from webapp.services import games as game_services
from webapp.services import profile_merge
from webapp.services.tables import sync_legacy_result




class BggCodeFilter(admin.SimpleListFilter):
    title = 'BGG Code'
    parameter_name = 'has_bgg_code'

    def lookups(self, request, model_admin):
        return [('yes', 'Presente'), ('no', 'Assente')]

    def queryset(self, request, queryset):
        if self.value() == 'yes':
            return queryset.exclude(bgg_code__isnull=True).exclude(bgg_code='')
        if self.value() == 'no':
            return queryset.filter(models.Q(bgg_code__isnull=True) | models.Q(bgg_code=''))


class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'date_joined', 'is_staff')
    ordering = ('-date_joined',)  # opzionale: ordina per data


# Deregistra l'admin default e registra il nostro
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'short_endpoint', 'created_at')
    list_select_related = ('user_profile',)
    readonly_fields = ('user_profile', 'endpoint', 'p256dh', 'auth', 'created_at')

    def short_endpoint(self, obj):
        return obj.endpoint[:80] + '…' if len(obj.endpoint) > 80 else obj.endpoint
    short_endpoint.short_description = 'Endpoint'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("nickname", "created_at", "user", "phone", "is_email_verified")
    search_fields = ("nickname", "slug", "user__username", "user__email", "phone")
    actions = ["merge_profiles_action"]

    def has_merge_permission(self, request):
        return request.user.is_superuser

    @admin.action(permissions=["merge"], description=_("Merge accounts"))
    def merge_profiles_action(self, request, queryset):
        ids = list(queryset.order_by('pk').values_list('pk', flat=True)[:3])
        if len(ids) != 2:
            self.message_user(request, _("Select exactly two accounts to merge."), messages.ERROR)
            return None
        url = reverse('admin:webapp_userprofile_merge')
        return redirect(f'{url}?a={ids[0]}&b={ids[1]}')

    def get_urls(self):
        return [
            path('merge/', self.admin_site.admin_view(self.merge_view), name='webapp_userprofile_merge'),
        ] + super().get_urls()

    def merge_view(self, request):
        if not self.has_merge_permission(request):
            raise PermissionDenied

        data = request.POST if request.method == 'POST' else request.GET
        try:
            ids = [int(data.get(key)) for key in ('a', 'b')]
            profiles = list(self.get_queryset(request).filter(pk__in=ids).select_related('user').order_by('pk'))
        except (TypeError, ValueError):
            profiles = []
        if len(profiles) != 2:
            self.message_user(request, _("Select two different accounts that still exist."), messages.ERROR)
            return redirect('admin:webapp_userprofile_changelist')

        keeper = next((profile for profile in profiles if str(profile.pk) == data.get('keep')), None)
        error = None
        allowed = True
        try:
            profile_merge.validate_accounts(*(profile.user for profile in profiles))
        except ValidationError as exc:
            error = ' '.join(exc.messages)
            allowed = False

        try:
            if allowed and request.method == 'POST':
                if keeper is None:
                    raise ValidationError(_("Choose the account to keep."))
                duplicate = next(profile for profile in profiles if profile.pk != keeper.pk)
                with transaction.atomic():
                    keeper = profile_merge.merge_accounts(keeper.pk, duplicate.pk)
                    summary = _("Merged account %(duplicate)s into %(keeper)s.") % {
                        'duplicate': f'{duplicate.slug} (#{duplicate.pk})',
                        'keeper': f'{keeper.slug} (#{keeper.pk})',
                    }
                    self.log_change(request, keeper, summary)
                self.message_user(request, summary, messages.SUCCESS)
                return redirect('admin:webapp_userprofile_change', keeper.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        except IntegrityError:
            error = _("A database conflict prevented the merge. No changes were saved.")

        accounts = [
            {
                'profile': profile,
                'has_password': profile_merge.has_password(profile.user),
                'logins': list(profile.user.social_auth.order_by('provider', 'pk')),
            }
            for profile in profiles
        ]
        first, second = ({login.provider for login in account['logins']} for account in accounts)
        without_email = any(not profile.user.email for profile in profiles)
        unverified_email = next(
            (profile.user.email for profile in profiles if profile.user.email and not profile.is_email_verified), None)
        return TemplateResponse(request, 'admin/webapp/userprofile/merge.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': _("Merge accounts"),
            'profiles': profiles,
            'accounts': accounts,
            'shared_providers': sorted(first & second),
            'unverified_import': unverified_email if without_email else None,
            'keeper': keeper,
            'error': error,
            'allowed': allowed,
        })


class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0
    fields = ('user_profile', 'position', 'score', 'team', 'outcome')
    readonly_fields = ('outcome',)


class TableLinkInline(admin.TabularInline):
    model = TableLink
    extra = 0
    fields = ('label', 'url')


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("title", "location", "author", "date", "time", "status", "leaderboard_status")
    list_filter = ("location", "status", "leaderboard_status", "result_mode", "date")
    autocomplete_fields = ("location", "game")
    inlines = [PlayerInline, TableLinkInline]

    def save_model(self, request, obj, form, change):
        if not obj.slug:
            obj.slug = obj.create_unique_slug()
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Positions may have been edited in the inline: keep result_mode/outcomes in sync.
        sync_legacy_result(form.instance)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("uuid", "table", "author", "content")


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("user_profile", "table", "position", "score", "team", "outcome")
    list_filter = ("user_profile", "table", "score", "position", "outcome")
    readonly_fields = ("outcome",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        sync_legacy_result(obj.table)


class LocationNetworkInline(admin.TabularInline):
    model = LocationNetwork
    verbose_name_plural = _('National affiliations')
    extra = 0
    fields = ('network', 'local_name', 'custom_logo')
    readonly_fields = ('network', 'local_name')
    formfield_overrides = {
        NetworkLogoImageField: {'form_class': NetworkLogoField, 'widget': AdminFileWidget},
    }

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('network')


class LocationAdminForm(LocationPermissionsForm):
    class Meta(LocationPermissionsForm.Meta):
        fields = '__all__'


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    form = LocationAdminForm
    list_display = ("name", "city", "creator", "enable_membership", "enable_calendar", "created_at")
    list_filter = ("city", "network_affiliations__network", "enable_membership", "enable_calendar", "created_at")
    list_editable = ("enable_membership", "enable_calendar")
    search_fields = ("name", "city", "creator__nickname")
    filter_horizontal = ("managers",)
    inlines = [LocationNetworkInline]
    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget},
    }


@admin.register(Network)
class NetworkAdmin(admin.ModelAdmin):
    form = NetworkForm
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')
    readonly_fields = ('slug',)

    def get_readonly_fields(self, request, obj=None):
        if obj and self.admin_site.get_model_admin(Location).has_view_or_change_permission(request):
            return (*self.readonly_fields, 'affiliated_locations')
        return self.readonly_fields

    @admin.display(description=_('Affiliated locations'))
    def affiliated_locations(self, obj):
        url = reverse('admin:webapp_location_changelist', query={'network_affiliations__network__id__exact': obj.pk})
        return format_html('<a href="{}">{}</a>', url, _('View affiliated locations'))


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ("name", "bgg_code", "default_result_mode")
    list_editable = ("bgg_code", "default_result_mode")
    list_filter = (BggCodeFilter, "bgg_imported", "verified", "default_result_mode", "leaderboard_enabled")
    search_fields = ("name",)
    actions = ["merge_games_action"]

    @admin.action(description=_("Merge the two selected games"))
    def merge_games_action(self, request, queryset):
        if queryset.count() != 2:
            self.message_user(request, _("Select exactly two games to merge."), level=messages.ERROR)
            return None
        a, b = queryset.order_by('pk')
        return redirect(f"{reverse('admin:webapp_game_merge')}?a={a.pk}&b={b.pk}")

    def get_urls(self):
        return [
            path('merge/', self.admin_site.admin_view(self.merge_view), name='webapp_game_merge'),
        ] + super().get_urls()

    def merge_view(self, request):
        """Confirmation page: pick the game to keep and, field by field, the value that wins."""
        if not self.has_delete_permission(request) or not self.has_change_permission(request):
            raise PermissionDenied
        data = request.POST if request.method == 'POST' else request.GET
        try:
            game_a = Game.objects.get(pk=int(data.get('a')))
            game_b = Game.objects.get(pk=int(data.get('b')))
        except (TypeError, ValueError, Game.DoesNotExist):
            self.message_user(request, _("Games not found."), level=messages.ERROR)
            return redirect('admin:webapp_game_changelist')
        if game_a.pk == game_b.pk:
            return redirect('admin:webapp_game_changelist')

        keep = data.get('keep')
        keeper = {str(game_a.pk): game_a, str(game_b.pk): game_b}.get(keep) or game_services.default_keeper(game_a, game_b)
        duplicate = game_b if keeper.pk == game_a.pk else game_a

        if request.method == 'POST' and 'confirm' in request.POST:
            choices = {f: request.POST.get(f'choice_{f}', 'keeper') for f in game_services.MERGEABLE_FIELDS}
            duplicate_repr = f'{duplicate} (#{duplicate.pk})'
            try:
                result = game_services.merge_games(keeper, duplicate, choices)
            except RestrictedError:
                self.message_user(request, _("The merge would remove a library entry with loan history."), level=messages.ERROR)
                return redirect('admin:webapp_game_changelist')
            keeper.refresh_from_db()
            summary = _("Merged %(dup)s into %(keeper)s: %(tables)d tables moved, %(moved)d library entries "
                        "moved, %(merged)d library entries merged, %(event_moved)d event library entries moved, "
                        "%(event_merged)d event library entries merged.") % {
                'dup': duplicate_repr, 'keeper': keeper, 'tables': result.tables_moved,
                'moved': result.library_moved, 'merged': result.library_merged,
                'event_moved': result.event_library_moved, 'event_merged': result.event_library_merged}
            self.log_change(request, keeper, summary)
            self.message_user(request, summary, level=messages.SUCCESS)
            return redirect('admin:webapp_game_change', keeper.pk)

        def display(game, field):
            value = getattr(game, field)
            if field == 'default_result_mode':
                return game.get_default_result_mode_display()
            return value

        rows = [{
            'field': field,
            'label': Game._meta.get_field(field).verbose_name,
            'keeper': display(keeper, field),
            'duplicate': display(duplicate, field),
            'choice': game_services.default_choice(field, keeper, duplicate),
            'is_image': field == 'image',
        } for field in game_services.differing_fields(keeper, duplicate)]

        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': _("Merge games"),
            'game_a': game_a, 'game_b': game_b,
            'keeper': keeper, 'duplicate': duplicate,
            'rows': rows,
            'tables_to_move': Table.objects.filter(game=duplicate).count(),
            'library_to_move': LocationGame.objects.filter(game=duplicate).count(),
            'event_library_to_move': EventGame.objects.filter(game=duplicate).count(),
            'library_conflicts': game_services.library_conflicts(keeper, duplicate),
            'different_bgg': bool(keeper.bgg_code and duplicate.bgg_code and keeper.bgg_code != duplicate.bgg_code),
            'or_flags': [(f, getattr(keeper, f) or getattr(duplicate, f)) for f in game_services.OR_FLAGS],
        }
        return TemplateResponse(request, 'admin/webapp/game/merge.html', context)


@admin.register(LocationFollower)
class LocationFollowerAdmin(admin.ModelAdmin):
    pass


@admin.register(FavoriteUser)
class FavoriteUserAdmin(admin.ModelAdmin):
    list_display = ('owner', 'favorite', 'created_at')
    search_fields = ('owner__nickname', 'favorite__nickname')
    autocomplete_fields = ('owner', 'favorite')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notification_type', 'table', 'location', 'is_read', 'sent')
    list_editable = ('is_read', 'sent',)
    search_fields = ('recipient__nickname', 'recipient__user__username', 'recipient__user__email')
    autocomplete_fields = ('recipient',)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    fields = ('status', 'start_date', 'end_date', 'approved_by', 'notes')


class LoanRelatedAdminMixin:
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Django wraps these admin POSTs in a transaction. Lock the object
        # before the form decides which fields can be edited.
        if request.method == 'POST' and request.resolver_match:
            prefix = f'{self.opts.app_label}_{self.opts.model_name}'
            if request.resolver_match.url_name in (f'{prefix}_change', f'{prefix}_delete'):
                queryset = queryset.select_for_update(of=('self',))
        return queryset


@admin.register(Member)
class MemberAdmin(LoanRelatedAdminMixin, admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'fiscal_code', 'location', 'user_profile', 'email')
    list_filter = ('location',)
    search_fields = ('first_name', 'last_name', 'fiscal_code', 'email')
    inlines = [MembershipInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.game_loans.exists():
            return (*super().get_readonly_fields(request, obj), 'location')
        return super().get_readonly_fields(request, obj)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('member', 'status', 'start_date', 'end_date', 'approved_by')
    list_filter = ('status', 'member__location')
    search_fields = ('member__first_name', 'member__last_name')


@admin.register(MembershipDocument)
class MembershipDocumentAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'is_active', 'created_at')
    list_filter = ('is_active', 'location')
    search_fields = ('name', 'location__name')


@admin.register(GuestProfile)
class GuestProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner')
    search_fields = ('name', 'owner__nickname')
    list_filter = ('owner',)


@admin.register(LocationGame)
class LocationGameAdmin(LoanRelatedAdminMixin, admin.ModelAdmin):
    list_display = ('game', 'location', 'ownership', 'owner_member', 'physical_location', 'is_archived', 'withdrawn_on')
    list_filter = ('location', 'ownership', 'physical_location', 'is_archived', 'withdrawal_reason')
    search_fields = ('game__name', 'location__name', 'owner_member__first_name', 'owner_member__last_name')
    filter_horizontal = ('tags',)


@admin.register(LocationGameTag)
class LocationGameTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'location', 'order')
    search_fields = ('name', 'location__name')
    autocomplete_fields = ('location',)


class FAQInline(admin.TabularInline):
    model = FAQ
    extra = 0
    fields = ('question', 'order', 'is_active')
    show_change_link = True


@admin.register(Banner)
class BannerAdmin(TabbedTranslationAdmin):
    form = BannerForm
    list_display = ('key', 'title', 'version', 'is_active', 'priority', 'audience', 'placement', 'starts_at', 'ends_at')
    list_editable = ('is_active', 'priority')
    list_filter = ('is_active', 'audience', 'placement', 'dismissal')
    search_fields = ('key', 'title', 'message')
    readonly_fields = ('cover_preview',)
    fieldsets = (
        (None, {'fields': ('key', 'version', 'is_active', 'title', 'message')}),
        (_('Cover and link'), {'fields': ('cover', 'cover_preview', 'cover_alt', 'action_label', 'action_url')}),
        (_('Visibility'), {'fields': ('audience', 'placement', 'priority', 'starts_at', 'ends_at')}),
        (_('Closing'), {'fields': ('dismissal', 'dismissal_days')}),
    )

    def get_readonly_fields(self, request, obj=None):
        return (*self.readonly_fields, 'key') if obj else self.readonly_fields

    def get_changelist_form(self, request, **kwargs):
        return super().get_changelist_form(request, **{'form': BannerChangeListForm, **kwargs})

    @admin.display(description=_('Cover preview'))
    def cover_preview(self, obj):
        if obj and obj.cover:
            return format_html('<img src="{}" alt="" style="max-width:320px;max-height:160px;object-fit:contain">',
                               obj.cover.url)
        return '—'


@admin.register(FAQCategory)
class FAQCategoryAdmin(TabbedTranslationAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)
    inlines = [FAQInline]


@admin.register(FAQ)
class FAQAdmin(TabbedTranslationAdmin):
    list_display = ('question', 'category', 'order', 'is_active')
    list_editable = ('order', 'is_active')
    list_filter = ('category', 'is_active')
    search_fields = ('question', 'answer')
    raw_id_fields = ('category',)


@admin.register(TelegramGroupConfig)
class TelegramGroupConfigAdmin(admin.ModelAdmin):
    list_display = ('location', 'chat_title', 'chat_id', 'active', 'created_at')
    list_filter = ('active', 'location')
    search_fields = ('chat_title', 'location__name')
    list_editable = ('active',)


@admin.register(TelegramSetupToken)
class TelegramSetupTokenAdmin(admin.ModelAdmin):
    list_display = ('location', 'token', 'expires_at', 'used', 'created_at')
    list_filter = ('used', 'location')
    search_fields = ('token', 'location__name')
    readonly_fields = ('token', 'created_at')


class PlayAreaInline(admin.TabularInline):
    model = PlayArea
    extra = 1
    fields = ('name', 'order')


class EventDateInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if not self.instance.organizer_location_id or any(self.errors):
            return
        days = []
        for form in self.forms:
            data = form.cleaned_data
            if not data.get('DELETE') and data.get('date'):
                self.instance.validate_master_day(data['date'])
                days.append(data['date'])
            if form.instance.pk and (data.get('DELETE') or 'date' in form.changed_data):
                old = EventDate.objects.get(pk=form.instance.pk)
                old.check_removal(replacing=True)
        if self.instance.is_published and not days:
            raise ValidationError(_('A published event needs at least one date.'))

    @transaction.atomic
    def save(self, commit=True):
        if not commit or not self.instance.organizer_location_id:
            return super().save(commit=commit)
        event = Event.objects.select_for_update().get(pk=self.instance.pk)
        # Django deletes existing inlines before saving new ones. Check the
        # last-day rule against the result of the whole calendar edit.
        for form in self.deleted_forms:
            form.instance._defer_last_date_check = True
        dates = super().save()
        if event.is_published and not event.dates.exists():
            raise ValidationError(_('A published event needs at least one date.'))
        return dates


class EventDateInline(admin.TabularInline):
    formset = EventDateInlineFormSet
    model = EventDate
    extra = 1
    fields = ('date',)


class PhysicalTableInline(admin.TabularInline):
    model = PhysicalTable
    extra = 1
    fields = ('name', 'play_area', 'order')


class EventAdminForm(ModelForm):
    class Meta:
        model = Event
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'organizer_location' in self.fields:
            self.fields['organizer_location'].required = (
                self.instance._state.adding or self.instance.organizer_location_id is not None
            )


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventAdminForm
    autocomplete_fields = ('organizer_location', 'venue_location')
    list_display = ('name', 'city', 'creator', 'status', 'participant_count', 'created_at')
    list_filter = ('status', 'city')
    list_editable = ('status',)
    search_fields = ('name', 'city', 'creator__nickname')
    filter_horizontal = ('managers', 'sponsor_locations', 'allowed_table_creators')
    readonly_fields = ('created_at', 'updated_at', 'venue_layout_requested_from', 'venue_layout_approved', 'master_event')
    inlines = [PlayAreaInline, EventDateInline, PhysicalTableInline]

    @admin.display(description=_('Participants'), ordering='_participant_count')
    def participant_count(self, obj):
        return obj._participant_count

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            _participant_count=models.Count('participants', distinct=True))

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            # A legacy mapping may have run while the admin form was being validated.
            current = Event.objects.select_for_update().only('master_event_id', 'organizer_location_id').get(pk=obj.pk)
            obj.master_event_id = current.master_event_id
            if obj.organizer_location_id is None:
                obj.organizer_location_id = current.organizer_location_id
        super().save_model(request, obj, form, change)


@admin.register(Sponsor)
class SponsorAdmin(admin.ModelAdmin):
    form = SponsorForm
    fields = ('name', 'logo', 'website', 'location')
    list_display = ('name', 'website', 'location')
    list_select_related = ('location',)
    search_fields = ('name',)
    autocomplete_fields = ('location',)


@admin.register(MasterEvent)
class MasterEventAdmin(admin.ModelAdmin):
    list_display = ('name', 'status', 'approved_by', 'approved_at')
    list_filter = ('status',)
    search_fields = ('name',)
    readonly_fields = ('slug', 'status', 'approved_by', 'approved_at')
    filter_horizontal = ('managers', 'sponsors')
    actions = ('approve_publication', 'back_to_draft', 'block')

    def get_readonly_fields(self, request, obj=None):
        if obj is None or obj.can_manage(request.user):
            return self.readonly_fields
        return (*self.readonly_fields, 'managers', 'sponsors')

    @admin.action(description=_('Approve publication'), permissions=['change'])
    def approve_publication(self, request, queryset):
        for master in queryset:
            try:
                if master.approve(request.user):
                    self.message_user(request, _('%(name)s was published.') % {'name': master.name}, messages.SUCCESS)
            except ValidationError as error:
                self.message_user(request, f"{master}: {' '.join(error.messages)}", messages.ERROR)

    @admin.action(description=_('Back to draft'), permissions=['change'])
    def back_to_draft(self, request, queryset):
        for master in queryset:
            if master.withdraw(request.user, Event.DRAFT):
                self.message_user(request, _('%(name)s is back to draft.') % {'name': master.name}, messages.SUCCESS)

    @admin.action(description=_('Block'), permissions=['change'])
    def block(self, request, queryset):
        for master in queryset:
            if master.withdraw(request.user, Event.BLOCKED):
                self.message_user(request, _('%(name)s was blocked.') % {'name': master.name}, messages.SUCCESS)


@admin.register(EventGameTag)
class EventGameTagAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'show_on_event_page', 'order')
    list_filter = ('show_on_event_page',)
    search_fields = ('name', 'event__name')
    autocomplete_fields = ('event',)


@admin.register(EventGame)
class EventGameAdmin(admin.ModelAdmin):
    list_display = ('game', 'event', 'created_at')
    search_fields = ('game__name', 'event__name')
    autocomplete_fields = ('event', 'game', 'source_location_game')
    filter_horizontal = ('tags', 'sponsor_locations')
    readonly_fields = ('uuid', 'created_at', 'updated_at')


@admin.register(PhysicalTable)
class PhysicalTableAdmin(admin.ModelAdmin):
    list_display = ('name', 'event', 'play_area', 'order')
    list_filter = ('event',)
    search_fields = ('name', 'event__name')


@admin.register(EventParticipant)
class EventParticipantAdmin(admin.ModelAdmin):
    list_display = ('user_profile', 'event', 'created_at')
    list_filter = ('event',)
    search_fields = ('user_profile__nickname', 'event__name')
    autocomplete_fields = ('event', 'user_profile')
