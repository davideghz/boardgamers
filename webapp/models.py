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
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from model_utils import FieldTracker

from webapp.storage_backends import PublicMediaStorage


class DateTimeModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta(object):
        abstract = True


class SlugModel(models.Model):
    slug_field_name = None
    randomize = True
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
        source_value = self.get_slug_source_value()
        slug = slugify(source_value)
        random_string = self.generate_random_string()
        unique_slug = f"{slug}-{random_string}"

        while self.__class__.objects.filter(slug=unique_slug).exists():
            random_string = self.generate_random_string()
            unique_slug = f"{slug}-{random_string}"
        return unique_slug

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.get(pk=self.pk)
            if getattr(original, self.slug_field_name) != self.get_slug_source_value():
                self.slug = self.create_unique_slug()
        else:
            self.slug = self.create_unique_slug()
        super().save(*args, **kwargs)


class Game(DateTimeModel, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    image = models.ImageField(upload_to='games', null=True, blank=True, storage=PublicMediaStorage())
    description = models.TextField()

    leaderboard_enabled = models.BooleanField(default=False, db_index=True)

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


class Location(DateTimeModel, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    creator = models.ForeignKey('UserProfile', on_delete=models.CASCADE, related_name='locations', null=True, blank=True)
    description = models.TextField()
    cover = models.ImageField(upload_to='location-covers', null=True, blank=True, storage=PublicMediaStorage())
    address = models.CharField(max_length=255, null=True, blank=True)
    city = models.CharField(max_length=144, null=True, blank=True)
    latitude = models.CharField(max_length=25, null=True, blank=True)
    longitude = models.CharField(max_length=25, null=True, blank=True)
    point = models.PointField(geography=True, default=Point(0.0, 0.0))
    is_public = models.BooleanField(default=False)
    website = models.URLField(null=True, blank=True)

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


class UserProfile(DateTimeModel, SlugModel):
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

    # Notifications
    notification_new_table = models.BooleanField(default=True, verbose_name="Notification New Table")
    notification_new_player = models.BooleanField(default=True, verbose_name="Notification New Player")
    notification_new_comments = models.BooleanField(default=True, verbose_name="Notification New Comments")
    notification_leaderboard_reminder = models.BooleanField(default=True, verbose_name="Notification Leaderboard Reminder")
    notification_leaderboard_update = models.BooleanField(default=True, verbose_name="Notification Leaderboard Update")


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


class Table(DateTimeModel, SlugModel):
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
    LEADERBOARD_STATUS_DEAFULT = LEADERBOARD_EDITABLE
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
    date = models.DateField(default=datetime.date.today, null=False, blank=True, verbose_name=_('Date'))
    time = models.TimeField(default=timezone.now, null=False, blank=True, verbose_name=_('Hour'))
    is_public_location = models.BooleanField(default=False, null=False, blank=True)

    author = models.ForeignKey(UserProfile, on_delete=models.SET_NULL, related_name='created_tables', null=True)
    players = models.ManyToManyField(UserProfile, through='Player', related_name='joined_tables', blank=True)
    game = models.ForeignKey(
        Game, on_delete=models.SET_NULL, related_name='created_tables', null=True, blank=True, verbose_name=_('Game'))

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
            return settings.STATIC_URL + settings.DEFAULT_GAME_COVER_URL

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

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ['-created_at']


class Player(DateTimeModel):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    table = models.ForeignKey(Table, on_delete=models.CASCADE)
    score = models.IntegerField(default=0)
    position = models.IntegerField(default=99, db_index=True)

    class Meta:
        verbose_name = "Player"
        verbose_name_plural = "Players"
        ordering = ['-created_at']
        unique_together = ('user_profile', 'table')
        index_together = ('user_profile', 'table')


class Comment(DateTimeModel):
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey(Table, related_name='comments', on_delete=models.CASCADE, null=True)
    author = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='comments', null=True)
    content = models.TextField()

    def __str__(self):
        return self.content

    class Meta:
        verbose_name = "Comment"
        verbose_name_plural = "Comments"
        ordering = ['-created_at']
        index_together = ('table', 'author')


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
