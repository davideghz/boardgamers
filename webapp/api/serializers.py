from rest_framework import serializers
from webapp.models import Table, Game, Location, Player


class GameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Game
        fields = ['name', 'slug', 'description']


class TableSerializer(serializers.ModelSerializer):
    location_name = serializers.CharField(source='location.name', read_only=True)
    game = GameSerializer(read_only=True)

    class Meta:
        model = Table
        fields = ['title', 'status', 'slug', 'cover_url', 'description', 'location_name', 'date', 'time', 'min_players', 'max_players', 'game']
