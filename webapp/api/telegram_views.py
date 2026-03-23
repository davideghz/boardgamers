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

def _send_message(chat_id, text, reply_markup=None, message_thread_id=None):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set")
        return
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if message_thread_id:
        payload['message_thread_id'] = message_thread_id
    if reply_markup:
        payload['reply_markup'] = reply_markup
    try:
        resp = http_requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload,
            timeout=5,
        )
        if not resp.ok:
            logger.error("Telegram sendMessage error %s: %s", resp.status_code, resp.text)
        else:
            logger.info("Telegram sendMessage ok: %s", resp.text[:200])
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

    logger.info("Telegram update received: %s", json.dumps(update))

    message = update.get('message') or update.get('my_chat_member')
    if not message:
        return JsonResponse({'ok': True})

    chat = message.get('chat', {})
    chat_id = chat.get('id')
    chat_title = chat.get('title', '')
    message_thread_id = message.get('message_thread_id')
    thread_title = (
        message.get('reply_to_message', {})
               .get('forum_topic_created', {})
               .get('name', '')
    )
    text = (message.get('text') or '').strip()

    if not chat_id or not text:
        return JsonResponse({'ok': True})

    # Strip @botname suffix Telegram adds in groups
    command = text.split('@')[0].split()[0].lower() if text.startswith('/') else ''
    args = text.split()[1:] if text.startswith('/') else []

    logger.info("Telegram command=%r chat_id=%s thread_id=%s thread_title=%r", command, chat_id, message_thread_id, thread_title)


    try:
        if command == '/setup':
            _handle_setup(chat_id, chat_title, args, message_thread_id, thread_title)
        elif command == '/tables':
            _handle_tables(chat_id, message_thread_id)
    except Exception:
        logger.exception("Error handling Telegram command %r", command)

    return JsonResponse({'ok': True})


def _handle_setup(chat_id, chat_title, args, message_thread_id=None, thread_title=''):
    if not args:
        _send_message(chat_id, "Usa: <code>/setup &lt;token&gt;</code>", message_thread_id=message_thread_id)
        return

    token_str = args[0]
    try:
        token = TelegramSetupToken.objects.select_related('location').get(
            token=token_str,
            used=False,
            expires_at__gt=timezone.now(),
        )
    except TelegramSetupToken.DoesNotExist:
        _send_message(chat_id, "❌ Token non valido o scaduto.\nGenera un nuovo token dalla pagina di gestione della location.", message_thread_id=message_thread_id)
        return

    existing = TelegramGroupConfig.objects.filter(chat_id=chat_id).first()
    if existing:
        existing.location = token.location
        existing.chat_title = chat_title
        existing.message_thread_id = message_thread_id
        existing.message_thread_title = thread_title
        existing.active = True
        existing.save(update_fields=['location', 'chat_title', 'message_thread_id', 'message_thread_title', 'active'])
        token.used = True
        token.save(update_fields=['used'])
        _send_message(
            chat_id,
            f"✅ Bot configurato per <b>{token.location.name}</b>!\n\n"
            f"Usa /tables per vedere i tavoli aperti.",
            message_thread_id=message_thread_id,
        )
        return

    TelegramGroupConfig.objects.create(
        location=token.location,
        chat_id=chat_id,
        chat_title=chat_title,
        message_thread_id=message_thread_id,
        message_thread_title=thread_title,
    )
    token.used = True
    token.save(update_fields=['used'])

    _send_message(
        chat_id,
        f"✅ Bot configurato per <b>{token.location.name}</b>!\n\n"
        f"Usa /tables per vedere i tavoli aperti.",
        message_thread_id=message_thread_id,
    )


def _handle_tables(chat_id, message_thread_id=None):
    config = TelegramGroupConfig.objects.select_related('location').filter(
        chat_id=chat_id, active=True
    ).first()

    if not config:
        _send_message(
            chat_id,
            "⚠️ Questo gruppo non è ancora configurato.\n"
            "Chiedi al manager della location di generare un token dalla pagina di gestione.",
            message_thread_id=message_thread_id,
        )
        return

    # Use the thread where the command was issued; fall back to the configured thread
    message_thread_id = message_thread_id or config.message_thread_id

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
            message_thread_id=message_thread_id,
        )
        return

    lines = [f"🎲 <b>Tavoli aperti — {location.name}</b>\n"]
    buttons = []
    for t in tables:
        game_name = t.game.name if t.game else "Gioco libero"
        players = f"{t.players.count()}/{t.max_players}"
        date_str = t.date.strftime("%-d %b")
        time_str = t.time.strftime("%H:%M") if t.time else ""
        lines.append(f"• {game_name} | {date_str} {time_str} | 👥 {players}")
        buttons.append([{
            "text": f"{t.title} — {date_str}",
            "url": f"{base_url}/tables/{t.slug}/",
        }])

    location_url = f"{base_url}/locations/{location.slug}/"
    buttons.append([{"text": "📍 Tutti i tavoli →", "url": location_url}])

    _send_message(
        chat_id,
        "\n".join(lines),
        reply_markup={"inline_keyboard": buttons},
        message_thread_id=message_thread_id,
    )


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
