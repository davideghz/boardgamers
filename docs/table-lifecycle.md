# Table Lifecycle

## Status

A table has three possible statuses, stored in `Table.status`:

| Status | Value | Meaning |
|---|---|---|
| Open | `open` | The game hasn't started yet. Players can join or leave. |
| Ongoing | `ongoing` | The game is in progress. Joining and leaving are locked. |
| Closed | `closed` | The game is over. Joining and leaving are locked. |

Status transitions are **fully automatic** — there is no manual trigger in the UI. They are computed by the management command `webapp/management/commands/update_table_status.py`, which should be run periodically (e.g. via cron every 15–30 minutes).

## Transition timeline

All times are relative to `game_datetime` (the combination of `Table.date` + `Table.time`, interpreted as `Europe/Rome`).

```
game_datetime - ∞         →  OPEN
game_datetime + 0h        →  ONGOING
game_datetime + 12h       →  CLOSED  (leaderboard still editable)
game_datetime + 2 days    →  CLOSED  (leaderboard locked)
```

The 12-hour ONGOING window is intentionally generous to cover long sessions (e.g. heavy board games, RPG evenings) where the actual play time is hard to predict.

## Leaderboard status

The leaderboard is a separate state field (`Table.leaderboard_status`) that controls whether players can edit their finishing positions:

| Leaderboard status | When |
|---|---|
| `not_editable` | Before `game_datetime`, or after `game_datetime + 2 days` |
| `editable` | From `game_datetime` until `game_datetime + 2 days` |

The 2-day editing window lets players fill in results even if they forget to do it right after the game.

When `leaderboard_status` changes, all players at the table receive an in-app notification (handled in `webapp/signals.py`).

A leaderboard is only active if `Game.leaderboard_enabled` is `True` for the game played at the table.

Player positions are stored as `Player.position` (integer). A value of `99` means the player hasn't been ranked yet.

## Who can do what

### Joining / leaving

Regular users can join or leave only when `table.status == OPEN`.

### Managing players (add / remove / view the players page)

The players management page (`/tables/<slug>/players/`) is restricted to the **table author** and **site admins** (`is_superuser`). They can add and remove players at any time, regardless of table status — this allows correcting mistakes after a game has started or ended.

Regular players who joined themselves can leave only while the table is `OPEN`.

### Editing the leaderboard

A user can edit the leaderboard if **all** of the following are true:

1. They are authenticated
2. `Game.leaderboard_enabled` is `True`
3. `Table.leaderboard_status == EDITABLE`
4. They are a player at the table

Site admins bypass conditions 3 and 4 and can always edit the leaderboard.

## Key files

| File | Role |
|---|---|
| `webapp/models.py` | `Table` and `Player` model definitions |
| `webapp/management/commands/update_table_status.py` | Automatic status transitions (run via cron) |
| `webapp/signals.py` | Notifications triggered on status changes |
| `webapp/views/table_views.py` | Join, leave, add/remove player, leaderboard permission checks |
| `webapp/api/views.py` | API endpoint for saving leaderboard positions |
| `webapp/templates/tables/table_detail.html` | Main table UI (join button, author actions) |
| `webapp/templates/tables/_table_leaderboard.html` | Leaderboard UI (drag-and-drop ranking) |
