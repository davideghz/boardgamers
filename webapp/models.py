import string
import uuid
import random
import datetime

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


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
        if not self.slug:
            self.slug = self.create_unique_slug()
        super().save(*args, **kwargs)


class State(models.Model):
    name = models.CharField(max_length=128, unique=True)
    slug = models.SlugField(max_length=128, unique=True)

    def __str__(self):
        return self.name


class Game(DateTimeModel, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    description = models.TextField()

    def __str__(self):
        return self.name


class Location(DateTimeModel, SlugModel):
    slug_field_name = 'name'
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    description = models.TextField()
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=144)
    state = models.ForeignKey(State, on_delete=models.SET_NULL, related_name='locations', null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    def __str__(self):
        return self.name


class UserProfile(DateTimeModel):
    is_email_verified = models.BooleanField(default=False, db_index=True)
    uuid = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, related_name='user_profile', on_delete=models.CASCADE)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=144)
    state = models.ForeignKey(State, on_delete=models.SET_NULL, related_name='users', null=True, blank=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    class Meta:
        verbose_name = "Profile"
        verbose_name_plural = "Profiles"

    @property
    def username(self):
        return self.user.username

    def __str__(self):
        return self.username


class Table(DateTimeModel, SlugModel):
    slug_field_name = 'title'
    title = models.CharField(max_length=144, null=False, blank=True)
    slug = models.SlugField(max_length=144, unique=True, null=False, blank=True)

    content = models.TextField(null=False, blank=True)
    state = models.ForeignKey(State, on_delete=models.SET_NULL, related_name='tables', null=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, related_name='tables', null=True, blank=True)

    max_players = models.SmallIntegerField(null=False, blank=True, default=4)
    date = models.DateField(default=datetime.date.today, null=False, blank=True)
    time = models.TimeField(default=timezone.now, null=False, blank=True)

    author = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='created_tables', null=True)
    players = models.ManyToManyField(UserProfile, through='Player', related_name='joined_tables', blank=True)
    games = models.ManyToManyField(Game, related_name='tables', blank=True)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "Table"
        verbose_name_plural = "Tables"
        ordering = ['-created_at']


class Player(DateTimeModel):
    user_profile = models.ForeignKey(UserProfile, on_delete=models.CASCADE)
    table = models.ForeignKey(Table, on_delete=models.CASCADE)

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
