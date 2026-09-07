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
        parser.add_argument(
            '--show', action='store_true',
            help="Print what Telegram currently has registered, and change nothing.")

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stdout.write(self.style.WARNING(
                "TELEGRAM_BOT_TOKEN is not set — nothing to do."))
            return

        if options['show']:
            self.show(token)
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

    def show(self, token):
        """What Telegram is actually serving to clients right now.

        Clients cache the "/" menu, so this is the way to tell a failed
        registration apart from a stale menu on your phone.
        """
        for language_code in COMMANDS:
            label = language_code or 'default'
            params = {'language_code': language_code} if language_code else {}
            try:
                response = requests.get(
                    f"{TELEGRAM_API_BASE}/bot{token}/getMyCommands",
                    params=params,
                    timeout=10,
                )
            except requests.RequestException as error:
                self.stdout.write(self.style.ERROR(f"[{label}] request failed: {error}"))
                continue

            if not response.ok:
                self.stdout.write(self.style.ERROR(
                    f"[{label}] {response.status_code}: {response.text}"))
                continue

            registered = response.json().get('result', [])
            if not registered:
                self.stdout.write(self.style.WARNING(
                    f"[{label}] nothing registered — run this command without --show"))
                continue
            for command in registered:
                self.stdout.write(
                    f"[{label}] /{command['command']} — {command['description']}")
