from rest_framework import serializers
from webapp.models import Table, Game, Location


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ['name', 'slug', 'description']


class TableSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    games = GameSerializer(many=True, read_only=True)

    class Meta:
        model = Table
        fields = ['title', 'slug', 'description', 'location_name', 'date', 'time', 'min_players', 'max_players', 'games']
