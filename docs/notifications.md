# Notification System

## Overview

There are two layers of notifications:

- **In-app notifications** — stored in the `Notification` model, displayed in `/account/notifications/` and counted in the header badge.
- **Email notifications** — driven by the same `Notification` records via management commands, and in a few cases sent immediately on signal.

The two layers share the same database records. The `sent` field on `Notification` is the flag that batch email commands use to know what still needs to be delivered.

---

## In-app notifications

### Model fields

| Field | Purpose |
|---|---|
| `recipient` | Target user (FK → UserProfile) |
| `notification_type` | Category (see below) |
| `table` / `location` | Optional context links |
| `message` | Optional free-text body |
| `is_read` | Marked `True` when the user visits `/account/notifications/` |
| `sent` | Marked `True` after an email has been sent for this record |
| `sent_at` | Timestamp of email delivery |

### Notification types

| Type | Trigger | Recipients |
|---|---|---|
| `new_table` | Table created | Followers of the location |
| `new_player` | User joins a table | Other players at the table |
| `new_comment` | Comment posted | All players at the table |
| `leaderboard_editable` | Leaderboard opens for editing | All players at the table |
| `leaderboard_updated` | A player's position is saved | All players at the table |
| `leaderboard_closed` | Leaderboard locks | All players at the table |
| `table_closed` | Table transitions to CLOSED | All players at the table |
| `table_deleted` | Table is deleted | All players at the table |

All types are created by Django signals in `webapp/signals.py`.

### User preferences

Each user can opt out of specific email types. The flags live on `UserProfile`:

| Flag | Controls |
|---|---|
| `notification_new_table` | Emails for new tables |
| `notification_new_player` | Emails for new players joining |
| `notification_new_comments` | Emails for new comments |
| `notification_leaderboard_reminder` | Emails when leaderboard opens |
| `notification_leaderboard_update` | Emails when leaderboard is updated |

These are editable at `/account/notifications/edit`.

---

## Email notifications

### Immediate emails (synchronous, on signal)

A handful of emails are sent inline at signal time, without going through the batch queue:

| Event | Function (in `webapp/emails.py`) |
|---|---|
| New user registration | `send_user_email_verification_code()` |
| Table deleted | `send_email_notification_deleted_table()` |
| Admin contact form | `send_admin_contact_message()` |

These call Django's `send_mail` directly and block the request.

### Batch emails (asynchronous, via management commands)

The two remaining email types are handled by management commands that should be run on a cron schedule. Both work by querying in-app `Notification` records that have `sent=False` and delivering the email, then flipping `sent=True`.

There is no task queue (Celery, RQ, etc.) — scheduling is external.

---

## Batch command: `send_queued_notifications`

**File**: `webapp/management/commands/send_queued_notifications.py`

**What it sends**: one email per `new_table` notification that has `sent=False`.

**How**: uses **boto3 directly** to call `SES.send_bulk_templated_email()`. This is a true AWS SES bulk send — all recipients in a batch share the same SES template (`NewTableNotification`), with per-recipient placeholder variables (`ReplacementTemplateData`). Batches are capped at 50 destinations per API call (AWS limit).

**Filtering**:
- `sent=False`
- `notification_type='new_table'`
- `recipient.notification_new_table=True` (if False, the record is still marked sent without sending)
- `recipient.user.email` must be non-empty

**Template variables per recipient**: `name`, `title`, `game`, `date`, `time`, `location_name`, `button_href`.

**After sending**: sets `sent=True`, `sent_at=now()` on all processed records in a single `UPDATE`.

**Production only**: the command exits early if the AWS settings (`AWS_SES_REGION_NAME`, `AWS_SES_ACCESS_KEY_ID`, `AWS_SES_SECRET_ACCESS_KEY`) are not configured.

---

## Batch command: `batch_notification`

**File**: `webapp/management/commands/batch_notification.py`

**What it sends**: one digest email per user for all their unread `new_comment` notifications.

**How**: calls `send_batch_notification_new_messages()` from `webapp/emails.py`, which renders a standard HTML email template and sends it via `django-ses` (the same path as all other Django `send_mail` calls). There is **no SES bulk API** here — each user gets an individual `send_mail` call.

**Filtering**:
- `sent=False`
- `is_read=False` — comments the user has already read in-app are excluded
- `notification_type='new_comment'`
- `recipient.notification_new_comments=True`
- `recipient.user.email` must be non-empty

**Grouping**: notifications are grouped by `(recipient → table)`. The resulting email lists each table separately with its unread comment count and a direct link.

**After sending**: marks each processed `Notification` record individually as `sent=True`, `sent_at=now()`.

---

## Comparison at a glance

| | `send_queued_notifications` | `batch_notification` |
|---|---|---|
| Notification type | `new_table` | `new_comment` |
| Also filters `is_read=False` | No | Yes |
| Email delivery | boto3 → SES bulk API (50/call) | `send_mail` via django-ses (one per user) |
| Template | AWS SES stored template | Django HTML template |
| Grouping | One email per notification | One digest per user (all tables) |
| Production only | Yes (requires AWS settings) | No |

---

## Supporting commands

| Command | Purpose |
|---|---|
| `setup_ses_template` | Creates or updates the `NewTableNotification` template on AWS SES |
| `manage_notifications` | Utility: mark all as sent/read, or delete all |
| `cleanup_old_notifications` | Deletes notifications older than N days (default: 30) |

---

## Key files

| File | Role |
|---|---|
| `webapp/models.py` | `Notification` model, `NotificationType` choices, `UserProfile` preference flags |
| `webapp/signals.py` | Creates `Notification` records on every relevant event |
| `webapp/emails.py` | Email sending functions |
| `webapp/management/commands/send_queued_notifications.py` | SES bulk batch for `new_table` |
| `webapp/management/commands/batch_notification.py` | Digest batch for `new_comment` |
| `webapp/management/commands/setup_ses_template.py` | AWS SES template setup |
| `webapp/context_processors.py` | `unread_notifications_count` for the header badge |
| `webapp/templates/accounts/account_notifications.html` | In-app notifications UI |
| `webapp/templates/emails/` | HTML email templates |
| `boardGames/production_settings.py` | AWS SES credentials and region |
