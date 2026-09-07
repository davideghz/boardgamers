"""Shared helpers for the Telegram bot and the Telegram Mini App.

Two different signature schemes coexist in Telegram and they are NOT
interchangeable — using the wrong one silently rejects every request:

- Login Widget / OAuth (the account-linking flow, handled by social-auth):
  secret key = SHA256(bot_token)
- Mini Apps (`initData`, validated here):
  secret key = HMAC_SHA256(key="WebAppData", msg=bot_token)
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone as dt_timezone
from urllib.parse import parse_qsl

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

# How long an initData payload stays acceptable. Telegram signs `auth_date` when
# the Mini App is opened; the window bounds how long a leaked payload can be
# replayed.
INIT_DATA_MAX_AGE = timedelta(hours=24)


# ── Bot API ───────────────────────────────────────────────────────────────────

def send_message(chat_id, text, reply_markup=None, message_thread_id=None):
    """Send a message through the bot. Never raises: Telegram being down must
    not break the request that triggered the notification."""
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
        resp = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/sendMessage",
            json=payload,
            timeout=5,
        )
        if not resp.ok:
            logger.error("Telegram sendMessage error %s: %s", resp.status_code, resp.text)
        else:
            logger.info("Telegram sendMessage ok: %s", resp.text[:200])
    except Exception as e:
        logger.error("Telegram sendMessage failed: %s", e)


def miniapp_link(location):
    """Shareable link that opens the Mini App on `location`.

    BotFather hosts one Mini App short name per URL, so the location travels in
    `startapp` — Telegram hands it back as `start_param` inside the signed
    initData. Returns '' when the bot username is not configured, so callers can
    simply hide the link.
    """
    username = settings.TELEGRAM_BOT_USERNAME
    short_name = settings.TELEGRAM_MINIAPP_SHORT_NAME
    if not username or not short_name:
        return ''
    return f"https://t.me/{username}/{short_name}?startapp={location.slug}"


# ── Mini App initData ─────────────────────────────────────────────────────────

def validate_init_data(raw, max_age=INIT_DATA_MAX_AGE):
    """Validate the `initData` query string a Mini App receives from Telegram.

    Returns the parsed payload (with `user` decoded from JSON) when the
    signature checks out, or None when it is missing, forged, malformed or
    older than `max_age`. Callers must treat None as "unauthenticated" — never
    fall back to the unsigned `initDataUnsafe`.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or not raw:
        return None

    try:
        pairs = dict(parse_qsl(raw, keep_blank_values=True, strict_parsing=True))
    except ValueError:
        return None

    received_hash = pairs.pop('hash', None)
    if not received_hash:
        return None

    # Every remaining field takes part in the signature, `signature` included:
    # only `hash` is excluded.
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    if not _is_fresh(pairs.get('auth_date'), max_age):
        return None

    # `user` travels as a JSON blob inside the query string.
    if 'user' in pairs:
        try:
            pairs['user'] = json.loads(pairs['user'])
        except (json.JSONDecodeError, TypeError):
            return None

    return pairs


def _is_fresh(auth_date, max_age):
    try:
        issued_at = datetime.fromtimestamp(int(auth_date), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return False
    return timezone.now() - issued_at <= max_age


def miniapp_language(profile, telegram_user):
    """Which language to answer a Mini App request in.

    A linked account's own preference wins — it is a deliberate choice — and
    otherwise we take the language the person's Telegram client is set to.
    Returns None when neither yields a language the site supports, leaving
    whatever Django already activated.
    """
    supported = {code for code, _name in settings.LANGUAGES}

    if profile and profile.preferred_language in supported:
        return profile.preferred_language

    # Telegram sends IETF tags: "it", "en", "en-GB", "pt-BR".
    code = ((telegram_user or {}).get('language_code') or '').split('-')[0]
    return code if code in supported else None


def profile_from_init_data(data):
    """Map a validated initData payload to the linked UserProfile.

    Returns None when the Telegram account has never been connected to a
    Board-Gamers account — the caller shows the read-only view in that case.
    """
    from social_django.models import UserSocialAuth

    telegram_id = ((data or {}).get('user') or {}).get('id')
    if not telegram_id:
        return None

    social = (
        UserSocialAuth.objects
        .filter(provider='telegram', uid=str(telegram_id))
        .select_related('user__user_profile')
        .first()
    )
    if not social:
        return None

    return getattr(social.user, 'user_profile', None)
