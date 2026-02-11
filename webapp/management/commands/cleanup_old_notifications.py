from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from webapp.models import Notification


class Command(BaseCommand):
    help = 'Delete notifications older than 30 days'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to keep notifications (default: 30)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting'
        )

    def handle(self, *args, **options):
        days = options['days']
        dry_run = options['dry_run']
        
        # Calculate the cutoff date
        cutoff_date = timezone.now() - timedelta(days=days)
        
        # Find old notifications
        old_notifications = Notification.objects.filter(created_at__lt=cutoff_date)
        count = old_notifications.count()
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING(f'DRY RUN: Would delete {count} notifications older than {days} days')
            )
            if count > 0:
                self.stdout.write('Notifications to be deleted:')
                for notification in old_notifications[:10]:  # Show first 10
                    self.stdout.write(f'  - ID: {notification.id}, Type: {notification.notification_type}, Created: {notification.created_at}')
                if count > 10:
                    self.stdout.write(f'  ... and {count - 10} more')
        else:
            # Delete the notifications
            deleted_count, _ = old_notifications.delete()
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully deleted {deleted_count} notifications older than {days} days')
            )
            
            if deleted_count == 0:
                self.stdout.write(self.style.NOTICE('No old notifications found to delete.'))
