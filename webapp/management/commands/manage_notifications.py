from django.core.management.base import BaseCommand
from django.utils import timezone
from webapp.models import Notification


class Command(BaseCommand):
    help = 'Utility per gestire le notifiche: segna come inviate, lette o elimina tutto.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--mark-all-sent',
            action='store_true',
            help='Imposta tutte le notifiche non inviate come inviate e aggiorna sent_at.'
        )
        parser.add_argument(
            '--mark-all-read',
            action='store_true',
            help='Imposta tutte le notifiche non lette come lette.'
        )
        parser.add_argument(
            '--delete-all',
            action='store_true',
            help='Elimina TUTTE le notifiche dal database.'
        )

    def handle(self, *args, **options):
        # 1. Mark All Sent
        if options['mark_all_sent']:
            # Filtriamo solo quelle non ancora inviate per efficienza e correttezza logica
            qs = Notification.objects.filter(sent=False)
            count = qs.update(sent=True, sent_at=timezone.now())
            self.stdout.write(self.style.SUCCESS(f'Aggiornate {count} notifiche come INVIATE.'))

        # 2. Mark All Read
        if options['mark_all_read']:
            qs = Notification.objects.filter(is_read=False)
            count = qs.update(is_read=True)
            self.stdout.write(self.style.SUCCESS(f'Aggiornate {count} notifiche come LETTE.'))

        # 3. Delete All
        if options['delete_all']:
            total_count = Notification.objects.count()
            if total_count == 0:
                self.stdout.write(self.style.WARNING('Nessuna notifica da eliminare.'))
            else:
                count, _ = Notification.objects.all().delete()
                self.stdout.write(self.style.SUCCESS(f'Eliminate {count} notifiche.'))

        # Se nessuna opzione è passata
        if not any([options['mark_all_sent'], options['mark_all_read'], options['delete_all']]):
            self.print_help('manage.py', 'manage_notifications')
            self.stdout.write(self.style.WARNING('\nAttenzione: Specifica almeno un argomento (--mark-all-sent, --mark-all-read, --delete-all)'))
