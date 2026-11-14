# Contributing to Board Gamers

Thanks for helping out! This file covers how to get a change from your machine into `master`.
For the local setup (PostgreSQL + PostGIS, GDAL/GEOS, `.env`), see the [Readme](Readme.md).

## Workflow

- **`master` is production.** The Heroku pipeline deploys every commit on `master`, and
  migrations run automatically in the release phase. `master` is protected: nobody pushes to it
  directly, every change goes through a pull request, and only the maintainer merges, after
  trying the change locally as an anonymous visitor, a regular user and a location manager.
- Fork the repo (or create a branch if you have access) and open a PR against `master`.
- Keep PRs small and focused on one thing: one feature or one fix per PR.
- Before opening the PR, rebase on the latest `master`.
- For anything bigger than a small fix, open an issue first so we can agree on the approach.
  Some larger designs are written up in [`docs/`](docs/).

## Commits

- Write commit messages **in English**, in the Conventional Commits style used in the history:
  `type(scope): summary`, e.g. `feat(tables): pick guests from a search modal`,
  `fix(forms): don't validate TailwindForm inside __init__`.
- Common types: `feat`, `fix`, `perf`, `refactor`, `docs`, `chore`, `test`.
- Common scopes: `tables`, `locations`, `events`, `leaderboard`, `account`, `users`, `forms`,
  `api`, `admin`, `templates`, `telegram`, `heroku`.

## Tests

There is no CI: tests are run locally, and every PR must say that they pass.

```bash
python manage.py test webapp.tests
```

- The DB user needs the `CREATEDB` privilege (Django creates a throwaway test database), and
  PostGIS must be installable in it.
- On macOS with Homebrew GDAL, you may need `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib` so
  that GDAL/GEOS are found.
- New behaviour should come with tests in `webapp/tests/` (see the existing `test_*.py` files).
  `webapp/factories.py` has factories for the main models.
- Test the permissions too, not only the normal case: a user who isn't allowed gets a 403 or 404.

## Database migrations

Migrations are numbered, and two PRs that both add `00NN_…` will conflict.

- Generate migrations with `python manage.py makemigrations webapp` and commit them in the same PR
  as the model change.
- If `master` gained a new migration while your PR was open: rebase, **delete your migration and
  regenerate it** so that it depends on the latest one. Don't commit merge migrations.
- Data migrations must be reversible, or at least safe to run on production data: they run
  automatically on deploy. Running one twice must do no harm.
- New fields need a sensible default, so existing rows stay valid. Avoid operations that lock a
  big table for a long time.

## Translations (i18n)

The UI is in Italian (default) and English. All user-facing strings go through `gettext` /
`{% translate %}`, written in English in the code; the Italian translations live in
`webapp/locale/it/LC_MESSAGES/django.po`.

```bash
python manage.py makemessages -l it --no-location -i "venv/*"
python manage.py compilemessages
```

- Always use `--no-location` (see the Readme for why).
- Both `django.po` and `django.mo` are committed. The `.mo` is binary and conflicts on every
  rebase: after rebasing, regenerate it with `compilemessages` instead of resolving it by hand.

## Frontend

- **Tailwind CSS via the Play CDN**, configured at runtime in `webapp/templates/base.html`.
  There is no build step and no Bootstrap (the `TailwindForm` base and the `Custom*Widget`
  classes in `webapp/forms.py` render Tailwind markup).
- Use the semantic color tokens (`bg-background`, `bg-surface`, `text-content`,
  `text-content-muted`, `border-divider`, …) instead of raw grays, so dark mode keeps working.
  Global overrides live only in the `<style>` block of `base.html`.
- Corner radius follows the size of the element (Tailwind defaults, not redefined):

  | Class          | Use                                                                 |
  |----------------|---------------------------------------------------------------------|
  | `rounded-full` | buttons, badges, avatars, chips                                     |
  | `rounded-2xl`  | page-level blocks: heroes, modals, CTA banners                      |
  | `rounded-xl`   | the default: cards, panels, list rows, form fields                  |
  | `rounded-lg`   | elements inside a card: thumbnails, icon boxes, sidebar items       |
  | `rounded-md`   | buttons inside a segmented toggle, small icon buttons in the header |
  | `rounded`      | checkboxes, tiny badges on cards                                    |

  A nested element gets a smaller radius than its container (e.g. a `rounded-lg` toggle with
  `rounded-md` buttons inside), so the edges stay parallel.
- Icons are inline SVG (Heroicons style). No icon fonts.
- Interactions are vanilla JS inline in the template. No Alpine.js, no frontend framework.
- Templates extend `base_webapp.html`. Card partials live in `webapp/templates/tags/`.
- Check your change in both light and dark mode, and at phone width.

## Code

- Models are in `webapp/models.py`, forms in `webapp/forms.py`, views in `webapp/views/`,
  business logic shared between views in `webapp/services/`.
- Location permissions: use `location.is_manager(user_profile)` instead of checking
  `creator` / `managers` by hand.
- Follow the style of the surrounding code (naming, comment density, idioms).
- Don't commit secrets, `.env`, production data dumps, or IDE folders.

## Security

- Every view that changes data checks permissions (see [Code](#code)) and only accepts POST.
- Objects taken from the URL belong to the location or user they claim to: changing an id in the
  URL must not give access to someone else's data.
- User content is rendered through `render_markdown` or Django's auto-escaping. No new `|safe`
  on user input. Email templates sent through AWS SES are not escaped by SES, so values must be
  escaped before they are passed in.
- Uploads have a size and type limit, and images are resized like the existing ones.
- New personal data (contacts, member data) is visible only to who needs it.
- Don't open public issues for vulnerabilities: see [SECURITY.md](SECURITY.md).

## Performance

- No extra queries on high-traffic pages (home, location, event and table pages) unless needed.
  Watch for N+1 queries in templates: use `select_related` / `prefetch_related`, and consider an
  `assertNumQueries` test for hot pages.
- New filters or orderings on large tables come with an index.
- Lists that can grow are paginated or capped.
- No slow work inside the request: Heroku cuts requests at 30 seconds and there are few workers.
  Sending many emails, calling external services in a loop or processing big files goes in
  smaller chunks or in a management command.
- New external dependencies (Python packages, CDN scripts, third-party APIs) need a good reason.

## UX

- New features are opt-in where possible: off or hidden until a user or manager turns them on,
  like the member registry (`enable_membership`).
- Existing flows don't get harder: no new required fields or extra steps for users who don't use
  the new feature.
- Notifications respect the user's settings and don't flood: one notification for a batch of
  changes, not one per change.
- New public pages have a title and meta/Open Graph tags, like the existing ones.

## Pull request checklist

The PR template repeats this list:

- [ ] Rebased on the latest `master`
- [ ] `python manage.py test webapp.tests` passes locally
- [ ] Migrations regenerated after rebase (if any)
- [ ] `.po` updated and `.mo` recompiled (if strings changed)
- [ ] Checked in light and dark mode and on mobile (if UI changed)

## License

By contributing, you agree that your contributions are licensed under the
[GNU AGPL-3.0](LICENSE), the license of the project.
