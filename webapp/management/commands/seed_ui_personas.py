from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from webapp.services import ui_personas


class Command(BaseCommand):
    help = 'Create one demo user for each audience of the UI (DEBUG only)'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete the demo data and create it again')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_ui_personas only runs with DEBUG=True.')
        if ui_personas.exists():
            if not options['reset']:
                raise CommandError('The demo data already exists: use --reset to create it again.')
            ui_personas.delete_ui_personas()

        personas = ui_personas.seed_ui_personas()

        self.stdout.write(self.style.SUCCESS('Demo data created. Sign in with these emails:'))
        for persona in ui_personas.PERSONAS:
            self.stdout.write(f'  {persona:<9} {ui_personas.email_for(persona)}')
        self.stdout.write(f'The password is PASSWORD in {ui_personas.__name__}.')
        self.stdout.write('Pages:')
        for location in (personas.negozio, personas.circolo, personas.associazione):
            self.stdout.write(f"  {reverse('location-detail', kwargs={'slug': location.slug})}")
        self.stdout.write(f'  {personas.manifestation.get_absolute_url()}')
