---
name: ui-change
description: Rules and checks for every change to the Board Gamers interface. Use it before touching anything a user sees (templates, template tags, components, inline CSS/JS, user-facing strings, or view context that changes what a page shows or which actions it offers), and follow its verification steps before calling the change done.
---

# Changing the interface

Every change a user can see follows this skill. It sits on top of the Frontend and Translations
sections of `CONTRIBUTING.md` and the words in `docs/ui-glossary.md`: read those too, they win
on anything they cover.

## 1. Start from the personas

Each page is seen by several audiences, and each must get the right actions, never an invite that
is already satisfied or impossible. Before writing code, list which of these personas the change
touches and what each should see and be able to do afterwards.

| Persona | Demo user (`<persona>@ui-demo.example.com`) | Who they are in the demo data |
|---|---|---|
| Visitor | none (anonymous) | Sees what is public; every action goes through the login. |
| Newcomer | `newcomer`, demo_nuovo | Signed up, city set, no ties: follows nothing, member of nothing. |
| Player | `player`, demo_giocatore | Follows the Negozio, plays two tables, attends an event and a festival day, membership pending at the Circolo. |
| Member | `member`, demo_socio | Active member of Circolo and Associazione, created a members-only table, attends the evenings, proposed a draft event. |
| Manager | `manager`, demo_gestore | Manages the Negozio, created Circolo and Associazione; author of most demo tables and events. |
| Organizer | `organizer`, demo_organizzatore | Runs the Manifestazione Demo only: no location, table or membership. |

The data comes from `webapp/services/ui_personas.py` (`seed_ui_personas`), on a DEBUG database:
`python manage.py seed_ui_personas` (`--reset` to recreate it). On the running demo, `/dev/personas/`
(DEBUG only, linked from the login page) signs in as any persona with one click, or out as a visitor.
The password is the `PASSWORD` constant there: never paste it in chat, commits or PRs. If the change needs a situation the demo
data lacks, extend `seed_ui_personas` rather than building it by hand.

Rules that hold for every persona:

- Each one finds their own things: what they play, attend, organize, propose or manage shows
  up in Home ("Le tue prossime attività") and in My activities, drafts included for who made them.
- No invite that makes no sense for the viewer: a manager is not asked to follow or join their own
  location, a member is not asked to become one, a visitor's action leads to the login and back.
- When an action is not allowed, say why (sign in, members only, membership pending, managers
  only) instead of hiding it silently.

## 2. Use what exists

Look at `/dev/ui/` (DEBUG only: every component in both themes) before writing markup. New markup
for something a component already does is a bug.

**Components** (`webapp/templates/components/`, tags in `webapp/templatetags/custom_tags.py`):

| Need | Use |
|---|---|
| Page title, count, main action, back link | `page_header`, `back_link` (its label names the destination) |
| Buttons | `button` (primary, secondary, danger; two sizes) |
| States, types, roles | `status_badge` (words of the glossary), `type_badge`, `role_badge`, `badge` |
| A row in any list of tables, events, festivals | `appointment_row` (built on `result_row`) |
| A card with a cover (home, location page) | `table_card`, `event_card`, `festival_card` |
| Nothing to show | `empty_state`, with `access` when the reason is a permission |
| Detail page actions | `action_bar`: Edit straight to the data form, Manage, More (Duplicate, Share) |
| Creating things | `create_menu` ("+ Crea"), only with the entries the viewer may use |
| Management panels | `todo_card` for what waits for an answer, `manage_tile` for the tools |
| "You're in" / "You're attending" | `participation_status`; `joined_dialog` after joining |
| Confirming a POST | `confirm_dialog` (a `<dialog>`); never `confirm()` |
| Form errors | `error_summary` at the top and `field_errors` by each field (aria-describedby, aria-invalid) |
| Icons | `icon` / `components/icon.html` (inline SVG, Heroicons style); add new ones there |
| Menus that pop over | `popover` + `data-popover-menu` (positioned by the script in `base_webapp.html`) |

**Who may do what** comes from code, not from template conditions:

- `get_viewer(request)` in views and `viewer` in templates (`webapp/services/viewer.py`): roles,
  `relation(location)`, `can_create_events`, `own_location_ids`, `managed_location_ids`, and the
  `*_access(location)` helpers that return a `LocationAccess` with `allowed` and the reason.
- `location.is_manager(user_profile)` for location permissions. Never rebuild chains like
  `is_manager or permission == …` in a template; compute once in the view and pass the result.
- Managers can preview a location as a visitor with `?as=visitor`: keep that working.

## 3. Follow the page patterns

- **Lists** follow Search (`search/appointments.html`): `page_header` with the count, a segmented
  control for the type, a text field and "Filtri" (a `<dialog>` under `lg`, a side column from `lg`),
  chips for the active filters with remove and "Azzera", `appointment_row`, pagination with
  `{% querystring %}`. Filters are plain GET forms: the page works without JavaScript and the URL
  keeps the state.
- **Detail pages** have one `action_bar` with only the allowed actions. The page's main action
  (join, create a table here, attend) sits in the side column on desktop and in the one fixed bar on
  phones: never twice on the same screen.
- **Creating** goes through "+ Crea"; ask for the context (which location) only when it is not
  known, and offer only the locations where the viewer may create.
- **Management** is a panel by task: "In attesa di te" first (`services/manager_todo.py`), then the
  tools grouped by what one wants to do.
- **Home** is made of modules by role: to-do, next activities, my locations, first steps, discover.
- **Rows or cards, the same for every kind.** Lists to scan (Search, Tavoli, Eventi,
  Manifestazioni, My activities, management lists) use `appointment_row`. Showcases with covers
  (the home's discover sections, a location's events) use cards: `table_card` for tables,
  `event_card` / `festival_card` for events and festivals (one template, `tags/event_card.html`).
  Sections side by side use the same form: never rows for one kind and cards for another.
- **Covers.** Everything listed with an image (locations, tables, events, festivals) has a
  `cover_url` that never comes back empty: its own image, else a fallback (an event uses its
  organizer location's cover, a table its game's), else the static default named in
  `settings.DEFAULT_*_COVER_URL` (`boardGames/static/images/*.webp`, flat illustrations in the
  site's palette). Templates always use `cover_url`, never the field or a related object's cover.
  - The field is a `ManagedImageField(..., max_side=COVER_MAX_SIDE)` on a model that inherits
    `DateTimeModel`, so the file is normalized and removed when replaced.
  - Forms use `CroppedCoverMixin` (optional, 5 MB limit, the file input the partial expects)
    and the view passes `request.FILES`; the form tag has `enctype="multipart/form-data"`.
  - The page renders it with `partials/_cover_field.html` (variant `location`, `crop_ratio` and
    `preview_ratio` of the place where it is shown: 16:9 / `video` for events and festivals,
    square for locations) and a help text saying which image is used without one.
  - The cover reaches the page through the shared row and card components; a new kind of item
    gets a branch in them (as festivals did in `appointment_row` and `event_card`), not markup
    of its own. Events and festivals share their days through `ScheduleMixin`.

## 4. Style, words and accessibility

- Semantic color tokens only (`bg-surface`, `text-content`, `text-content-muted`, `text-link`,
  `border-divider`, `bg-primary`, `text-danger`, `bg-success-soft`, …): no raw grays, blues or hex
  values, so dark mode keeps working. Radius by size, as in the table in `CONTRIBUTING.md`.
- Tailwind Play CDN, vanilla JS inline, no Alpine, no new frontend dependency.
- Every user-facing string is translatable, in English in the code, with the Italian word from
  `docs/ui-glossary.md`. Use a translation context (`pgettext` / `{% trans … context "…" %}`) when
  an English word is ambiguous, reusing an existing context where one fits (search for `context "`
  in the templates and `pgettext` in the Python code), e.g. `status`, `navigation`, `page actions`.
- Every page sets its own title (`meta.title`); `base.html` adds the site name.
- Links and buttons have a visible `focus-visible` ring; the current menu entry has
  `aria-current="page"`; dialogs close with Escape and return focus; form fields have labels.
- Layout works at 375 px: nothing scrolls sideways, the first result or the main action is visible
  without scrolling.

## 5. Verify before calling it done

1. **Tests per persona.** Add or extend a test that seeds `seed_ui_personas()` in
   `setUpTestData` and checks, for each persona the change touches, what is shown and what is not
   (see `test_action_bar.py`, `test_home_modules.py`, `test_own_activities.py`). Italian text in
   assertions goes through `italian()` from `test_location_table_access.py`. A new page goes in
   `test_ui_smoke.py`. Then run the whole suite: `python manage.py test webapp.tests`.
2. **Strings.** `makemessages -l it --no-location -i "venv/*" -i ".venv/*"`, translate every new
   or fuzzy entry following the glossary, then `compilemessages`. Commit `.po` and `.mo`.
3. **Look at it as each persona,** on the demo data, at 375 px and at desktop width, in the light
   and the dark theme. The demo server runs with `--noreload`: restart it after changing Python
   code or templates. In the browser, switch persona from `/dev/personas/`. To check a page from a
   script, render it with the test client and open the copy:

   ```python
   # python manage.py shell, on the demo database
   from django.test import Client
   from django.test.utils import setup_test_environment
   from webapp.models import UserProfile
   from webapp.services.ui_personas import email_for
   setup_test_environment()
   client = Client(HTTP_HOST='127.0.0.1:8139')
   client.force_login(UserProfile.objects.get(user__username=email_for('member')).user)
   open('boardGames/static/_page.html', 'w').write(client.get('/the/page/').content.decode())
   ```

   Open `/static/_page.html` on the demo server, remove `#djDebug` if it is in the way, and
   **delete the `_*.html` copies when done**.
4. **A new component** goes in `/dev/ui/` (`dev/_ui_gallery_items.html`) with a rendering test.
5. **Report** which personas you checked and how, and anything you could not verify.
