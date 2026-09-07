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
        parser.add_argument(
            '--chat-id', type=int, default=None,
            help="With --show, also inspect the scopes specific to this chat.")

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.stdout.write(self.style.WARNING(
                "TELEGRAM_BOT_TOKEN is not set — nothing to do."))
            return

        if options['show']:
            self.show(token, options['chat_id'])
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

    def show(self, token, chat_id=None):
        """What Telegram is actually serving to clients right now.

        Registration writes to the `default` scope, but a group resolves its
        command list from the most specific scope that has one — chat_member,
        chat_administrators, chat, all_chat_administrators, all_group_chats,
        and only then default. Anything set higher up silently hides what we
        registered, which looks exactly like a stale menu. So list them all.
        """
        scopes = [
            ('default', None),
            ('all_private_chats', {'type': 'all_private_chats'}),
            ('all_group_chats', {'type': 'all_group_chats'}),
            ('all_chat_administrators', {'type': 'all_chat_administrators'}),
        ]
        if chat_id is not None:
            scopes += [
                ('chat', {'type': 'chat', 'chat_id': chat_id}),
                ('chat_administrators',
                 {'type': 'chat_administrators', 'chat_id': chat_id}),
            ]

        shadowing = []
        for scope_name, scope in scopes:
            for language_code in COMMANDS:
                label = f"{scope_name}/{language_code or 'default'}"
                commands = self.registered(token, scope, language_code)
                if commands is None:
                    continue
                if not commands:
                    self.stdout.write(f"[{label}] —")
                    continue
                if scope_name != 'default':
                    shadowing.append(label)
                for command in commands:
                    self.stdout.write(self.style.SUCCESS(
                        f"[{label}] /{command['command']} — {command['description']}"))

        if shadowing:
            self.stdout.write(self.style.WARNING(
                "\nThese scopes are more specific than `default` and take "
                "precedence where they apply: " + ", ".join(shadowing) + ".\n"
                "Clear them (setMyCommands with that scope and an empty list) "
                "for the registered list to show through."))
        if chat_id is None:
            self.stdout.write(
                "\nPass --chat-id <group id> to also check that group's own scopes.")

    def registered(self, token, scope, language_code):
        """The command list for one scope/language, or None if the call failed."""
        params = {}
        if scope:
            params['scope'] = json.dumps(scope)
        if language_code:
            params['language_code'] = language_code
        try:
            response = requests.get(
                f"{TELEGRAM_API_BASE}/bot{token}/getMyCommands",
                params=params,
                timeout=10,
            )
        except requests.RequestException as error:
            self.stdout.write(self.style.ERROR(f"request failed: {error}"))
            return None

        if not response.ok:
            self.stdout.write(self.style.ERROR(
                f"{response.status_code}: {response.text}"))
            return None
        return response.json().get('result', [])
