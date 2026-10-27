# Board Gamers — notes for AI coding assistants

Read [CONTRIBUTING.md](CONTRIBUTING.md) first: workflow, tests, migrations, translations and
frontend rules all live there. This file only adds the context an assistant tends to get wrong.

## What the app is

Django + GeoDjango app for organizing board game sessions at physical venues (associations,
game libraries, shops). Main concepts, all in `webapp/models.py`:

- `UserProfile`: extends `User` (nickname, avatar, language, notification settings).
- `Location`: a venue, with a `creator`, `managers` and a PostGIS point.
- `Table`: a game session at a location; players join through the `Player` model.
- `Event`: a multi-table event (convention style) at a location.
- `Member` / `Membership`: the venue's member registry and membership periods.

## Things that are easy to get wrong

- `master` deploys to production on every commit. Never push to it; open a PR.
- The frontend is **Tailwind via the Play CDN**, not Bootstrap, and has no build step.
  Use the semantic color tokens so dark mode works. No Alpine.js: vanilla JS inline.
  Icons are inline SVG.
- Location permissions go through `location.is_manager(user_profile)`.
- User-facing strings must be translatable (English in code, Italian in `django.po`).
  After changing strings, run `makemessages -l it --no-location -i "venv/*"` and
  `compilemessages`.
- Run tests with the label: `python manage.py test webapp.tests`.
- Commit messages in English, `type(scope): summary`.
- Match the surrounding code: naming, comment density, idioms.

## Layout

- `boardGames/`: settings (`settings.py`, `local_settings.py`, `production_settings.py`), URLs.
- `webapp/views/`: views, split by area (`table_views.py`, `location_views.py`, …).
- `webapp/services/`: business logic shared between views and commands.
- `webapp/api/`: JSON endpoints; Django REST Framework is used only for the public widget and the
  BoardGameGeek search.
- `webapp/templates/`: `base.html` (Tailwind config and global styles), `base_webapp.html`,
  one folder per area, card partials in `tags/`.
- `webapp/templatetags/custom_tags.py`: template filters, including `render_markdown`
  (`mistune` + `nh3` sanitization).
- `webapp/management/commands/`: scheduled jobs and utilities (see the Readme).
- `docs/`: design notes for larger features.
