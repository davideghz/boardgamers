from random import random

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from webapp.factories import UserProfileFactory, TableFactory, CommentFactory, SuperUserProfileFactory, LocationFactory, \
    GameFactory
from webapp.models import Table, UserProfile, Player, Game


class Command(BaseCommand):
    help = 'Populate the database with sample data'
    locations = ["Tardis", "La forgia degli eroi", "Joker"]
    games = ["Risiko", "Bang", "Rock, Paper, Wizard", "Monopoli", "Mascarade"]

    def handle(self, *args, **kwargs):
        # Disabling email signals
        self.stdout.write(self.style.SUCCESS('Disabling email signals'))
        settings.ENABLE_EMAIL_SIGNALS = False

        self.stdout.write(self.style.SUCCESS('Starting database population'))

        # Create Locations
        for location_name in self.locations:
            LocationFactory.create(name=location_name, slug=slugify(location_name))

        # Create Games
        for game_name in self.games:
            GameFactory.create(name=game_name, slug=slugify(game_name))

        # Create superuser
        SuperUserProfileFactory.create()

        # Create 5 user profiles
        for _ in range(5):
            UserProfileFactory.create()

        # Create 15 tables
        for _ in range(15):
            TableFactory.create()

        # Crea 50 comments
        for _ in range(50):
            CommentFactory.create()

        # Assign 1 player and 2 game for each table
        for table in Table.objects.all():
            author = table.author
            random_user_profile = UserProfile.objects.exclude(id=author.id).order_by("?").first()
            Player.objects.create(table=table, user_profile=random_user_profile)
            Player.objects.create(table=table, user_profile=author)
            random_games = Game.objects.order_by("?")[:2]
            table.games.add(*random_games)

        self.stdout.write(self.style.SUCCESS('Database populated successfully!'))

        # Enabling email signals
        self.stdout.write(self.style.SUCCESS('Enabling email signals'))
        settings.ENABLE_EMAIL_SIGNALS = True
