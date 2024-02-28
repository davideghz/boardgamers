import datetime
import random

import factory
from django.contrib.gis.geos import Point
from django.utils import timezone
from factory.django import DjangoModelFactory
from django.contrib.auth.models import User
from .models import UserProfile, Table, Comment, Player, Game, Location
from faker import Faker

faker = Faker()


def random_longitude():
    return random.choice(['9'])


def random_latitude():
    return random.choice(['45', '89', '-89'])


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User

    username = factory.LazyFunction(faker.email)
    email = username


class SuperUserFactory(UserFactory):
    username = "bgadmin"
    email = "bgadmin@example.com"
    password = factory.PostGenerationMethodCall('set_password', 'bgadmin')
    is_superuser = True
    is_staff = True


class UserProfileFactory(DjangoModelFactory):
    class Meta:
        model = UserProfile

    nickname = factory.LazyFunction(faker.user_name)
    is_email_verified = True
    user = factory.SubFactory(UserFactory)
    address = factory.LazyFunction(faker.address)
    city = factory.LazyFunction(faker.city)
    longitude = factory.LazyFunction(random_longitude)
    latitude = factory.LazyFunction(random_latitude)


class SuperUserProfileFactory(UserProfileFactory):
    user = factory.SubFactory(SuperUserFactory)


class LocationFactory(DjangoModelFactory):
    class Meta:
        model = Location

    name = factory.Iterator(["Tardis", "La forgia degli eroi", "Joker"])
    description = factory.LazyFunction(faker.sentence)
    address = factory.LazyFunction(faker.address)
    city = factory.LazyFunction(faker.city)
    longitude = factory.LazyFunction(random_longitude)
    latitude = factory.LazyFunction(random_latitude)
    is_public = True


class GameFactory(DjangoModelFactory):
    class Meta:
        model = Game

    name = factory.Iterator(["Risiko", "Bang", "Rock, Paper, Wizard", "Monopoli", "Mascarade"])
    description = factory.LazyFunction(faker.sentence)


def generate_random_time():
    hour = random.randint(20, 22)  # 22 incluso per permettere orari fino alle 22:59
    minute = random.randint(0, 59)
    return datetime.time(hour, minute)


def generate_date_next_week():
    today = timezone.now().date()
    days_ahead = random.randint(1, 7)
    next_week_date = today + datetime.timedelta(days=days_ahead)
    return next_week_date


class TableFactory(DjangoModelFactory):
    class Meta:
        model = Table

    title = factory.LazyFunction(faker.sentence)
    description = factory.LazyFunction(faker.text)
    author = factory.LazyAttribute(lambda _: random.choice(UserProfile.objects.all()))
    location = factory.LazyAttribute(lambda _: random.choice(Location.objects.all()))
    date = factory.LazyFunction(generate_date_next_week)
    time = factory.LazyFunction(generate_random_time)


class CommentFactory(DjangoModelFactory):
    class Meta:
        model = Comment

    table = factory.LazyAttribute(lambda _: random.choice(Table.objects.all()))
    author = factory.LazyAttribute(lambda _: random.choice(UserProfile.objects.all()))
    content = factory.LazyFunction(faker.sentence)


class PlayerFactory(DjangoModelFactory):
    class Meta:
        model = Player

    user = factory.LazyAttribute(lambda _: random.choice(UserProfile.objects.all()))
    table = factory.LazyAttribute(lambda _: random.choice(Table.objects.all()))
