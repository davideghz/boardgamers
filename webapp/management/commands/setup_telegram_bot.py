"""Register the bot's command list with Telegram.

Run once after deploying a change to the commands — Telegram caches the list
client-side, so a command the bot handles is invisible in the "/" menu until
this has run:

    python manage.py setup_telegram_bot

Descriptions are registered per language: Telegram shows the Italian list to
clients set to Italian and falls back to the default (English) for everyone
else. The command *names* stay the same in both, so the webhook has a single
set of strings to dispatch on.
"""

import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from webapp.services.telegram import TELEGRAM_API_BASE

COMMANDS = {
    None: [
        {'command': 'tables', 'description': 'Upcoming tables at this location'},
        {'command': 'join', 'description': 'Open the app and book a seat'},
        {'command': 'setup', 'description': 'Connect this group to a location'},
    ],
    'it': [
        {'command': 'tables', 'description': 'I prossimi tavoli di questa location'},
        {'command': 'join', 'description': 'Apri l\'app e prenota il tuo posto'},
        {'command': 'setup', 'description': 'Collega questo gruppo a una location'},
    ],
}


class Command(BaseCommand):
    help = "Register the bot's command list with Telegram (setMyCommands)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help="Print what would be sent without calling Telegram.")

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stdout.write(self.style.WARNING(
                "TELEGRAM_BOT_TOKEN is not set — nothing to do."))
            return

        for language_code, commands in COMMANDS.items():
            label = language_code or 'default'
            payload = {'commands': commands}
            if language_code:
                payload['language_code'] = language_code

            if options['dry_run']:
                self.stdout.write(f"[{label}] {json.dumps(commands, ensure_ascii=False)}")
                continue

            try:
                response = requests.post(
                    f"{TELEGRAM_API_BASE}/bot{token}/setMyCommands",
                    json=payload,
                    timeout=10,
                )
            except requests.RequestException as error:
                self.stdout.write(self.style.ERROR(f"[{label}] request failed: {error}"))
                continue

            if response.ok:
                self.stdout.write(self.style.SUCCESS(f"[{label}] registered"))
            else:
                self.stdout.write(self.style.ERROR(
                    f"[{label}] {response.status_code}: {response.text}"))
