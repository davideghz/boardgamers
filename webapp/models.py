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
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.functional import cached_property
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from meta.models import ModelMeta
from model_utils import FieldTracker
from phonenumber_field.modelfields import PhoneNumberField
from webapp.storage_backends import PublicMediaStorage


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


class DateTimeModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta(object):
        abstract = True


class SlugModel(models.Model):
    slug_field_name = None
    random_string_length = 6

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
        base_slug = slugify(self.get_slug_source_value())
        qs = self.__class__.objects.filter(slug=base_slug)
        if self.pk:
            qs = qs.exclude(pk=self.pk)
        if not qs.exists():
            return base_slug
        while True:
            candidate = f"{base_slug}-{self.generate_random_string()}"
            if not self.__class__.objects.filter(slug=candidate).exclude(pk=self.pk or 0).exists():
                return candidate

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            original_slug = slugify(getattr(original, self.slug_field_name))
            current_slug = slugify(self.get_slug_source_value())
            if original_slug != current_slug:
                self.slug = self.create_unique_slug()
        else:
            self.slug = self.create_unique_slug()
        super().save(*args, **kwargs)


class Game(DateTimeModel, ModelMeta, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    image = models.ImageField(upload_to='games', null=True, blank=True, storage=PublicMediaStorage())
    description = models.TextField()
    bgg_code = models.CharField(max_length=20, null=True, blank=True, verbose_name='BGG Code')
    min_players = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Minimum players'))
    max_players = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Maximum players'))
    min_playtime = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Min playtime (minutes)'))
    max_playtime = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name=_('Max playtime (minutes)'))
    weight = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True, verbose_name=_('Weight'))
    year_published = models.SmallIntegerField(null=True, blank=True, verbose_name=_('Year published'))

    leaderboard_enabled = models.BooleanField(default=False, db_index=True)
    bgg_imported = models.BooleanField(default=False, db_index=True)
    verified = models.BooleanField(default=False, db_index=True)

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
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    creator = models.ForeignKey('UserProfile', on_delete=models.CASCADE, related_name='locations', null=True, blank=True)
    managers = models.ManyToManyField('UserProfile', related_name='managed_locations', blank=True)
    description = models.TextField()
    cover = models.ImageField(upload_to='location-covers', null=True, blank=True, storage=PublicMediaStorage())
    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=144, null=True, blank=True)
    latitude = models.CharField(max_length=25, null=True, blank=True)
    longitude = models.CharField(max_length=25, null=True, blank=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    is_public = models.BooleanField(default=True)
    show_tables_in_homepage = models.BooleanField(default=True)
    enable_membership = models.BooleanField(default=False)
    enable_calendar = models.BooleanField(default=False)
    website = models.URLField(null=True, blank=True)
    opening_hours = models.JSONField(null=True, blank=True)
    default_table_time = models.TimeField(
        default=datetime.time(20, 30),
        null=False,
        blank=True,
        verbose_name=_('Default table time'),
        help_text=_('Default start time used when creating new tables at this location.'),
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

    def save(self, *args, **kwargs):
        if self.latitude and self.longitude:
            self.point = Point(float(self.longitude), float(self.latitude), srid=4326)
        super().save(*args, **kwargs)


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
    avatar = models.ImageField(upload_to='avatars', null=True, blank=True, storage=PublicMediaStorage())
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


class Table(DateTimeModel, ModelMeta, SlugModel):
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
    PHASE_RECENTLY_ENDED = 'recently_ended'  # 12h–2 days after start
    PHASE_ARCHIVED = 'archived'              # more than 2 days after start

    # Each phase maps to (table_status, leaderboard_status). Keeping both in one
    # map is the common approach: change the lifecycle here and both stay in sync.
    _PHASE_STATUS_MAP = {
        PHASE_UPCOMING:       (OPEN,    LEADERBOARD_NOT_EDITABLE),
        PHASE_LIVE:           (ONGOING, LEADERBOARD_EDITABLE),
        PHASE_RECENTLY_ENDED: (CLOSED,  LEADERBOARD_EDITABLE),
        PHASE_ARCHIVED:       (CLOSED,  LEADERBOARD_NOT_EDITABLE),
    }
    LIVE_WINDOW = datetime.timedelta(hours=12)
    ARCHIVE_AFTER = datetime.timedelta(days=2)

    slug_field_name = 'title'
    title = models.CharField(max_length=144, null=False, blank=True, verbose_name=_('Title'))
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    tracker = FieldTracker(fields=['status', 'leaderboard_status'])

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
        on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Play Area'))
    category = models.ForeignKey(
        'EventTableCategory',
        on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Category'))
    physical_table = models.ForeignKey(
        'PhysicalTable',
        on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Station'))

    min_players = models.SmallIntegerField(null=False, blank=True, default=2, verbose_name=_('Minimum players'))
    max_players = models.SmallIntegerField(null=False, blank=True, default=5, verbose_name=_('Maximum players'))
    external_players = models.PositiveIntegerField(null=False, blank=True, default=0,
                                                   verbose_name=_('External players'))
    unlimited_seats = models.BooleanField(
        default=False, null=False, blank=True, verbose_name=_('Unlimited seats'),
        help_text=_('No seat limit: anyone can join and no empty seats are shown.'))
    date = models.DateField(default=datetime.date.today, null=False, blank=True, verbose_name=_('Date'))
    time = models.TimeField(default=datetime.time(20, 30), null=False, blank=True, verbose_name=_('Hour'))
    duration = models.PositiveIntegerField(
        default=120, null=False, blank=True, verbose_name=_('Duration (minutes)'),
        help_text=_('Expected duration in minutes'))
    is_public_location = models.BooleanField(default=False, null=False, blank=True)

    author = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, related_name='created_tables', null=True)
    players = models.ManyToManyField(UserProfile, through='Player', related_name='joined_tables', blank=True)
    game = models.ForeignKey(
        Game, on_delete=models.SET_NULL, related_name='created_tables', null=True, blank=True, verbose_name=_('Game'))
    custom_cover = models.ImageField(
        upload_to='table-covers', null=True, blank=True, storage=PublicMediaStorage(),
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
        if current < game_datetime + self.ARCHIVE_AFTER:
            return self.PHASE_RECENTLY_ENDED
        return self.PHASE_ARCHIVED

    def computed_table_status(self, at=None):
        """The table_status this table should have, based on time."""
        return self._PHASE_STATUS_MAP[self.lifecycle_phase(at)][0]

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

    def save(self, *args, **kwargs):
        # Keep both statuses in sync with the lifecycle on every save, so that
        # editing the date/time immediately realigns them (no drift waiting for
        # the cron). Set `_skip_status_recompute = True` to bypass if ever needed.
        if not getattr(self, '_skip_status_recompute', False):
            self.recompute_statuses()
        super().save(*args, **kwargs)

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
        """schema.org/Event JSON-LD payload for a table (a game session).
        Location tables reference their venue Place; event tables link the
        parent event via `superEvent` and inherit its venue as `location`."""
        data = {
            '@context': 'https://schema.org',
            '@type': 'Event',
            'name': self.title,
            'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
            'eventStatus': 'https://schema.org/EventScheduled',
            'startDate': self.start_datetime.isoformat(),
            'endDate': self.end_datetime.isoformat(),
            'url': _absolute_url(self.get_absolute_url(), request),
        }
        if not self.unlimited_seats:
            data['maximumAttendeeCapacity'] = self.max_players
        description = _plain_text(self.description)
        if description:
            data['description'] = description
        image = self.get_meta_image()
        if image:
            data['image'] = _absolute_url(image, request)
        if self.location_id:
            data['location'] = self.location.as_schema_place(request)
        elif self.event_id:
            data['superEvent'] = {
                '@type': 'Event',
                'name': self.event.name,
                'url': _absolute_url(self.event.get_absolute_url(), request),
            }
            venue = self.event.as_schema_place()
            if venue:
                data['location'] = venue
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


class NotificationType(models.TextChoices):
    NEW_TABLE = 'new_table', _('New table created')
    NEW_PLAYER = 'new_player', _('New player joined')
    LEADERBOARD_EDITABLE = 'leaderboard_editable', _('Leaderboard is now editable')
    LEADERBOARD_UPDATED = 'leaderboard_updated', _('Leaderboard updated')
    LEADERBOARD_CLOSED = 'leaderboard_closed', _('Leaderboard closed')
    TABLE_CLOSED = 'table_closed', _('Table closed')
    TABLE_DELETED = 'table_deleted', _('Table deleted')
    NEW_COMMENT = 'new_comment', _('New comment')


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

    first_name = models.CharField(max_length=100, verbose_name=_('First Name'))
    last_name = models.CharField(max_length=100, verbose_name=_('Last Name'))
    code = models.CharField(max_length=50, blank=True, verbose_name=_('Member Code'))
    email = models.EmailField(blank=True, verbose_name=_('Email'))
    phone_number = PhoneNumberField(blank=True, region='IT', verbose_name=_('Phone Number'))
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Member')
        verbose_name_plural = _('Members')
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

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
    approved_by = models.ForeignKey(
        UserProfile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='approved_memberships',
        verbose_name=_('Approved By')
    )
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Membership')
        verbose_name_plural = _('Memberships')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.member} [{self.status}]"


class LocationGame(DateTimeModel):
    """
    Represents a game in a location's library.
    Can be owned by the location itself or by a member (socio),
    and can be physically stored at the association or at a member's home.
    """
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
    notes = models.TextField(blank=True, verbose_name=_('Notes'))
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False, db_index=True)

    class Meta:
        verbose_name = _('Location Game')
        verbose_name_plural = _('Location Games')
        unique_together = ('location', 'game')
        ordering = ['game__name']

    def __str__(self):
        return f"{self.game.name} @ {self.location.name}"


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


class Event(DateTimeModel, ModelMeta, SlugModel):
    PENDING = 'pending'
    APPROVED = 'approved'
    REJECTED = 'rejected'
    STATUS_CHOICES = [
        (PENDING, _('Pending approval')),
        (APPROVED, _('Approved')),
        (REJECTED, _('Rejected')),
    ]

    slug_field_name = 'name'
    name = models.CharField(max_length=255, verbose_name=_('Name'))
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)
    description = models.TextField(blank=True, verbose_name=_('Description'))
    cover = models.ImageField(
        upload_to='event-covers', null=True, blank=True, storage=PublicMediaStorage(),
        verbose_name=_('Cover'))

    address = models.CharField(max_length=255, null=True, blank=True, verbose_name=_('Address'))
    city = models.CharField(max_length=144, null=True, blank=True, verbose_name=_('City'))
    latitude = models.CharField(max_length=25, null=True, blank=True)
    longitude = models.CharField(max_length=25, null=True, blank=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    phone = PhoneNumberField(null=True, blank=True, region='IT', verbose_name=_('Phone'))
    email = models.EmailField(null=True, blank=True, verbose_name=_('Email'))

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=PENDING, verbose_name=_('Status'))

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
        return settings.STATIC_URL + settings.DEFAULT_LOCATION_COVER_URL

    def structured_data(self, request=None):
        """schema.org/Event JSON-LD payload for search-engine rich results.
        Relative URLs are made absolute from `request` when available, else
        from settings.DOMAIN_URL (S3 media URLs are already absolute)."""
        data = {
            '@context': 'https://schema.org',
            '@type': 'Event',
            'name': self.name,
            'eventAttendanceMode': 'https://schema.org/OfflineEventAttendanceMode',
            'eventStatus': 'https://schema.org/EventScheduled',
            'url': _absolute_url(self.get_absolute_url(), request),
        }
        if self.start_date:
            data['startDate'] = self.start_date.isoformat()
        if self.end_date:
            data['endDate'] = self.end_date.isoformat()
        description = _plain_text(self.description)
        if description:
            data['description'] = description
        if self.cover:
            data['image'] = _absolute_url(self.cover_url, request)
        place = self.as_schema_place()
        if place:
            data['location'] = place
        if self.creator and self.creator.nickname:
            data['organizer'] = {'@type': 'Organization', 'name': self.creator.nickname}
        return data

    def as_schema_place(self):
        """schema.org/Place fragment for this event's venue, or None if unknown.
        Embeddable as the `location` of the event and of its tables."""
        if not (self.address or self.city):
            return None
        place = {'@type': 'Place', 'name': self.city or self.name}
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

    def get_absolute_url(self):
        return reverse('event_detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if self.latitude and self.longitude:
            self.point = Point(float(self.longitude), float(self.latitude), srid=4326)
        super().save(*args, **kwargs)

    def is_manager(self, user_profile):
        return self.creator == user_profile or user_profile in self.managers.all()

    def can_create_table(self, user_profile):
        return self.is_manager(user_profile) or user_profile in self.allowed_table_creators.all()

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


class PlayArea(DateTimeModel):
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='play_areas', verbose_name=_('Event'))
    name = models.CharField(max_length=144, verbose_name=_('Name'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        return f"{self.event.name} — {self.name}"

    class Meta:
        verbose_name = _('Play Area')
        verbose_name_plural = _('Play Areas')
        ordering = ['order', 'name']
        unique_together = [('event', 'name')]


class EventDate(DateTimeModel):
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='dates', verbose_name=_('Event'))
    date = models.DateField(verbose_name=_('Date'))

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


class PhysicalTable(DateTimeModel):
    """A physical playing station ("postazione") at an event — e.g. Table 1, 2, 3.

    Game sessions (Table) can be assigned to a station for a time slot. A station
    can exist without any session (free / game-lending stations).
    """
    event = models.ForeignKey(
        Event, on_delete=models.CASCADE, related_name='physical_tables', verbose_name=_('Event'))
    play_area = models.ForeignKey(
        PlayArea, on_delete=models.SET_NULL, related_name='physical_tables',
        null=True, blank=True, verbose_name=_('Play Area'))
    name = models.CharField(max_length=144, verbose_name=_('Name'),
                            help_text=_('On-site label, e.g. "Table 1"'))
    order = models.PositiveIntegerField(default=0, verbose_name=_('Order'))

    def __str__(self):
        return f"{self.event.name} — {self.name}"

    class Meta:
        verbose_name = _('Station')
        verbose_name_plural = _('Stations')
        ordering = ['order', 'name']
        unique_together = [('event', 'name')]


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

    def __str__(self):
        return f"{self.user_profile.nickname} — {self.endpoint[:60]}"
