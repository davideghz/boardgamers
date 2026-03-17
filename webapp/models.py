import string
import uuid
import random
import datetime

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

from webapp.storage_backends import PublicMediaStorage


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

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'cover_url',
    }

    def get_meta_title(self):
                return _("%(name)s - Board-Gamers.com") % {'name': self.name}

    def get_meta_description(self):
        return self.description

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
    is_public = models.BooleanField(default=False)
    enable_membership = models.BooleanField(default=False)
    website = models.URLField(null=True, blank=True)

    _metadata = {
        'title': 'get_meta_title',
        'description': 'get_meta_description',
        'image': 'cover_url',
    }

    def get_meta_title(self):
                return _("%(name)s - Board-Gamers.com") % {'name': self.name}

    def get_meta_description(self):
                return _("Game nights in %(address)s") % {'address': self.address}

    def __str__(self):
        return f"{self.name} - {self.city}"

    @cached_property
    def cover_url(self):
        if self.cover and hasattr(self.cover, 'url'):
            return self.cover.url
        else:
            return settings.STATIC_URL + settings.DEFAULT_LOCATION_COVER_URL

    def save(self, *args, **kwargs):
        if self.latitude is not None and self.longitude is not None:
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

    preferred_language = models.CharField(
        max_length=7,
        choices=settings.LANGUAGES,   # [("it","Italiano"), ("en","English"), ...]
        default="it",
    )

    # Notifications
    notification_new_table = models.BooleanField(default=True, verbose_name="Notification New Table")
    notification_new_player = models.BooleanField(default=True, verbose_name="Notification New Player")
    notification_new_comments = models.BooleanField(default=True, verbose_name="Notification New Comments")
    notification_leaderboard_reminder = models.BooleanField(default=True, verbose_name="Notification Leaderboard Reminder")
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

    LEADERBOARD_NOT_EDITABLE = 'not_editable'
    LEADERBOARD_EDITABLE = 'editable'
    LEADERBOARD_STATUS_DEAFULT = LEADERBOARD_NOT_EDITABLE
    LEADERBOARD_STATUS_CHOICES = [
        (LEADERBOARD_NOT_EDITABLE, _('Not Editable')),
        (LEADERBOARD_EDITABLE, _('Editable')),
    ]

    slug_field_name = 'title'
    title = models.CharField(max_length=144, null=False, blank=True, verbose_name=_('Title'))
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    tracker = FieldTracker(fields=['status', 'leaderboard_status'])

    description = models.TextField(null=False, blank=True, verbose_name=_('Description'))
    location = models.ForeignKey(
        Location, on_delete=models.SET_NULL, related_name='tables', null=True, blank=True, verbose_name=_('Location'))

    min_players = models.SmallIntegerField(null=False, blank=True, default=2, verbose_name=_('Minimum players'))
    max_players = models.SmallIntegerField(null=False, blank=True, default=5, verbose_name=_('Maximum players'))
    external_players = models.PositiveIntegerField(null=False, blank=True, default=0, verbose_name=_('External players'))
    date = models.DateField(default=datetime.date.today, null=False, blank=True, verbose_name=_('Date'))
    time = models.TimeField(default=timezone.now, null=False, blank=True, verbose_name=_('Hour'))
    is_public_location = models.BooleanField(default=False, null=False, blank=True)

    author = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, related_name='created_tables', null=True)
    players = models.ManyToManyField(UserProfile, through='Player', related_name='joined_tables', blank=True)
    game = models.ForeignKey(
        Game, on_delete=models.SET_NULL, related_name='created_tables', null=True, blank=True, verbose_name=_('Game'))

    @property
    def total_players(self):
        """
        Returns the total number of players: registered players + external players.
        optimizes database access if `players` are prefetched.
        """
        # Using len() on a queryset that is prefetched will not hit the database again.
        # If not prefetched, it will execute the query.
        if hasattr(self, '_prefetched_objects_cache') and 'players' in self._prefetched_objects_cache:
             return len(self.players.all()) + self.external_players
        return self.players.count() + self.external_players

    status = models.CharField(max_length=20, choices=TABLE_STATUS_CHOICES, default=TABLE_STATUS_DEFAULT)
    leaderboard_status = models.CharField(
        max_length=20,
        choices=LEADERBOARD_STATUS_CHOICES,
        default=LEADERBOARD_STATUS_DEAFULT
    )

    @cached_property
    def cover_url(self):
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
        }.get(self.status, 'text-bg-light')

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
        if self.game:
            return _("Join the %(game)s table! We'll play on %(date)s at %(time)s at %(location)s") % {
                'game': self.game.name,
                'date': self.date.strftime('%d/%m/%Y'),
                'time': self.time.strftime('%H:%M'),
                'location': self.location.name
            }
        else:
            return _("Join the table! We'll play on %(date)s at %(time)s at %(location)s") % {
                'date': self.date.strftime('%d/%m/%Y'),
                'time': self.time.strftime('%H:%M'),
                'location': self.location.name
            }

    def get_meta_image(self):
        return self.game.cover_url if self.game else self.location.cover_url

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ['-created_at']


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
    phone_number = models.CharField(max_length=30, blank=True, verbose_name=_('Phone Number'))
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
