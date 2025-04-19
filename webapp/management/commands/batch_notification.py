from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils.timezone import now
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from webapp.models import Table, Notification


class Command(BaseCommand):
    help = "Invia notifiche batch"

    def handle(self, *args, **kwargs):
        notifications_unread = Notification.objects.filter(read=False)
