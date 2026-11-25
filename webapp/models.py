import re
import string
import uuid
import random
import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import mistune
import nh3

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.contrib.gis.geos import Point
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator, URLValidator
from django.db import transaction
from django.urls import reverse, translate_url
from django.utils import timezone, translation
from django.utils.encoding import force_bytes
from django.utils.functional import cached_property
from django.utils.http import urlsafe_base64_encode, url_has_allowed_host_and_scheme
from django.utils.translation import get_language, gettext_lazy as _
from django.utils.text import slugify
from meta.models import ModelMeta
from model_utils import FieldTracker
from phonenumber_field.modelfields import PhoneNumberField

from webapp.fields import ManagedImageField, NetworkLogoImageField
from webapp.image_models import ManagedImagesModel
from webapp.services.images import AVATAR_MAX_SIDE, COVER_MAX_SIDE


def _plain_text(markdown_text):
    """Convert Markdown to plain text (strip all tags) and truncate for meta."""
    if not markdown_text:
        return ''
    html = mistune.html(markdown_text)
    plain = nh3.clean(html, tags=set())
    plain = re.sub(r'\s+', ' ', plain).strip()
    return plain[:160]


def _absolute_url(url, request=None):
    """Make a possibly-relative URL absolute for structured data / OG tags.
    S3 media URLs are already absolute; STATIC_URL fallbacks are not."""
    if not url:
        return None
    if url.startswith(('http://', 'https://')):
        return url
    if request is not None:
        return request.build_absolute_uri(url)
    return settings.DOMAIN_URL + url


class DateTimeModel(ManagedImagesModel):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta(object):
        abstract = True


class SlugModel(models.Model):
    slug_field_name = None
    random_string_length = 6
    regenerate_slug_on_rename = True

    class Meta:
        abstract = True

    @staticmethod
    def generate_random_string(length=random_string_length):
        letters = string.ascii_lowercase
        return ''.join(random.choice(letters) for i in range(length))

    def get_slug_source_value(self):
        if not self.slug_field_name or not hasattr(self, self.slug_field_name):
            raise ValueError("slug_field_name must be defined for SlugModel instance.")
        return getattr(self, self.slug_field_name)

    def create_unique_slug(self):
        # Titles made only of emoji or non-latin characters slugify to '', which breaks reverse()
        base_slug = slugify(self.get_slug_source_value()) or self._meta.model_name
        # Names can be longer than the slug column: truncate, leaving room for
        # the random suffix when one is needed, or Postgres raises DataError.
        max_length = self._meta.get_field('slug').max_length
        base_slug = base_slug[:max_length].rstrip('-')
        qs = self.__class__.objects.filter(slug=base_slug)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if not qs.exists():
            return base_slug
        prefix = base_slug[:max_length - self.random_string_length - 1].rstrip('-')
        while True:
            candidate = f"{prefix}-{self.generate_random_string()}"
            if not self.__class__.objects.filter(slug=candidate).exclude(pk=self.pk or 0).exists():
                return candidate

    def save(self, *args, **kwargs):
        if not self.regenerate_slug_on_rename:
            if not self.slug:
                self.slug = self.create_unique_slug()
        elif self.pk:
            original = type(self).objects.get(pk=self.pk)
            original_slug = slugify(getattr(original, self.slug_field_name))
            current_slug = slugify(self.get_slug_source_value())
            if original_slug != current_slug or not self.slug:
                self.slug = self.create_unique_slug()
        else:
            self.slug = self.create_unique_slug()
        super().save(*args, **kwargs)


class ResultMode(models.TextChoices):
    """How a table's result is recorded (see docs/leaderboard-seasons-plan.md)."""
    FFA = 'ffa', _('Free for all')
    TEAMS = 'teams', _('Teams')
    COOP = 'coop', _('Cooperative')
    NONE = 'none', _('No leaderboard')


class GameOutcome(models.TextChoices):
    """Outcome of the players against the game itself (coop, or "the game won")."""
    WON = 'won', _('Won')
    LOST = 'lost', _('Lost')


class PlayerOutcome(models.TextChoices):
    """Normalised per-player outcome, derived from the recorded result."""
    WON = 'won', _('Won')
    LOST = 'lost', _('Lost')
    DRAW = 'draw', _('Draw')


class Game(DateTimeModel, ModelMeta, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    image = ManagedImageField(upload_to='games', null=True, blank=True, max_side=COVER_MAX_SIDE)
    description = models.TextField()
    bgg_code = models.CharField(max_length=20, null=True, blank=True, verbose_name='BGG Code')
    min_players = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Minimum players'))
    max_players = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Maximum players'))
    min_playtime = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Min playtime (minutes)'))
    max_playtime = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Max playtime (minutes)'))
    weight = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, verbose_name=_('Weight'))
    year_published = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Year published'))

    leaderboard_enabled = models.BooleanField(default=False, db_index=True)
    default_result_mode = models.CharField(
        max_length=10, choices=ResultMode.choices, default=ResultMode.NONE,
        # DB-level default too, so code that predates this column can still insert games
        db_default=ResultMode.NONE, verbose_name=_('Suggested result mode'))
    bgg_imported = models.BooleanField(default=False, db_index=True)
    verified = models.BooleanField(default=False, db_index=True)
    is_expansion = models.BooleanField(default=False, db_default=False, verbose_name=_('Expansion'))

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'cover_url',
    }

    def get_meta_title(self):
        return _("%(name)s - Board-Gamers.com") % {'name': self.name}

    def get_meta_description(self):
        return _plain_text(self.description)

    @cached_property
    def cover_url(self):
        if self.image and hasattr(self.image, 'url'):
            return self.image.url
        else:
            return settings.DOMAIN_URL + settings.STATIC_URL + settings.DEFAULT_GAME_COVER_URL

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Location(DateTimeModel, ModelMeta, SlugModel):
    # How long after a table's start its leaderboard stays editable (days).
    # Event tables always use the default.
    LEADERBOARD_EDIT_DAYS_DEFAULT = 2
    LEADERBOARD_EDIT_DAYS_MIN = 2
    LEADERBOARD_EDIT_DAYS_MAX = 30
    GAME_LOAN_DAYS_DEFAULT = 7

    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    creator = models.ForeignKey('UserProfile', on_delete=models.CASCADE, related_name='locations', null=True, blank=True)
    managers = models.ManyToManyField('UserProfile', related_name='managed_locations', blank=True)
    networks = models.ManyToManyField('Network', through='LocationNetwork', related_name='locations', blank=True)
    description = models.TextField()
    cover = ManagedImageField(upload_to='location-covers', null=True, blank=True, max_side=COVER_MAX_SIDE)
    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=144, null=True, blank=True)
    latitude = models.CharField(max_length=25, null=True, blank=True)
    longitude = models.CharField(max_length=25, null=True, blank=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    show_tables_in_homepage = models.BooleanField(default=True)
    enable_membership = models.BooleanField(default=False)
    enable_calendar = models.BooleanField(default=False)
    # Lets visitors browse the game library (LocationGame) from the location page.
    enable_public_games = models.BooleanField(default=True)
    # Sections of the public location page the managers can hide.
    show_most_played_games = models.BooleanField(default=True)
    show_stats = models.BooleanField(default=True)
    show_top_gamers = models.BooleanField(default=True)
    enable_game_loans = models.BooleanField(default=False, verbose_name=_('Enable game loans'))
    enable_member_game_loans = models.BooleanField(
        default=False, verbose_name=_('Allow members to record their own loans'))
    show_game_loan_borrower = models.BooleanField(
        default=False, verbose_name=_('Show the borrower’s nickname to members'))
    game_loan_days = models.PositiveSmallIntegerField(
        default=GAME_LOAN_DAYS_DEFAULT,
        validators=[MinValueValidator(1)],
        verbose_name=_('Default loan duration (days)'),
    )
    website = models.URLField(null=True, blank=True)
    facebook_url = models.URLField(
        _('Facebook profile'), blank=True, max_length=500,
        validators=[RegexValidator(
            r'\Ahttps?://(?:(?:www|m|web)\.)?(?:facebook\.com|fb\.com)/'
            r'(?:[\w.-]+|(?:people|pages|p)/[^/?#]+(?:/\d+)?|share/[\w-]+)/?(?:[?#]|\Z)',
            _('Enter a Facebook profile URL.'), flags=re.IGNORECASE,
        )],
    )
    instagram_url = models.URLField(
        _('Instagram profile'), blank=True, max_length=500,
        validators=[RegexValidator(
            r'\Ahttps?://(?:www\.)?instagram\.com/[\w.]+/?(?:[?#]|\Z)',
            _('Enter an Instagram profile URL.'), flags=re.IGNORECASE,
        )],
    )
    opening_hours = models.JSONField(null=True, blank=True)
    default_table_time = models.TimeField(
        default=datetime.time(20, 30),
        null=False,
        blank=True,
        verbose_name=_('Default table time'),
        help_text=_('Default start time used when creating new tables at this location.'),
    )
    leaderboard_edit_days = models.PositiveSmallIntegerField(
        default=LEADERBOARD_EDIT_DAYS_DEFAULT,
        validators=[MinValueValidator(LEADERBOARD_EDIT_DAYS_MIN), MaxValueValidator(LEADERBOARD_EDIT_DAYS_MAX)],
        verbose_name=_('Leaderboard editable for (days)'),
        help_text=_('How many days after the start of a table its leaderboard can still be filled in.'),
    )

    # Permission choices
    PERM_ANYONE = 'anyone'
    PERM_MEMBERS_ONLY = 'members_only'
    PERM_MANAGERS_ONLY = 'managers_only'

    TABLE_CREATION_CHOICES = [
        ('anyone', _('Anyone')),
        ('members_only', _('Members only')),
        ('managers_only', _('Owners and managers only')),
    ]
    TABLE_JOIN_CHOICES = [
        ('anyone', _('Anyone')),
        ('members_only', _('Members only')),
    ]
    EVENT_CREATION_CHOICES = [
        (PERM_MANAGERS_ONLY, _('Owners and managers only')),
        (PERM_MEMBERS_ONLY, _('Members only')),
    ]
    event_creation_permission = models.CharField(
        max_length=20, choices=EVENT_CREATION_CHOICES, default=PERM_MANAGERS_ONLY, db_default=PERM_MANAGERS_ONLY,
        verbose_name=_('Who can create events'),
    )
    event_join_permission = models.CharField(
        max_length=20, choices=TABLE_JOIN_CHOICES, default=PERM_ANYONE, db_default=PERM_ANYONE,
        verbose_name=_('Who can join events'),
    )

    table_creation_permission = models.CharField(
        max_length=20,
        choices=TABLE_CREATION_CHOICES,
        default='anyone',
        verbose_name=_('Who can create tables'),
    )
    table_join_permission = models.CharField(
        max_length=20,
        choices=TABLE_JOIN_CHOICES,
        default='anyone',
        verbose_name=_('Who can join tables'),
    )

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'cover_url',
    }

    def is_manager(self, user_profile):
        return bool(user_profile and (
            self.creator_id == user_profile.pk or self.managers.filter(pk=user_profile.pk).exists()))

    @classmethod
    def event_creation_locations(cls, user):
        if not user.is_authenticated:
            return cls.objects.none()
        if user.is_superuser:
            return cls.objects.all()
        profile = user.user_profile
        managed = models.Q(creator=profile) | models.Q(managers=profile)
        member = models.Q(
            event_creation_permission=cls.PERM_MEMBERS_ONLY,
            pk__in=Membership.active_for(profile).values('member__location_id'),
        )
        return cls.objects.filter(managed | member).distinct()

    def can_create_events(self, user):
        return self.event_creation_locations(user).filter(pk=self.pk).exists()

    def can_join_events(self, profile):
        return bool(profile and (
            self.event_join_permission == self.PERM_ANYONE
            or profile.user.is_superuser
            or self.is_manager(profile)
            or Membership.active_for(profile).filter(member__location=self).exists()
        ))

    def get_meta_title(self):
        return _("%(name)s - Board-Gamers.com") % {'name': self.name}

    def get_meta_description(self):
        return _("Game nights in %(address)s") % {'address': self.address}

    # Maps opening_hours JSON day keys ('0'=Monday .. '6'=Sunday) to schema.org.
    _SCHEMA_WEEKDAYS = [
        'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

    def as_schema_place(self, request=None):
        """schema.org/Place fragment for this location, embeddable inside other
        entities (e.g. a Table's `location`) or wrapped with @context standalone."""
        place = {
            '@type': 'Place',
            'name': self.name,
            'url': _absolute_url(reverse('location-detail', kwargs={'slug': self.slug}), request),
        }
        if self.cover:
            place['image'] = _absolute_url(self.cover_url, request)
        if self.address or self.city:
            postal = {'@type': 'PostalAddress'}
            if self.address:
                postal['streetAddress'] = self.address
            if self.city:
                postal['addressLocality'] = self.city
            place['address'] = postal
        if self.latitude and self.longitude:
            place['geo'] = {
                '@type': 'GeoCoordinates',
                'latitude': self.latitude,
                'longitude': self.longitude,
            }
        if self.website:
            place['sameAs'] = self.website
        specs = self._opening_hours_schema()
        if specs:
            place['openingHoursSpecification'] = specs
        return place

    def _opening_hours_schema(self):
        """Build schema.org openingHoursSpecification from the opening_hours JSON."""
        if not self.opening_hours:
            return []
        specs = []
        for key, day in self.opening_hours.items():
            try:
                weekday = self._SCHEMA_WEEKDAYS[int(key)]
            except (ValueError, IndexError):
                continue
            if not day.get('is_open'):
                continue
            for slot in day.get('slots', []):
                if slot.get('open') and slot.get('close'):
                    specs.append({
                        '@type': 'OpeningHoursSpecification',
                        'dayOfWeek': f'https://schema.org/{weekday}',
                        'opens': slot['open'],
                        'closes': slot['close'],
                    })
        return specs

    def structured_data(self, request=None):
        """schema.org/Place JSON-LD payload for the location page."""
        data = {'@context': 'https://schema.org'}
        data.update(self.as_schema_place(request))
        return data

    def __str__(self):
        return f"{self.name} - {self.city}"

    @cached_property
    def cover_url(self):
        if self.cover and hasattr(self.cover, 'url'):
            return self.cover.url
        else:
            return settings.STATIC_URL + settings.DEFAULT_LOCATION_COVER_URL

    @property
    def has_active_membership_documents(self):
        """Whether this location publishes documents members have to sign.
        Filters in Python so a prefetch of `membership_documents` is reused."""
        return any(document.is_active for document in self.membership_documents.all())

    def save(self, *args, **kwargs):
        if self.latitude and self.longitude:
            self.point = Point(float(self.longitude), float(self.latitude), srid=4326)
        super().save(*args, **kwargs)


class Network(DateTimeModel, SlugModel):
    slug_field_name = 'name'
    regenerate_slug_on_rename = False

    name = models.CharField(_('Name'), max_length=255)
    slug = models.SlugField(max_length=144, unique=True, blank=True)
    logo = NetworkLogoImageField(_('National logo'), upload_to='network-logos', blank=True)
    website = models.URLField(_('Website'), blank=True, validators=[URLValidator(schemes=['http', 'https'])])
    is_active = models.BooleanField(_('Active'), default=True)

    class Meta:
        ordering = ['name', 'pk']
        verbose_name = _('National network')
        verbose_name_plural = _('National networks')

    def __str__(self):
        return self.name


class LocationNetwork(DateTimeModel):

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='network_affiliations')
    network = models.ForeignKey(Network, on_delete=models.PROTECT, related_name='affiliations',
                                verbose_name=_('National network'))
    local_name = models.CharField(_('Local affiliation name'), max_length=100, blank=True)
    custom_logo = NetworkLogoImageField(_('Custom affiliation logo'), upload_to='location-network-logos', blank=True)

    class Meta:
        ordering = ['network__name', 'network_id', 'pk']
        constraints = [models.UniqueConstraint(fields=['location', 'network'], name='unique_location_network')]
        verbose_name = _('Location affiliation')
        verbose_name_plural = _('Location affiliations')

    @property
    def display_name(self):
        return self.local_name or self.network.name

    def __str__(self):
        return f'{self.location.name} – {self.network.name}'


class UserProfile(DateTimeModel, ModelMeta, SlugModel):
    slug_field_name = 'nickname'
    nickname = models.CharField(unique=True, max_length=25, null=False, blank=True)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    is_email_verified = models.BooleanField(default=False, db_index=True)
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, related_name='user_profile', on_delete=models.CASCADE, db_index=True)
    address = models.CharField(max_length=350)
    city = models.CharField(max_length=144, null=True, blank=True)
    latitude = models.CharField(max_length=25, null=True, blank=True, db_index=True)
    longitude = models.CharField(max_length=25, null=True, blank=True, db_index=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    avatar = ManagedImageField(upload_to='avatars', null=True, blank=True, max_side=AVATAR_MAX_SIDE)
    phone = PhoneNumberField(null=True, blank=True, region='IT', verbose_name=_('Phone'))

    preferred_language = models.CharField(
        max_length=7,
        choices=settings.LANGUAGES,   # [("it","Italiano"), ("en","English"), ...]
        default="it",
    )

    show_full_name = models.BooleanField(default=False, verbose_name=_("Show full name on profile"))

    # Notifications (email)
    notification_new_table = models.BooleanField(default=True, verbose_name="Notification New Table")
    notification_new_player = models.BooleanField(default=False, verbose_name="Notification New Player")
    notification_new_comments = models.BooleanField(default=True, verbose_name="Notification New Comments")

    # Notifications (push)
    push_notification_new_table = models.BooleanField(default=True, verbose_name="Push Notification New Table")
    push_notification_new_player = models.BooleanField(default=True, verbose_name="Push Notification New Player")
    notification_leaderboard_reminder = models.BooleanField(
        default=True, verbose_name="Notification Leaderboard Reminder")
    notification_leaderboard_update = models.BooleanField(default=True, verbose_name="Notification Leaderboard Update")

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'avatar_url',
    }

    def get_meta_title(self):
        return _("%(nickname)s - Board-Gamers.com") % {'nickname': self.nickname}

    def get_meta_description(self):
        return _("Profile of %(nickname)s on Board-Gamers.com") % {'nickname': self.nickname}

    def save(self, *args, **kwargs):
        if self.latitude and self.longitude:
            self.point = Point(float(self.longitude), float(self.latitude), srid=4326)
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    @property
    def username(self):
        return self.nickname

    @cached_property
    def avatar_url(self):
        if self.avatar and hasattr(self.avatar, 'url'):
            return self.avatar.url
        else:
            return settings.STATIC_URL + settings.DEFAULT_AVATAR_URL

    @staticmethod
    def get_activation_link(user):
        params = {
            'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': default_token_generator.make_token(user),
        }
        return settings.DOMAIN_URL + reverse('email_verify', kwargs=params)

    def __str__(self):
        return self.nickname


class GuestProfile(DateTimeModel):
    """A named guest identity that a user can bring to tables."""
    owner = models.ForeignKey(
        'UserProfile', on_delete=models.CASCADE,
        related_name='guest_profiles', verbose_name=_('Owner')
    )
    name = models.CharField(max_length=100, verbose_name=_('Name'))

    class Meta:
        verbose_name = _('Guest Profile')
        verbose_name_plural = _('Guest Profiles')
        ordering = ['name']

    def __str__(self):
        return self.name


class TableQuerySet(models.QuerySet):
    def public(self):
        return self.filter(Table.public_condition())

    def visible_to(self, user):
        if user.is_superuser:
            return self
        if not user.is_authenticated:
            return self.public()
        return self.filter(Table.public_condition() | models.Q(event__in=Event.objects.managed_by(user.user_profile)))


def clear_unreserved_layout_assignment(collector, field, sub_objs, using):
    """Keep scheduled event assignments; release other references on deletion."""
    scheduled = sub_objs.filter(event__isnull=False, date__gte=timezone.localdate())
    models.RESTRICT(collector, field, scheduled, using)
    models.SET_NULL(collector, field, sub_objs, using)


class Table(DateTimeModel, ModelMeta, SlugModel):
    objects = TableQuerySet.as_manager()

    @classmethod
    def public_condition(cls, prefix=''):
        return models.Q(**{f'{prefix}event__isnull': True}) | models.Q(**{
            f'{prefix}event__status': Event.PUBLISHED, f'{prefix}event__table_booking_enabled': True,
        })

    @property
    def is_public(self):
        return not self.event_id or (self.event.is_published and self.event.table_booking_enabled)

    OPEN = 'open'
    ONGOING = 'ongoing'
    CLOSED = 'closed'
    TABLE_STATUS_DEFAULT = OPEN
    TABLE_STATUS_CHOICES = [
        (OPEN, _('Open')),
        (ONGOING, _('On Going')),
        (CLOSED, _('Closed')),
    ]
    # table_status values in which the session is still active and players can
    # join or leave (everything except CLOSED).
    JOIN_LEAVE_STATUSES = (OPEN, ONGOING)

    LEADERBOARD_NOT_EDITABLE = 'not_editable'
    LEADERBOARD_EDITABLE = 'editable'
    LEADERBOARD_STATUS_DEAFULT = LEADERBOARD_NOT_EDITABLE
    LEADERBOARD_STATUS_CHOICES = [
        (LEADERBOARD_NOT_EDITABLE, _('Not Editable')),
        (LEADERBOARD_EDITABLE, _('Editable')),
    ]

    # ── Lifecycle phase: single time-based source of truth from which BOTH
    #    table_status and leaderboard_status are derived (see _PHASE_STATUS_MAP).
    PHASE_UPCOMING = 'upcoming'              # before the game start time
    PHASE_LIVE = 'live'                      # 0–12h after start
    PHASE_RECENTLY_ENDED = 'recently_ended'  # 12h after start until the leaderboard window ends
    PHASE_ARCHIVED = 'archived'              # after the leaderboard window (see leaderboard_edit_window)

    # Each phase maps to (table_status, leaderboard_status). Keeping both in one
    # map is the common approach: change the lifecycle here and both stay in sync.
    _PHASE_STATUS_MAP = {
        PHASE_UPCOMING:       (OPEN,    LEADERBOARD_NOT_EDITABLE),
        PHASE_LIVE:           (ONGOING, LEADERBOARD_EDITABLE),
        PHASE_RECENTLY_ENDED: (CLOSED,  LEADERBOARD_EDITABLE),
        PHASE_ARCHIVED:       (CLOSED,  LEADERBOARD_NOT_EDITABLE),
    }
    LIVE_WINDOW = datetime.timedelta(hours=12)

    slug_field_name = 'title'
    title = models.CharField(max_length=144, null=False, blank=True, verbose_name=_('Title'))
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    tracker = FieldTracker(fields=['status', 'leaderboard_status', 'game'])

    def get_slug_source_value(self):
        if self.title:
            return self.title
        if self.game:
            return self.game.name
        return 'table'

    description = models.TextField(null=False, blank=True, verbose_name=_('Description'))
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Location'))
    event = models.ForeignKey(
        'Event', on_delete=models.CASCADE, related_name='tables', null=True, blank=True, verbose_name=_('Event'))
    play_area = models.ForeignKey(
        'PlayArea',
        on_delete=clear_unreserved_layout_assignment, related_name='tables', null=True, blank=True, verbose_name=_('Play Area'))
    category = models.ForeignKey(
        'EventTableCategory',
        on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Category'))
    physical_table = models.ForeignKey(
        'PhysicalTable',
        on_delete=clear_unreserved_layout_assignment, related_name='tables', null=True, blank=True, verbose_name=_('Station'))

    min_players = models.SmallIntegerField(null=False, blank=True, default=2, verbose_name=_('Minimum players'))
    max_players = models.SmallIntegerField(null=False, blank=True, default=5, verbose_name=_('Maximum players'))
    external_players = models.PositiveIntegerField(null=False, blank=True, default=0,
                                                   verbose_name=_('External players'))
    unlimited_seats = models.BooleanField(
        default=False, null=False, blank=True, verbose_name=_('Unlimited seats'),
        help_text=_('No seat limit: anyone can join and no empty seats are shown.'))
    date = models.DateField(default=datetime.date.today, null=False, verbose_name=_('Date'))
    time = models.TimeField(default=datetime.time(20, 30), null=False, verbose_name=_('Hour'))
    duration = models.PositiveIntegerField(
        default=120, null=False, blank=True, verbose_name=_('Duration (minutes)'),
        help_text=_('Expected duration in minutes'))

    author = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, related_name='created_tables', null=True)
    players = models.ManyToManyField(UserProfile, through='Player', related_name='joined_tables', blank=True)
    game = models.ForeignKey(
        Game, on_delete=models.SET_NULL, related_name='created_tables', null=True, blank=True, verbose_name=_('Game'))
    custom_cover = ManagedImageField(
        upload_to='table-covers', null=True, blank=True, max_side=COVER_MAX_SIDE,
        verbose_name=_('Custom cover'),
        help_text=_('Optional image shown instead of the game cover.'))

    @property
    def total_players(self):
        """
        Returns the total number of players: registered players + guests + external players.
        Uses player_set (all Player rows) so guests are included.
        Optimizes database access if `player_set` is prefetched.
        """
        if hasattr(self, '_prefetched_objects_cache') and 'player_set' in self._prefetched_objects_cache:
            return len(self.player_set.all()) + self.external_players
        return self.player_set.count() + self.external_players

    @property
    def seats_available(self):
        """Free seats left (registered players + guests + external considered)."""
        return self.max_players - self.total_players

    @property
    def is_session_active(self):
        """True while the session is open or ongoing (i.e. not closed)."""
        return self.status in self.JOIN_LEAVE_STATUSES

    @property
    def is_joinable(self):
        """True when a new player may join: session active and (unlimited or seats free)."""
        return self.is_session_active and (self.unlimited_seats or self.seats_available > 0)

    status = models.CharField(max_length=20, choices=TABLE_STATUS_CHOICES, default=TABLE_STATUS_DEFAULT)
    leaderboard_status = models.CharField(
        max_length=20,
        choices=LEADERBOARD_STATUS_CHOICES,
        default=LEADERBOARD_STATUS_DEAFULT
    )
    # Result recording (null until set; see docs/leaderboard-seasons-plan.md)
    result_mode = models.CharField(
        max_length=10, choices=ResultMode.choices, null=True, blank=True, verbose_name=_('Result mode'))
    game_outcome = models.CharField(
        max_length=10, choices=GameOutcome.choices, null=True, blank=True, verbose_name=_('Outcome against the game'))
    coop_score = models.IntegerField(null=True, blank=True, verbose_name=_('Group score'))
    season = models.ForeignKey(
        'Season', on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Season'))
    # First table of the series this one was duplicated from: copies of a copy
    # point to the same root (see services.tables.duplicate_table)
    series_root = models.ForeignKey(
        'self', on_delete=models.SET_NULL, related_name='series_copies', null=True, blank=True,
        verbose_name=_('Series root'))

    @cached_property
    def cover_url(self):
        if self.custom_cover and hasattr(self.custom_cover, 'url'):
            return self.custom_cover.url
        if self.game and self.game.image and hasattr(self.game.image, 'url'):
            return self.game.image.url
        else:
            return settings.DOMAIN_URL + settings.STATIC_URL + settings.DEFAULT_GAME_COVER_URL

    @property
    def status_badge_class(self):
        return {
            self.CLOSED: 'text-bg-secondary',
            self.ONGOING: 'text-bg-warning',
            self.OPEN: 'text-bg-primary',
        }.get(self.status, 'text-bg-light')

    @property
    def leaderboard_status_badge_class(self):
        return {
            self.LEADERBOARD_NOT_EDITABLE: 'text-bg-secondary',
            self.LEADERBOARD_EDITABLE: 'text-bg-primary',
        }.get(self.leaderboard_status, 'text-bg-light')

    # ── Time-based status computation ──────────────────────────────────────
    def lifecycle_phase(self, at=None):
        """Return the lifecycle phase (PHASE_*) of this table at a given moment.

        Single source of truth: derived purely from the game date+time, anchored
        to the project timezone so DST is handled correctly.
        """
        tz = ZoneInfo(settings.TIME_ZONE)
        current = at or timezone.now()
        game_datetime = datetime.datetime.combine(self.date, self.time, tzinfo=tz)
        if current < game_datetime:
            return self.PHASE_UPCOMING
        if current < game_datetime + self.LIVE_WINDOW:
            return self.PHASE_LIVE
        if current < game_datetime + self.leaderboard_edit_window:
            return self.PHASE_RECENTLY_ENDED
        return self.PHASE_ARCHIVED

    @property
    def leaderboard_edit_window(self):
        """How long after the start the leaderboard stays editable: the location's setting, default for events."""
        days = self.location.leaderboard_edit_days if self.location_id else Location.LEADERBOARD_EDIT_DAYS_DEFAULT
        return datetime.timedelta(days=days)

    def computed_table_status(self, at=None):
        """The table_status this table should have, based on time."""
        return self._PHASE_STATUS_MAP[self.lifecycle_phase(at)][0]

    # Legacy "no position" marker on Player.position (to become NULL in the cleanup phase).
    UNSET_POSITION = 99

    @classmethod
    def is_position_set(cls, position):
        """A real position (not NULL nor the legacy 99 marker)."""
        return position not in (None, cls.UNSET_POSITION)

    @property
    def effective_result_mode(self):
        """The table's own result mode, else the one suggested by its game."""
        if self.result_mode:
            return self.result_mode
        if self.game_id:
            return self.game.default_result_mode
        return ResultMode.NONE

    def recompute_outcomes(self):
        """Derive Player.outcome from the recorded result. Never touches position or score.

        Single source of truth for outcomes (see docs/leaderboard-seasons-plan.md):
        ffa/teams use the positions (shared 1st = everyone won, all tied = draw),
        "the game won" and coop use game_outcome, no mode / no positions = no outcome.
        Writes with bulk_update, so no Player signals fire.
        """
        players = list(self.player_set.all())

        def position(p):
            return None if p.position in (None, self.UNSET_POSITION) else p.position

        mode = self.result_mode
        if mode == ResultMode.COOP:
            for p in players:
                p.outcome = self.game_outcome
        elif mode in (ResultMode.FFA, ResultMode.TEAMS):
            ranked = [p for p in players if position(p) is not None]
            if mode == ResultMode.FFA and self.game_outcome == GameOutcome.LOST:
                outcome_of = lambda p: PlayerOutcome.LOST
            elif not ranked:
                outcome_of = lambda p: None
            else:
                # A side is a player (ffa) or a team; in teams every member carries the team position.
                sides = {(p.team if mode == ResultMode.TEAMS else p.pk): position(p) for p in ranked}
                draw = len(sides) > 1 and all(v == 1 for v in sides.values())
                outcome_of = lambda p: (
                    None if position(p) is None
                    else PlayerOutcome.DRAW if draw
                    else PlayerOutcome.WON if position(p) == 1
                    else PlayerOutcome.LOST
                )
            for p in players:
                p.outcome = outcome_of(p)
        else:
            for p in players:
                p.outcome = None
        Player.objects.bulk_update(players, ['outcome'])

    def computed_leaderboard_status(self, at=None):
        """The leaderboard_status this table should have, based on time."""
        return self._PHASE_STATUS_MAP[self.lifecycle_phase(at)][1]

    def recompute_statuses(self, at=None):
        """Realign BOTH table_status and leaderboard_status on this instance.

        Does not save. Returns True if either value actually changed.
        """
        new_table_status, new_leaderboard_status = \
            self._PHASE_STATUS_MAP[self.lifecycle_phase(at)]
        changed = (
            self.status != new_table_status
            or self.leaderboard_status != new_leaderboard_status
        )
        self.status = new_table_status
        self.leaderboard_status = new_leaderboard_status
        return changed

    def _event_date_changed(self):
        """Tables already outside the calendar (e.g. of an event that got its organizer
        later) must still be saved by the cron and the other actions."""
        if not self.event_id:
            return False
        return not Table.objects.filter(pk=self.pk, event_id=self.event_id, date=self.date).exists()

    _LAYOUT_FIELDS = ('event', 'location', 'play_area', 'physical_table', 'date', 'time', 'duration')

    def _placement_for_save(self, fields):
        if fields is None or self._state.adding:
            return self
        placement = Table.objects.filter(pk=self.pk).only(*self._LAYOUT_FIELDS).first()
        if placement is None:
            return self
        for name in self._LAYOUT_FIELDS:
            attribute = self._meta.get_field(name).attname
            if name in fields or attribute in fields:
                setattr(placement, attribute, getattr(self, attribute))
        return placement

    def _layout_assignment_changed(self):
        if not (self.play_area_id or self.physical_table_id):
            return False
        if self._state.adding:
            return True
        assignment = {name: getattr(self, name) for name in (
            'event_id', 'location_id', 'play_area_id', 'physical_table_id', 'date', 'time', 'duration',
        )}
        return not Table.objects.filter(pk=self.pk, **assignment).exists()

    def _validate_layout_assignment(self, event, *, lock=False):
        if event:
            owner = event.layout_owner()
        else:
            owner = {'location_id': self.location_id} if self.location_id is not None else None
        station = None
        if self.physical_table_id:
            station = PhysicalTable.objects.filter(pk=self.physical_table_id, **owner).first() if owner else None
            if station is None:
                raise ValidationError(_('Choose a station from this schedule’s layout.'))
            if self.play_area_id is None:
                self.play_area_id = station.play_area_id
            elif self.play_area_id != station.play_area_id:
                raise ValidationError(_('The selected station does not belong to the selected area.'))
        if self.play_area_id:
            areas = PlayArea.objects.select_for_update() if lock else PlayArea.objects.all()
            if not owner or not areas.filter(pk=self.play_area_id, **owner).exists():
                raise ValidationError(_('Choose a play area from this schedule’s layout.'))
        # Take the area lock before the station lock, as deleting an area can update its stations.
        if lock and station and not PhysicalTable.objects.select_for_update().filter(
                pk=station.pk, play_area_id=station.play_area_id, **owner).exists():
            raise ValidationError(_('The selected station changed. Choose the station again.'))

    def clean(self):
        super().clean()
        if self.date and self.event_id and self.event.organizer_location_id and self._event_date_changed():
            try:
                self.event.validate_table_date(self.date)
            except ValidationError as error:
                raise ValidationError({'date': error}) from error
        if self._layout_assignment_changed():
            self._validate_layout_assignment(self.event if self.event_id else None)

    def save(self, *args, **kwargs):
        # Keep both statuses in sync with the lifecycle on every save, so that
        # editing the date/time immediately realigns them (no drift waiting for
        # the cron). Set `_skip_status_recompute = True` to bypass if ever needed.
        if not getattr(self, '_skip_status_recompute', False):
            self.recompute_statuses()
        fields = kwargs.get('update_fields')
        if fields is not None and not {name.removesuffix('_id') for name in fields}.intersection(self._LAYOUT_FIELDS):
            return super().save(*args, **kwargs)
        placement = self._placement_for_save(fields)
        date_changed = (fields is None or {'event', 'event_id', 'date'}.intersection(fields)) and placement._event_date_changed()
        layout_changed = placement._layout_assignment_changed()
        if not date_changed and not layout_changed:
            return super().save(*args, **kwargs)
        with transaction.atomic():
            event = Event.objects.select_for_update().get(pk=placement.event_id) if placement.event_id else None
            if date_changed and event.organizer_location_id:
                event.validate_table_date(placement.date)
            if layout_changed:
                area_id = placement.play_area_id
                placement._validate_layout_assignment(event, lock=True)
                if area_id != placement.play_area_id:
                    self.play_area_id = placement.play_area_id
                    if fields is not None:
                        kwargs['update_fields'] = {*fields, 'play_area'}
            return super().save(*args, **kwargs)

    @property
    def start_datetime(self):
        return datetime.datetime.combine(self.date, self.time)

    @property
    def end_datetime(self):
        """Full end datetime (handles durations that cross midnight)."""
        return self.start_datetime + datetime.timedelta(minutes=self.duration or 0)

    @property
    def end_time(self):
        """End time of the session, derived from start time + duration."""
        return self.end_datetime.time()

    def overlaps_with(self, other):
        """True if this session's time range overlaps another's."""
        return self.start_datetime < other.end_datetime and other.start_datetime < self.end_datetime

    @property
    def google_calendar_url(self):
        import urllib.parse
        start_dt = datetime.datetime.combine(self.date, self.time)
        end_dt = start_dt + datetime.timedelta(minutes=self.duration or 120)
        fmt = "%Y%m%dT%H%M%S"
        params = {
            'action': 'TEMPLATE',
            'text': self.title,
            'dates': f"{start_dt.strftime(fmt)}/{end_dt.strftime(fmt)}",
        }
        if self.description:
            params['details'] = self.description[:500]
        if self.location and self.location.address:
            params['location'] = self.location.address
        return 'https://www.google.com/calendar/render?' + urllib.parse.urlencode(params)

    def __str__(self):
        return self.title

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'get_meta_image',
    }

    def get_meta_title(self):
        if self.game:
            return _("%(game)s - %(date)s - Board-Gamers.com") % {
                'game': self.game.name,
                'date': self.date.strftime('%d/%m/%Y')
            }
        else:
            return _("%(title)s - %(date)s - Board-Gamers.com") % {
                'title': self.title,
                'date': self.date.strftime('%d/%m/%Y')
            }

    def get_meta_description(self):
        context_name = ''
        if self.location:
            context_name = self.location.name
        elif self.event:
            context_name = self.event.name
        if self.game:
            return _("Join the %(game)s table! We'll play on %(date)s at %(time)s at %(location)s") % {
                'game': self.game.name,
                'date': self.date.strftime('%d/%m/%Y'),
                'time': self.time.strftime('%H:%M'),
                'location': context_name,
            }
        else:
            return _("Join the table! We'll play on %(date)s at %(time)s at %(location)s") % {
                'date': self.date.strftime('%d/%m/%Y'),
                'time': self.time.strftime('%H:%M'),
                'location': context_name,
            }

    def get_meta_image(self):
        if self.game:
            return self.game.cover_url
        if self.location:
            return self.location.cover_url
        if self.event:
            return self.event.cover_url
        return None

    def get_absolute_url(self):
        if self.event_id:
            return reverse('event_table_detail',
                           kwargs={'event_slug': self.event.slug, 'table_slug': self.slug})
        return reverse('table-detail', kwargs={'slug': self.slug})

    def structured_data(self, request=None):
        """schema.org/Event JSON-LD payload for a table (a game session), or
        None. Location tables reference their venue Place; event tables link the
        parent event via `superEvent` and inherit its venue as `location`.
        `location` is required by schema.org, so when the venue is unknown (an
        event table whose parent event has no address) we return None and the
        view skips the markup rather than emit a payload Search Console flags."""
        if self.location_id:
            location = self.location.as_schema_place(request)
        elif self.event_id:
            location = self.event.as_schema_place(request)
        else:
            location = None
        if not location:
            return None
        data = {
            '@context': 'https://schema.org',
            '@type': 'Event',
            'name': self.title,
            'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
            'eventStatus': 'https://schema.org/EventScheduled',
            'startDate': self.start_datetime.isoformat(),
            'endDate': self.end_datetime.isoformat(),
            'url': _absolute_url(self.get_absolute_url(), request),
            'location': location,
        }
        if self.event_id:
            data['superEvent'] = {
                '@type': 'Event',
                'name': self.event.name,
                'url': _absolute_url(self.event.get_absolute_url(), request),
            }
        if not self.unlimited_seats:
            data['maximumAttendeeCapacity'] = self.max_players
        description = _plain_text(self.description)
        if description:
            data['description'] = description
        image = self.get_meta_image()
        if image:
            data['image'] = _absolute_url(image, request)
        if self.author and self.author.nickname:
            data['organizer'] = {'@type': 'Organization', 'name': self.author.nickname}
        return data

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(location__isnull=False, event__isnull=True) |
                    models.Q(location__isnull=True, event__isnull=False)
                ),
                name='table_location_xor_event',
            )
        ]


class TableLink(DateTimeModel):
    """An optional external link attached to a Table (rulebook, score sheet,
    video, …). A table can have any number of them."""
    table = models.ForeignKey(
        Table, on_delete=models.CASCADE, related_name='links', verbose_name=_('Table'))
    label = models.CharField(max_length=100, blank=True, verbose_name=_('Label'))
    url = models.URLField(max_length=500, verbose_name=_('URL'))

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.label or self.url

    @property
    def display_label(self):
        """Label to show; falls back to the URL host when no label is set."""
        if self.label:
            return self.label
        netloc = urlparse(self.url).netloc
        return netloc or self.url


class Player(DateTimeModel):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, null=True, blank=True)
    guest_profile = models.ForeignKey(
        GuestProfile, on_delete=models.CASCADE,
        null=True, blank=True, related_name='table_players'
    )
    table = models.ForeignKey(Table, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    position = models.IntegerField(default=99, db_index=True)
    # DB-level default too, so code that predates this column can still insert players
    team = models.CharField(max_length=10, blank=True, default='', db_default='', verbose_name=_('Team'))
    outcome = models.CharField(
        max_length=10, choices=PlayerOutcome.choices, null=True, blank=True, db_index=True,
        verbose_name=_('Outcome'))

    @property
    def display_name(self):
        if self.guest_profile:
            return f"{self.guest_profile.name} (ospite di {self.guest_profile.owner.nickname})"
        return self.user_profile.nickname if self.user_profile else "—"

    @property
    def is_guest(self):
        return self.guest_profile_id is not None

    class Meta:
        verbose_name = "Player"
        verbose_name_plural = "Players"
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user_profile', 'table'],
                condition=models.Q(user_profile__isnull=False),
                name='unique_user_profile_table'
            ),
            models.UniqueConstraint(
                fields=['guest_profile', 'table'],
                condition=models.Q(guest_profile__isnull=False),
                name='unique_guest_profile_table'
            ),
        ]


class Season(DateTimeModel):
    """A leaderboard period of a Location. At most one active (end_date is null) per Location."""
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='seasons', verbose_name=_('Location'))
    name = models.CharField(max_length=100, verbose_name=_('Name'))
    start_date = models.DateField(verbose_name=_('Start date'))
    end_date = models.DateField(null=True, blank=True, verbose_name=_('End date'))

    class Meta:
        verbose_name = _('Season')
        verbose_name_plural = _('Seasons')
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['location'],
                condition=models.Q(end_date__isnull=True),
                name='unique_active_season_per_location',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.location})'


class CommentType(models.TextChoices):
    USER = 'user', _('User Comment')
    SYSTEM = 'system', _('System Comment')


class Comment(DateTimeModel):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey(Table, related_name='comments', on_delete=models.CASCADE, null=True)
    author = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='comments', null=True, blank=True)
    content = models.TextField()
    comment_type = models.CharField(max_length=10, choices=CommentType.choices, default=CommentType.USER)

    def __str__(self):
        return self.content

    class Meta:
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
        ordering = ['-created_at']


class LocationFollower(DateTimeModel):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='followed_locations')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='followers')

    class Meta:
        unique_together = ('user_profile', 'location')
        verbose_name = _('Location Follower')
        verbose_name_plural = _('Location Followers')

    def __str__(self):
        return f"{self.user_profile.nickname} follows {self.location.name}"


class FavoriteUser(DateTimeModel):
    """A user another user marked as favorite: private to `owner`, needs no
    confirmation and sends no notification. Favorites are the quick picks of
    the user picker (e.g. adding players to a table)."""
    owner = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='favorite_users')
    favorite = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='favorited_by')

    class Meta:
        verbose_name = _('Favorite User')
        verbose_name_plural = _('Favorite Users')
        constraints = [
            models.UniqueConstraint(fields=['owner', 'favorite'], name='unique_favorite_user'),
            models.CheckConstraint(condition=~models.Q(owner=models.F('favorite')), name='favorite_user_not_self'),
        ]

    def __str__(self):
        return f"{self.owner.nickname} ★ {self.favorite.nickname}"


class NotificationType(models.TextChoices):
    NEW_TABLE = 'new_table', _('New table created')
    NEW_PLAYER = 'new_player', _('New player joined')
    LEADERBOARD_EDITABLE = 'leaderboard_editable', _('Leaderboard is now editable')
    LEADERBOARD_UPDATED = 'leaderboard_updated', _('Leaderboard updated')
    LEADERBOARD_CLOSED = 'leaderboard_closed', _('Leaderboard closed')
    TABLE_CLOSED = 'table_closed', _('Table closed')
    TABLE_DELETED = 'table_deleted', _('Table deleted')
    NEW_COMMENT = 'new_comment', _('New comment')
    TABLES_ADDED = 'tables_added', _('Added to new sessions')


class Notification(DateTimeModel):
    recipient = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='notifications')
    table = models.ForeignKey(Table, null=True, blank=True, on_delete=models.CASCADE)
    location = models.ForeignKey(Location, null=True, blank=True, on_delete=models.CASCADE)

    subject = models.CharField(max_length=255, blank=True, null=True)
    message = models.TextField(blank=True, null=True)

    notification_type = models.CharField(max_length=50, choices=NotificationType.choices)

    sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    is_read = models.BooleanField(default=False)
    push_sent = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _('Notification')
        verbose_name_plural = _('Notifications')
        ordering = ['-created_at']

    def __str__(self):
        return f"To {self.recipient.nickname} [{self.notification_type}]"


#: Soft check on the Italian fiscal code: shape only (16 chars, letters and
#: digits in the right places), tolerant of "omocodia" codes where digits are
#: replaced by letters. Blank values skip validation, so members without an
#: Italian fiscal code can leave the field empty.
validate_fiscal_code = RegexValidator(
    regex=r'^[A-Z]{6}[0-9A-Z]{2}[A-Z][0-9A-Z]{2}[A-Z][0-9A-Z]{3}[A-Z]$',
    flags=re.IGNORECASE,
    message=_('Enter a valid fiscal code (16 characters), or leave the field empty.'),
)


class Member(DateTimeModel):
    """
    Rappresenta una persona fisica associata a una location.
    Può essere collegata a un UserProfile (utente registrato) oppure no.
    """
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='members',
        verbose_name=_('Location')
    )
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='memberships',
        verbose_name=_('User Profile')
    )

    #: Personal data carried over when the same user joins another location.
    PERSONAL_DATA_FIELDS = (
        'first_name', 'last_name', 'fiscal_code', 'email', 'phone_number',
        'birth_date', 'birth_place', 'nationality',
        'address', 'zip_code', 'city', 'province',
    )
    #: Fields an association needs to fill in the membership form.
    REQUIRED_PERSONAL_DATA_FIELDS = (
        'fiscal_code', 'birth_date', 'birth_place', 'address', 'zip_code', 'city', 'province',
    )

    first_name = models.CharField(max_length=100, verbose_name=_('First Name'))
    last_name = models.CharField(max_length=100, verbose_name=_('Last Name'))
    fiscal_code = models.CharField(
        max_length=16, blank=True, validators=[validate_fiscal_code],
        verbose_name=_('Fiscal Code')
    )
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    phone_number = PhoneNumberField(blank=True, region='IT', verbose_name=_('Phone Number'))

    birth_date = models.DateField(null=True, blank=True, verbose_name=_('Date of Birth'))
    birth_place = models.CharField(max_length=100, blank=True, verbose_name=_('Place of Birth'))
    nationality = models.CharField(max_length=100, blank=True, verbose_name=_('Nationality'))
    address = models.CharField(max_length=200, blank=True, verbose_name=_('Address'))
    zip_code = models.CharField(max_length=10, blank=True, verbose_name=_('ZIP Code'))
    city = models.CharField(max_length=100, blank=True, verbose_name=_('City'))
    province = models.CharField(max_length=2, blank=True, verbose_name=_('Province'))

    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Member')
        verbose_name_plural = _('Members')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    def save(self, *args, **kwargs):
        self.fiscal_code = self.fiscal_code.strip().upper()
        self.province = self.province.strip().upper()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def current_membership(self):
        """The membership that matters right now: the active one, else the latest."""
        return self.active_membership or self.memberships.first()

    @property
    def needs_signed_document(self):
        """True while the member's current membership still lacks the signed form."""
        membership = self.current_membership
        return bool(
            membership
            and membership.status in (Membership.PENDING, Membership.ACTIVE)
            and not membership.signed_document
        )

    @property
    def has_complete_personal_data(self):
        """True when every field the membership form needs is filled in."""
        return all(getattr(self, field) for field in self.REQUIRED_PERSONAL_DATA_FIELDS)

    @classmethod
    def personal_data_from_latest(cls, user_profile):
        """
        Personal data of the most recent Member record of `user_profile`, to
        prefill the form when the same person joins another location.

        Members are per-location, so the data is copied once and then lives
        independently: each location owns its own copy.
        """
        if user_profile is None:
            return {}
        latest = cls.objects.filter(user_profile=user_profile).order_by('-created_at').first()
        if latest is None:
            return {}
        return {field: getattr(latest, field) for field in cls.PERSONAL_DATA_FIELDS}

    @property
    def active_membership(self):
        """Returns the current active membership, or None."""
        import datetime
        return self.memberships.filter(
            status=Membership.ACTIVE,
            end_date__gte=datetime.date.today()
        ).first()


class Membership(DateTimeModel):
    """
    Periodo di validità della membership di un Member per una location.
    """
    PENDING = 'pending'
    ACTIVE = 'active'
    EXPIRED = 'expired'
    REJECTED = 'rejected'

    STATUS_CHOICES = [
        (PENDING, _('Pending')),
        (ACTIVE, _('Active')),
        (EXPIRED, _('Expired')),
        (REJECTED, _('Rejected')),
    ]

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name='memberships',
        verbose_name=_('Member')
    )
    start_date = models.DateField(null=True, blank=True, verbose_name=_('Start Date'))
    end_date = models.DateField(null=True, blank=True, verbose_name=_('End Date'))
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=PENDING,
        db_index=True, verbose_name=_('Status')
    )
    notes = models.TextField(blank=True, verbose_name=_('Notes'))
    #: Set by a manager once the member hands in the signed paper form.
    signed_document = models.BooleanField(
        default=False, verbose_name=_('Signed document received'))
    approved_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_memberships',
        verbose_name=_('Approved By')
    )
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    @classmethod
    def active_for(cls, profile):
        today = timezone.localdate()
        return cls.objects.filter(
            models.Q(start_date__isnull=True) | models.Q(start_date__lte=today),
            models.Q(end_date__isnull=True) | models.Q(end_date__gte=today),
            member__user_profile=profile, status=cls.ACTIVE,
        )

    class Meta:
        verbose_name = _('Membership')
        verbose_name_plural = _('Memberships')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.member} [{self.status}]"


class MembershipDocument(DateTimeModel):
    """
    A blank document a location asks its members to print and sign (membership
    form, privacy notice, statute...). It is downloaded as it is and holds no
    personal data, so it lives on the public media bucket like any other file.
    """
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='membership_documents',
        verbose_name=_('Location')
    )
    name = models.CharField(max_length=200, verbose_name=_('Name'))
    file = models.FileField(
        upload_to='membership-documents',
        verbose_name=_('File')
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Membership Document')
        verbose_name_plural = _('Membership Documents')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.location.name})"

    @property
    def extension(self):
        """Uppercase file extension, for the badge next to the download link."""
        name = self.file.name or ''
        return name.rsplit('.', 1)[-1].upper() if '.' in name else ''


class LocationGameTag(DateTimeModel):
    """A label for the games of a location's library, defined by its managers.
    Internal only: tags are not shown on the public library."""
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='game_tags', verbose_name=_('Location'))
    name = models.CharField(max_length=64, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('Location Game Tag')
        verbose_name_plural = _('Location Game Tags')
        ordering = ['order', 'name']
        unique_together = [('location', 'name')]


class LocationGame(DateTimeModel):
    """
    Represents a game in a location's library.
    Can be owned by the location itself or by a member (socio),
    and can be physically stored at the association or at a member's home.
    """
    class WithdrawalReason(models.TextChoices):
        SOLD = 'sold', _('Sold')
        DESTROYED = 'destroyed', _('Destroyed')
        LOST = 'lost', _('Lost or missing')
        RETURNED_TO_MEMBER = 'returned_to_member', _('Returned to member')
        OTHER = 'other', _('Other')

    OWNED_BY_LOCATION = 'location'
    OWNED_BY_MEMBER = 'member'
    OWNERSHIP_CHOICES = [
        (OWNED_BY_LOCATION, _('Owned by Location')),
        (OWNED_BY_MEMBER, _('Owned by Member')),
    ]

    AT_ASSOCIATION = 'association'
    AT_HOME = 'home'
    PHYSICAL_LOCATION_CHOICES = [
        (AT_ASSOCIATION, _('At the association')),
        (AT_HOME, _("At member's home")),
    ]

    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='location_games',
        verbose_name=_('Location')
    )
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name='location_games',
        verbose_name=_('Game')
    )
    ownership = models.CharField(
        max_length=20, choices=OWNERSHIP_CHOICES, default=OWNED_BY_LOCATION,
        verbose_name=_('Ownership')
    )
    owner_member = models.ForeignKey(
        Member, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='owned_games', verbose_name=_('Owner Member')
    )
    physical_location = models.CharField(
        max_length=20, choices=PHYSICAL_LOCATION_CHOICES, default=AT_ASSOCIATION,
        verbose_name=_('Physical Location')
    )
    is_archived = models.BooleanField(default=False, verbose_name=_('Withdrawn'))
    withdrawn_on = models.DateField(null=True, blank=True, verbose_name=_('Withdrawal date'))
    withdrawal_reason = models.CharField(
        max_length=20, choices=WithdrawalReason.choices, blank=True, verbose_name=_('Withdrawal reason'))
    withdrawal_note = models.TextField(blank=True, verbose_name=_('Withdrawal note'))
    notes = models.TextField(blank=True, verbose_name=_('Notes'))
    tags = models.ManyToManyField(
        LocationGameTag, related_name='games', blank=True, verbose_name=_('Tags'))
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Location Game')
        verbose_name_plural = _('Location Games')
        unique_together = ('location', 'game')
        ordering = ['game__name']

    @property
    def has_withdrawal_details(self):
        return bool(self.withdrawn_on or self.withdrawal_reason or self.withdrawal_note)

    @property
    def is_lendable(self):
        return (not self.is_archived and self.ownership == self.OWNED_BY_LOCATION
                and self.physical_location == self.AT_ASSOCIATION)

    def __str__(self):
        return f"{self.game.name} @ {self.location.name}"


def delete_game_loan_member(collector, field, sub_objs, using):
    """Keep the borrower for open loans and anonymize returned loans."""
    models.RESTRICT(collector, field, sub_objs.filter(returned_at__isnull=True), using)
    returned = sub_objs.filter(returned_at__isnull=False)
    for actor in ('loaned_by', 'returned_by'):
        # A self-service loan can also identify the borrower as its operator.
        loan_ids = list(returned.filter(**{actor: models.F('member__user_profile')}).values_list('pk', flat=True))
        if loan_ids:
            collector.add_field_update(field.model._meta.get_field(actor), None, sub_objs.filter(pk__in=loan_ids))
    models.SET_NULL(collector, field, returned, using)


class LocationGameLoan(DateTimeModel):
    # Collect the loans when deleting their location, including those that restrict
    # deleting the game or member individually.
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='game_loans', verbose_name=_('Location'))
    location_game = models.ForeignKey(
        LocationGame, on_delete=models.RESTRICT, related_name='loans', verbose_name=_('Location Game'),
    )
    member = models.ForeignKey(
        Member, on_delete=delete_game_loan_member, null=True, blank=True,
        related_name='game_loans', verbose_name=_('Member'),
    )
    loaned_at = models.DateTimeField(default=timezone.now, verbose_name=_('Loaned at'))
    due_date = models.DateField(verbose_name=_('Due date'))
    returned_at = models.DateTimeField(null=True, blank=True, verbose_name=_('Returned at'))
    loaned_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recorded_game_loans', verbose_name=_('Loan recorded by'),
    )
    returned_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recorded_game_returns', verbose_name=_('Return recorded by'),
    )
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)

    class Meta:
        verbose_name = _('Location Game Loan')
        verbose_name_plural = _('Location Game Loans')
        ordering = ['-loaned_at', '-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['location_game'], condition=models.Q(returned_at__isnull=True),
                name='unique_open_loan_per_location_game',
            ),
            models.CheckConstraint(
                condition=models.Q(returned_at__isnull=True) | models.Q(returned_at__gte=models.F('loaned_at')),
                name='game_loan_return_after_checkout',
            ),
            models.CheckConstraint(
                condition=models.Q(returned_at__isnull=False) | models.Q(member__isnull=False),
                name='open_game_loan_has_member',
            ),
        ]

    @property
    def is_overdue(self):
        return self.returned_at is None and self.due_date < timezone.localdate()

    def __str__(self):
        return f'{self.location_game} ({self.loaned_at:%Y-%m-%d})'


class TelegramGroupConfig(DateTimeModel):
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='telegram_configs',
        verbose_name=_('Location')
    )
    chat_id = models.BigIntegerField(unique=True, verbose_name=_('Chat ID'))
    chat_title = models.CharField(max_length=255, blank=True, verbose_name=_('Chat title'))
    message_thread_id = models.BigIntegerField(null=True, blank=True, verbose_name=_('Message thread ID'))
    message_thread_title = models.CharField(max_length=255, blank=True, verbose_name=_('Message thread title'))
    active = models.BooleanField(default=True, verbose_name=_('Active'))

    class Meta:
        verbose_name = _('Telegram Group Config')
        verbose_name_plural = _('Telegram Group Configs')

    def __str__(self):
        return f"{self.location.name} — {self.chat_title or self.chat_id}"


class TelegramSetupToken(DateTimeModel):
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='telegram_tokens',
        verbose_name=_('Location')
    )
    token = models.CharField(max_length=64, unique=True, verbose_name=_('Token'))
    expires_at = models.DateTimeField(verbose_name=_('Expires at'))
    used = models.BooleanField(default=False, verbose_name=_('Used'))

    class Meta:
        verbose_name = _('Telegram Setup Token')
        verbose_name_plural = _('Telegram Setup Tokens')

    def __str__(self):
        return f"{self.location.name} — {self.token[:8]}…"

    @property
    def is_valid(self):
        from django.utils import timezone
        return not self.used and self.expires_at > timezone.now()


def validate_banner_link(value):
    if value.startswith('/') and url_has_allowed_host_and_scheme(value, allowed_hosts=set()):
        return
    URLValidator(schemes=['http', 'https'])(value)


class BannerQuerySet(models.QuerySet):
    def visible(self, *, authenticated, home, at=None):
        at = at or timezone.now()
        audiences = [Banner.Audience.EVERYONE,
                     Banner.Audience.AUTHENTICATED if authenticated else Banner.Audience.ANONYMOUS]
        placements = [Banner.Placement.SITE]
        if home:
            placements.append(Banner.Placement.HOME)
        return self.filter(is_active=True, audience__in=audiences, placement__in=placements).filter(
            models.Q(starts_at__isnull=True) | models.Q(starts_at__lte=at),
            models.Q(ends_at__isnull=True) | models.Q(ends_at__gt=at),
        )


class Banner(DateTimeModel):
    class Audience(models.TextChoices):
        EVERYONE = 'everyone', _('Everyone')
        ANONYMOUS = 'anonymous', _('Anonymous visitors')
        AUTHENTICATED = 'authenticated', _('Authenticated users')

    class Placement(models.TextChoices):
        HOME = 'home', _('Home page')
        SITE = 'site', _('All pages')

    class Dismissal(models.TextChoices):
        PERMANENT = 'permanent', _('Permanently')
        DAYS = 'days', _('For a number of days')

    key = models.SlugField(_('Identifier'), max_length=80, unique=True)
    version = models.PositiveIntegerField(_('Version'), default=1, validators=[MinValueValidator(1)],
                                         help_text=_('Increase only to show a substantially new message again.'))
    title = models.CharField(_('Title'), max_length=150, blank=True)
    message = models.TextField(_('Message'))
    cover = ManagedImageField(_('Cover'), upload_to='banners/', blank=True, max_side=COVER_MAX_SIDE)
    cover_alt = models.CharField(_('Cover description'), max_length=200, blank=True,
                                 help_text=_('Leave empty if the image is decorative.'))
    action_label = models.CharField(_('Link text'), max_length=100, blank=True)
    action_url = models.CharField(_('Link URL'), max_length=500, blank=True, validators=[validate_banner_link],
                                  help_text=_('An internal path starting with / or an http(s) URL.'))
    is_active = models.BooleanField(_('Active'), default=False, db_index=True)
    audience = models.CharField(_('Audience'), max_length=20, choices=Audience.choices, default=Audience.EVERYONE)
    placement = models.CharField(_('Display on'), max_length=10, choices=Placement.choices, default=Placement.HOME)
    priority = models.PositiveIntegerField(_('Priority'), default=0, help_text=_('Higher values are shown first.'))
    starts_at = models.DateTimeField(_('Visible from'), null=True, blank=True)
    ends_at = models.DateTimeField(_('Visible until'), null=True, blank=True)
    dismissal = models.CharField(_('Hide after closing'), max_length=10, choices=Dismissal.choices,
                                 default=Dismissal.PERMANENT)
    dismissal_days = models.PositiveIntegerField(_('Days hidden after closing'), null=True, blank=True,
                                                 validators=[MinValueValidator(1)])

    objects = BannerQuerySet.as_manager()

    class Meta:
        verbose_name = _('Banner')
        verbose_name_plural = _('Banners')
        ordering = ['-priority', 'pk']

    def __str__(self):
        return self.title or self.key

    def clean(self):
        super().clean()
        errors = {}
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors['ends_at'] = _('The end must be after the start.')
        if self.dismissal == self.Dismissal.DAYS and not self.dismissal_days:
            errors['dismissal_days'] = _('Enter how many days the banner should remain hidden.')
        # The forms only have the translated fields, so the errors go on those.
        labels = {name: getattr(self, name) for name in
                  (f'action_label_{language}' for language, _name in settings.LANGUAGES)}
        if self.action_url:
            errors.update({name: _('Enter the link text.') for name, label in labels.items() if not label})
        elif any(labels.values()):
            errors['action_url'] = _('Enter the link URL.')
        if errors:
            raise ValidationError(errors)

    @property
    def action_href(self):
        if not self.action_url:
            return ''
        try:
            validate_banner_link(self.action_url)
        except ValidationError:
            return ''
        if self.action_url.startswith('/'):
            language = get_language()
            with translation.override(settings.LANGUAGE_CODE):
                return translate_url(self.action_url, language)
        return self.action_url


class FAQCategory(DateTimeModel):
    name = models.CharField(max_length=100, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    class Meta:
        verbose_name = _('FAQ Category')
        verbose_name_plural = _('FAQ Categories')
        ordering = ['order']

    def __str__(self):
        return self.name or ''


class FAQ(DateTimeModel):
    category = models.ForeignKey(
        FAQCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='faqs', verbose_name=_('Category')
    )
    question = models.CharField(max_length=500, verbose_name=_('Question'))
    answer = models.TextField(verbose_name=_('Answer'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'))

    class Meta:
        verbose_name = _('FAQ')
        verbose_name_plural = _('FAQ')
        ordering = ['category__order', 'order']

    def __str__(self):
        return self.question or ''


class EventQuerySet(models.QuerySet):
    def managed_by(self, profile):
        if not profile:
            return self.none()
        legacy_staff = models.Q(organizer_location__isnull=True) & (
            models.Q(creator=profile) | models.Q(managers=profile)
        )
        return self.filter(legacy_staff | models.Q(organizer_location__creator=profile)
                           | models.Q(organizer_location__managers=profile)).distinct()


class Event(DateTimeModel, ModelMeta, SlugModel):
    objects = EventQuerySet.as_manager()
    # Managers publish their own events. Only an admin can block one, and a
    # blocked event can't be published again from the management pages.
    DRAFT = 'draft'
    PUBLISHED = 'published'
    BLOCKED = 'blocked'
    STATUS_CHOICES = [
        (DRAFT, _('Draft')),
        (PUBLISHED, _('Published')),
        (BLOCKED, _('Blocked')),
    ]

    slug_field_name = 'name'
    name = models.CharField(max_length=255, verbose_name=_('Name'))
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)
    description = models.TextField(blank=True, verbose_name=_('Description'))
    cover = ManagedImageField(
        upload_to='event-covers', null=True, blank=True, max_side=COVER_MAX_SIDE,
        verbose_name=_('Cover'))

    CATALOG_LOCATION = 'location'
    CATALOG_SELECTED = 'selected'
    catalog_mode = models.CharField(
        max_length=12, blank=True, default='', db_default='',
        choices=[
            ('', _('Automatic for the venue')),
            (CATALOG_LOCATION, _('Organizing location library')),
            (CATALOG_SELECTED, _('Event selection')),
        ],
        verbose_name=_('Game catalog'),
    )

    class LayoutMode(models.TextChoices):
        EVENT = 'event', _('Event layout')
        VENUE = 'venue', _('Venue layout')

    layout_mode = models.CharField(
        max_length=5, choices=LayoutMode.choices, default=LayoutMode.EVENT, db_default=LayoutMode.EVENT,
        verbose_name=_('Play areas and stations'),
    )

    # PROTECT also stops the deletion of the profile that created the location
    # (Location.creator cascades): reassign its events first.
    organizer_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name='organized_events', null=True, blank=True,
        verbose_name=_('Organizing location'),
    )
    venue_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name='events_at_venue', null=True, blank=True,
        verbose_name=_('Venue location'),
    )
    venue_name = models.CharField(max_length=255, blank=True, default='', db_default='', verbose_name=_('Venue name'))
    address = models.CharField(max_length=255, null=True, blank=True, verbose_name=_('Address'))
    city = models.CharField(max_length=144, null=True, blank=True, verbose_name=_('City'))
    latitude = models.CharField(max_length=25, null=True, blank=True)
    longitude = models.CharField(max_length=25, null=True, blank=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    phone = PhoneNumberField(null=True, blank=True, region='IT', verbose_name=_('Phone'))
    email = models.EmailField(null=True, blank=True, verbose_name=_('Email'))

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=DRAFT, verbose_name=_('Status'))

    creator = models.ForeignKey(
        'UserProfile', on_delete=models.SET_NULL, related_name='created_events',
        null=True, blank=True, verbose_name=_('Creator'))
    managers = models.ManyToManyField(
        'UserProfile', related_name='managed_events', blank=True, verbose_name=_('Managers'))
    sponsor_locations = models.ManyToManyField(
        Location, related_name='sponsored_events', blank=True, verbose_name=_('Sponsor locations'))
    allowed_table_creators = models.ManyToManyField(
        'UserProfile', related_name='event_table_creation_allowed', blank=True,
        verbose_name=_('Additional table creators'))
    leaderboard_enabled = models.BooleanField(
        default=True, verbose_name=_('Leaderboard'),
        help_text=_('When off, the tables of this event have no leaderboard.'))
    # Lets visitors browse the game library (EventGame) from the event page.
    enable_public_games = models.BooleanField(
        # DB-level default too, so code that predates this column can still insert events
        default=False, db_default=False, verbose_name=_('Public game library'))
    # When off, the program page is reserved to managers and the event page shows
    # no link to it.
    table_booking_enabled = models.BooleanField(
        default=True, db_default=True, verbose_name=_('Table booking'))
    # Optional button shown first among the event page cards (e.g. the organizers'
    # own program or ticket shop). Hidden unless both title and URL are set.
    custom_button_title = models.CharField(
        max_length=80, blank=True, default='', db_default='', verbose_name=_('Button title'))
    custom_button_subtitle = models.CharField(
        max_length=160, blank=True, default='', db_default='', verbose_name=_('Button subtitle'))
    custom_button_url = models.URLField(
        max_length=500, blank=True, default='', db_default='', verbose_name=_('Button link'))

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'cover_url',
    }

    def get_meta_title(self):
        return _("%(name)s - Board-Gamers.com") % {'name': self.name}

    def get_meta_description(self):
        description = _plain_text(self.description)
        if description:
            return description
        return _("%(name)s — gaming event") % {'name': self.name}

    @cached_property
    def cover_url(self):
        if self.cover and hasattr(self.cover, 'url'):
            return self.cover.url
        if self.organizer_location_id:
            return self.organizer_location.cover_url
        return settings.STATIC_URL + settings.DEFAULT_LOCATION_COVER_URL

    @property
    def venue(self):
        return self.venue_location or self

    @property
    def venue_label(self):
        if self.venue_location_id:
            return self.venue_location.name
        return self.venue_name or self.city or self.address or ''

    def structured_data(self, request=None):
        """schema.org/Event JSON-LD payload for search-engine rich results, or
        None. `startDate` and `location` are required by schema.org; when either
        is unknown (undated event, or no venue address) we return None so the
        view skips the markup rather than emit an invalid payload that Search
        Console flags. Relative URLs are made absolute from `request` when
        available, else from settings.DOMAIN_URL (S3 media URLs are already
        absolute)."""
        place = self.as_schema_place(request)
        if not self.start_date or not place:
            return None
        data = {
            '@context': 'https://schema.org',
            '@type': 'Event',
            'name': self.name,
            'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
            'eventStatus': 'https://schema.org/EventScheduled',
            'url': _absolute_url(self.get_absolute_url(), request),
            'startDate': self.start_date.isoformat(),
            'location': place,
        }
        if self.end_date:
            data['endDate'] = self.end_date.isoformat()
        description = _plain_text(self.description)
        if description:
            data['description'] = description
        if self.cover:
            data['image'] = _absolute_url(self.cover_url, request)
        if self.organizer_location_id:
            data['organizer'] = {'@type': 'Organization', 'name': self.organizer_location.name}
        elif self.creator and self.creator.nickname:
            data['organizer'] = {'@type': 'Organization', 'name': self.creator.nickname}
        return data

    def as_schema_place(self, request=None):
        """schema.org/Place fragment for this event's venue, or None if unknown.
        Embeddable as the `location` of the event and of its tables. A venue
        without an address falls back to the address of the event."""
        venue = self.venue_location
        if venue and (venue.address or venue.city):
            return venue.as_schema_place(request)
        if not (self.address or self.city):
            return None
        place = {'@type': 'Place', 'name': venue.name if venue else self.venue_name or self.city or self.name}
        postal = {'@type': 'PostalAddress'}
        if self.address:
            postal['streetAddress'] = self.address
        if self.city:
            postal['addressLocality'] = self.city
        place['address'] = postal
        if self.latitude and self.longitude:
            place['geo'] = {
                '@type': 'GeoCoordinates',
                'latitude': self.latitude,
                'longitude': self.longitude,
            }
        return place

    @property
    def is_at_organizer_location(self):
        return self.organizer_location_id is not None and self.organizer_location_id == self.venue_location_id

    _LAYOUT_FIELDS = ('layout_mode', 'organizer_location', 'venue_location')

    def layout_owner(self):
        if self.layout_mode == self.LayoutMode.VENUE:
            return {'location_id': self.venue_location_id} if self.is_at_organizer_location else None
        return {'event_id': self.pk} if self.pk else None

    def effective_play_areas(self):
        owner = self.layout_owner()
        return PlayArea.objects.filter(**owner) if owner else PlayArea.objects.none()

    def effective_physical_tables(self):
        owner = self.layout_owner()
        return PhysicalTable.objects.filter(**owner) if owner else PhysicalTable.objects.none()

    def _validate_layout_change(self, previous, fields=None):
        def proposed(name):
            source = self if fields is None or name in fields or name.removesuffix('_id') in fields else previous
            return getattr(source, name)

        mode = proposed('layout_mode')
        organizer = proposed('organizer_location_id')
        venue = proposed('venue_location_id')
        if mode == self.LayoutMode.VENUE and (organizer is None or organizer != venue):
            raise ValidationError(_('Only events held at their organizing location can use the venue layout.'))
        if previous is None or (previous.layout_mode == mode and
                (mode == self.LayoutMode.EVENT or previous.venue_location_id == venue)):
            return

        field, owner_id = ('location_id', venue) if mode == self.LayoutMode.VENUE else ('event_id', self.pk)
        assigned = self.tables.filter(date__gte=timezone.localdate()).filter(
            (models.Q(play_area__isnull=False) & ~models.Q(**{f'play_area__{field}': owner_id})) |
            (models.Q(physical_table__isnull=False) & ~models.Q(**{f'physical_table__{field}': owner_id}))
        ).order_by('date', 'time', 'pk')
        titles = list(assigned.values_list('title', flat=True)[:6])
        if titles:
            sessions = ', '.join(titles[:5]) + (' …' if len(titles) > 5 else '')
            raise ValidationError(_('Reassign these upcoming sessions before changing the layout: %(sessions)s') % {
                'sessions': sessions,
            })

    def clean(self):
        super().clean()
        previous = Event.objects.filter(pk=self.pk).only(*self._LAYOUT_FIELDS).first() if self.pk else None
        self._validate_layout_change(previous)

    def get_absolute_url(self):
        return reverse('event_detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if self.latitude and self.longitude:
            self.point = Point(float(self.longitude), float(self.latitude), srid=4326)
        with transaction.atomic():
            update_fields = kwargs.get('update_fields')
            if update_fields is None or {name.removesuffix('_id') for name in update_fields}.intersection(self._LAYOUT_FIELDS):
                previous = None
                if self.pk:
                    previous = Event.objects.select_for_update().filter(pk=self.pk).only(*self._LAYOUT_FIELDS).first()
                self._validate_layout_change(previous, update_fields if previous else None)
            super().save(*args, **kwargs)
            # The sources of the selected games belong to the organizing location.
            if update_fields is None or {'organizer_location', 'organizer_location_id'} & set(update_fields):
                stale = self.games.filter(source_location_game__isnull=False)
                if self.organizer_location_id:
                    stale = stale.exclude(source_location_game__location_id=self.organizer_location_id)
                stale.update(source_location_game=None)

    def is_manager(self, user_profile):
        if self.organizer_location_id:
            return self.organizer_location.is_manager(user_profile)
        return bool(user_profile and (self.creator_id == user_profile.pk or user_profile in self.managers.all()))

    def can_create_table(self, user_profile):
        return self.is_manager(user_profile) or (
            not self.organizer_location_id and user_profile in self.allowed_table_creators.all()
        )

    @property
    def is_published(self):
        return self.status == self.PUBLISHED

    @property
    def uses_location_library(self):
        return self.organizer_location_id is not None and (
            self.catalog_mode == self.CATALOG_LOCATION or (not self.catalog_mode and self.is_at_organizer_location)
        )

    @property
    def catalog_is_public(self):
        return self.enable_public_games and (
            not self.uses_location_library or self.organizer_location.enable_public_games
        )

    def can_view_catalog(self, user):
        return (self.is_published and self.catalog_is_public) or (
            user.is_authenticated and (user.is_superuser or self.is_manager(user.user_profile))
        )

    def validate_table_date(self, date):
        if not self.dates.filter(date=date).exists():
            raise ValidationError(_('Choose one of the event dates.'))

    def missing_publish_requirements(self):
        """What the event still lacks before it can be published: an undated event
        wouldn't show up in the event list, and an empty page tells visitors nothing."""
        missing = []
        if not self.dates.exists():
            missing.append(_('Add at least one date'))
        if self.organizer_location_id:
            if not self.venue_location_id and not all(
                    value not in (None, '') for value in (self.venue_name, self.address, self.latitude, self.longitude)):
                missing.append(_('Choose a venue or enter its name, address and coordinates'))
            if self.dates.filter(models.Q(opening_time__isnull=True) | models.Q(closing_time__isnull=True)).exists():
                missing.append(_('Set opening and closing times for each date'))
        if not self.description.strip():
            missing.append(_('Write a description'))
        return missing

    def can_view_program(self, user):
        """The program is public while table booking is on; otherwise only the
        event managers and superusers can open it."""
        if self.table_booking_enabled:
            return True
        return user.is_authenticated and (user.is_superuser or self.is_manager(user.user_profile))

    @cached_property
    def sorted_dates(self):
        # Uses the prefetched `dates` cache when available (EventDate.Meta already
        # orders by date, but sort defensively to stay correct without prefetch).
        return sorted(self.dates.all(), key=lambda d: d.date)

    @property
    def start_date(self):
        dates = self.sorted_dates
        return dates[0].date if dates else None

    @property
    def end_date(self):
        dates = self.sorted_dates
        return dates[-1].date if dates else None

    def is_upcoming(self, today=None):
        """True if the event has at least one date today or in the future."""
        if today is None:
            today = timezone.localdate()
        return any(d.date >= today for d in self.sorted_dates)

    def is_concluded(self, today=None):
        """True if the event has dates and all of them are in the past.

        An event without any date is not considered concluded (it is simply
        undated / still being set up).
        """
        if today is None:
            today = timezone.localdate()
        dates = self.sorted_dates
        return bool(dates) and all(d.date < today for d in dates)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('Event')
        verbose_name_plural = _('Events')
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=(~models.Q(layout_mode='venue') | models.Q(
                    organizer_location__isnull=False, venue_location__isnull=False,
                    organizer_location=models.F('venue_location'),
                )),
                name='event_venue_layout_requires_organizer_venue',
            ),
        ]


class PlayArea(DateTimeModel):
    """A room or zone where tables are played, owned by an event or a location."""
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='play_areas',
        null=True, blank=True, verbose_name=_('Event'))
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='play_areas',
        null=True, blank=True, verbose_name=_('Location'))
    name = models.CharField(max_length=144, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        owner = self.event or self.location
        return f"{owner.name} — {self.name}"

    class Meta:
        verbose_name = _('Play Area')
        verbose_name_plural = _('Play Areas')
        ordering = ['order', 'name']
        unique_together = [('event', 'name'), ('location', 'name')]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(event__isnull=False, location__isnull=True)
                    | models.Q(event__isnull=True, location__isnull=False)
                ),
                name='playarea_event_xor_location',
            ),
        ]


class EventDate(DateTimeModel):
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='dates', verbose_name=_('Event'))
    date = models.DateField(verbose_name=_('Date'))
    opening_time = models.TimeField(null=True, blank=True, verbose_name=_('Opening time'))
    closing_time = models.TimeField(null=True, blank=True, verbose_name=_('Closing time'))

    def check_removal(self, *, replacing=False, removed=None):
        if self.event.tables.filter(date=self.date).exists():
            raise ValidationError(_('Move the tables scheduled on this date first.'))
        if not replacing and self.event.is_published and not self.event.dates.exclude(
                pk__in=removed if removed is not None else [self.pk]).exists():
            raise ValidationError(_('A published event needs at least one date.'))

    def save(self, *args, **kwargs):
        with transaction.atomic():
            Event.objects.select_for_update().get(pk=self.event_id)
            if self.pk:
                old = EventDate.objects.get(pk=self.pk)
                if old.event_id != self.event_id:
                    raise ValidationError(_('An event date cannot change event.'))
                if old.date != self.date and old.event.organizer_location_id:
                    old.check_removal(replacing=True)
            return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.event.name} — {self.date}"

    class Meta:
        verbose_name = _('Event Date')
        verbose_name_plural = _('Event Dates')
        ordering = ['date']
        unique_together = [('event', 'date')]


class EventTableCategory(DateTimeModel):
    """A per-event table category ("tipologia"), e.g. wargames, RPG, retrogaming.
    Defined by event managers and assigned to the event's tables."""
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='table_categories', verbose_name=_('Event'))
    name = models.CharField(max_length=144, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        return f"{self.event.name} — {self.name}"

    class Meta:
        verbose_name = _('Event Table Category')
        verbose_name_plural = _('Event Table Categories')
        ordering = ['order', 'name']
        unique_together = [('event', 'name')]


class EventGameTag(DateTimeModel):
    """A label for the games of an event's library, defined by its managers.
    Games with a tag flagged `show_on_event_page` are featured on the event page."""
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='game_tags', verbose_name=_('Event'))
    name = models.CharField(max_length=64, verbose_name=_('Name'))
    show_on_event_page = models.BooleanField(default=False, verbose_name=_('Show on the event page'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = _('Event Game Tag')
        verbose_name_plural = _('Event Game Tags')
        ordering = ['order', 'name']
        unique_together = [('event', 'name')]


class EventGame(DateTimeModel):
    """A selected title keeps its identity when the organizer rearranges its inventory."""
    source_location_game = models.ForeignKey(
        LocationGame, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='event_selections', verbose_name=_('Source in the organizing library'),
    )

    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='games', verbose_name=_('Event'))
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name='event_games', verbose_name=_('Game'))
    tags = models.ManyToManyField(
        EventGameTag, related_name='games', blank=True, verbose_name=_('Tags'))
    sponsor_locations = models.ManyToManyField(
        Location, related_name='event_games', blank=True, verbose_name=_('Sponsor locations'))
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    def clean(self):
        super().clean()
        if self.source_location_game_id and self.event_id and (
                self.source_location_game.game_id != self.game_id or
                self.source_location_game.location_id != self.event.organizer_location_id):
            raise ValidationError({'source_location_game': _('Choose this title from the organizing location.')})

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.game.name} @ {self.event.name}"

    class Meta:
        verbose_name = _('Event Game')
        verbose_name_plural = _('Event Games')
        unique_together = [('event', 'game')]
        ordering = ['game__name']


def clear_unreserved_station_area(collector, field, sub_objs, using):
    # Older sessions may store only the station. Protect its area in that case too.
    sessions = Table.objects.using(using).filter(
        physical_table__in=sub_objs, event__isnull=False, date__gte=timezone.localdate(),
    )
    models.RESTRICT(collector, Table._meta.get_field('physical_table'), sessions, using)
    models.SET_NULL(collector, field, sub_objs, using)


class PhysicalTable(DateTimeModel):
    """A physical playing station ("postazione") at an event or a location — e.g.
    Table 1, 2, 3. Belongs to exactly one of the two, like PlayArea.

    Game sessions (Table) can be assigned to a station for a time slot. A station
    can exist without any session (free / game-lending stations).
    """
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='physical_tables',
        null=True, blank=True, verbose_name=_('Event'))
    location = models.ForeignKey(
        Location, on_delete=models.CASCADE, related_name='physical_tables',
        null=True, blank=True, verbose_name=_('Location'))
    play_area = models.ForeignKey(
        PlayArea, on_delete=clear_unreserved_station_area, related_name='physical_tables',
        null=True, blank=True, verbose_name=_('Play Area'))
    name = models.CharField(max_length=144, verbose_name=_('Name'),
                            help_text=_('On-site label, e.g. "Table 1"'))
    is_visible = models.BooleanField(default=True, verbose_name=_('Selectable by all users'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def clean(self):
        super().clean()
        if self.play_area_id and (self.play_area.event_id, self.play_area.location_id) != (self.event_id, self.location_id):
            raise ValidationError({'play_area': _('Choose a play area from this station’s layout.')})
        if self.pk and self.tables.filter(event__isnull=False, date__gte=timezone.localdate()).exists():
            if not PhysicalTable.objects.filter(pk=self.pk, event_id=self.event_id, location_id=self.location_id).exists():
                raise ValidationError(_('Reassign upcoming event sessions before transferring this station.'))

    def save(self, *args, **kwargs):
        fields = kwargs.get('update_fields')
        if self._state.adding or (fields is not None and not {'play_area', 'play_area_id'}.intersection(fields)):
            return super().save(*args, **kwargs)
        with transaction.atomic():
            if self.play_area_id:
                PlayArea.objects.select_for_update().only('pk').get(pk=self.play_area_id)
            old_area = PhysicalTable.objects.select_for_update().values_list('play_area_id', flat=True).get(pk=self.pk)
            super().save(*args, **kwargs)
            if old_area != self.play_area_id:
                self.tables.exclude(play_area_id=self.play_area_id).update(play_area_id=self.play_area_id)

    def __str__(self):
        owner = self.event or self.location
        return f"{owner.name} — {self.name}"

    class Meta:
        verbose_name = _('Station')
        verbose_name_plural = _('Stations')
        ordering = ['order', 'name']
        unique_together = [('event', 'name'), ('location', 'name')]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(event__isnull=False, location__isnull=True)
                    | models.Q(event__isnull=True, location__isnull=False)
                ),
                name='physicaltable_event_xor_location',
            ),
        ]


class EventParticipant(DateTimeModel):
    """A user registered to attend an event ("iscritto all'evento").

    Created either via the event "Partecipa" button or automatically when a user
    joins a table belonging to the event.
    """
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='participants', verbose_name=_('Event'))
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name='event_participations',
        verbose_name=_('User'))

    def __str__(self):
        return f"{self.user_profile.nickname} @ {self.event.name}"

    class Meta:
        verbose_name = _('Event Participant')
        verbose_name_plural = _('Event Participants')
        ordering = ['-created_at']
        unique_together = [('event', 'user_profile')]


class PushSubscription(DateTimeModel):
    """Stores a browser Web Push subscription for a user."""
    user_profile = models.ForeignKey(
        UserProfile, on_delete=models.CASCADE, related_name='push_subscriptions')
    endpoint = models.TextField()
    p256dh = models.TextField()
    auth = models.TextField()

    class Meta:
        verbose_name = _('Push Subscription')
        verbose_name_plural = _('Push Subscriptions')
        # Every page load re-sends the browser's subscription, so concurrent requests
        # (two tabs) could otherwise both insert the same endpoint.
        constraints = [
            models.UniqueConstraint(
                fields=['user_profile', 'endpoint'], name='unique_push_subscription_per_user'),
        ]

    def __str__(self):
        return f"{self.user_profile.nickname} — {self.endpoint[:60]}"
