import json
import logging
import secrets
from datetime import timedelta

import requests as http_requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from webapp.models import Location, Table, TelegramGroupConfig, TelegramSetupToken

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _send_message(chat_id, text):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set")
        return
    try:
        http_requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=5,
        )
    except Exception as e:
        logger.error("Telegram sendMessage failed: %s", e)


def _is_location_manager(user, location):
    if not user.is_authenticated:
        return False
    profile = user.user_profile
    return location.creator == profile or profile in location.managers.all()


# ── Webhook ───────────────────────────────────────────────────────────────────

@csrf_exempt
def telegram_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    secret = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    if settings.TELEGRAM_WEBHOOK_SECRET and secret != settings.TELEGRAM_WEBHOOK_SECRET:
        return HttpResponseForbidden()

    try:
        update = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    message = update.get('message') or update.get('my_chat_member')
    if not message:
        return JsonResponse({'ok': True})

    chat = message.get('chat', {})
    chat_id = chat.get('id')
    chat_title = chat.get('title', '')
    text = (message.get('text') or '').strip()

    if not chat_id or not text:
        return JsonResponse({'ok': True})

    # Strip @botname suffix Telegram adds in groups
    command = text.split('@')[0].split()[0].lower() if text.startswith('/') else ''
    args = text.split()[1:] if text.startswith('/') else []

    if command == '/setup':
        _handle_setup(chat_id, chat_title, args)
    elif command == '/tables':
        _handle_tables(chat_id)

    return JsonResponse({'ok': True})


def _handle_setup(chat_id, chat_title, args):
    if not args:
        _send_message(chat_id, "Usa: <code>/setup &lt;token&gt;</code>")
        return

    token_str = args[0]
    try:
        token = TelegramSetupToken.objects.select_related('location').get(
            token=token_str,
            used=False,
            expires_at__gt=timezone.now(),
        )
    except TelegramSetupToken.DoesNotExist:
        _send_message(chat_id, "❌ Token non valido o scaduto.\nGenera un nuovo token dalla pagina di gestione della location.")
        return

    existing = TelegramGroupConfig.objects.filter(chat_id=chat_id).first()
    if existing:
        _send_message(
            chat_id,
            f"ℹ️ Questo gruppo è già configurato per <b>{existing.location.name}</b>.",
        )
        return

    TelegramGroupConfig.objects.create(
        location=token.location,
        chat_id=chat_id,
        chat_title=chat_title,
    )
    token.used = True
    token.save(update_fields=['used'])

    _send_message(
        chat_id,
        f"✅ Bot configurato per <b>{token.location.name}</b>!\n\n"
        f"Usa /tables per vedere i tavoli aperti.",
    )


def _handle_tables(chat_id):
    config = TelegramGroupConfig.objects.select_related('location').filter(
        chat_id=chat_id, active=True
    ).first()

    if not config:
        _send_message(
            chat_id,
            "⚠️ Questo gruppo non è ancora configurato.\n"
            "Chiedi al manager della location di generare un token dalla pagina di gestione.",
        )
        return

    today = timezone.now().date()
    tables = (
        Table.objects
        .filter(location=config.location, date__gte=today, status=Table.OPEN)
        .select_related('game')
        .prefetch_related('players')
        .order_by('date', 'time')[:10]
    )

    location = config.location
    base_url = f"{settings.SITE_PROTOCOL}://{settings.SITE_DOMAIN}"

    if not tables:
        _send_message(
            chat_id,
            f"🎲 <b>{location.name}</b>\n\nNessun tavolo aperto al momento.",
        )
        return

    lines = [f"🎲 <b>Tavoli aperti — {location.name}</b>\n"]
    for t in tables:
        game_name = t.game.name if t.game else "Gioco libero"
        players = f"{t.players.count()}/{t.max_players}"
        date_str = t.date.strftime("%-d %b")
        time_str = t.time.strftime("%H:%M") if t.time else ""
        url = f"{base_url}/tables/{t.slug}/"
        lines.append(
            f"• <b>{t.title}</b> ({game_name})\n"
            f"  📅 {date_str} {time_str} · 👥 {players}\n"
            f"  <a href='{url}'>Dettagli →</a>"
        )

    _send_message(chat_id, "\n\n".join(lines))


# ── Generate setup token ──────────────────────────────────────────────────────

@login_required
@require_POST
def generate_setup_token(request, slug):
    location = get_object_or_404(Location, slug=slug)

    if not _is_location_manager(request.user, location):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    # Invalida i token precedenti non ancora usati per questa location
    TelegramSetupToken.objects.filter(location=location, used=False).update(used=True)

    token = TelegramSetupToken.objects.create(
        location=location,
        token=secrets.token_urlsafe(32),
        expires_at=timezone.now() + timedelta(hours=1),
    )

    return JsonResponse({
        'token': token.token,
        'expires_at': token.expires_at.isoformat(),
        'setup_command': f'/setup {token.token}',
    })
