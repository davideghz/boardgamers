# Banners

Manage banners in **Administration → Other → Banners**. New banners are inactive until enabled.
The contributor invitation is created by migration `0103_seed_contributor_banner` without a cover.

Each banner has:

- A stable identifier and a positive version. Increase the version for a substantially new
  message, not for copy corrections: each version has its own dismissal preference.
- Italian and English title, message, link text and cover description. Messages are plain text.
- An optional PNG, JPEG or WebP cover, up to 5 MB and 8192 pixels per side. New uploads are
  resized using `ManagedImageField(max_side=COVER_MAX_SIDE)` and the shared image pipeline
  (1200-pixel maximum side). Transparency is preserved in PNG; opaque resized covers use JPEG.
  Replaced, cleared and deleted covers are removed only after commit, when no image field in
  the same storage still references the file. No banner-specific resize or cleanup signal is
  needed: `Banner` inherits `ManagedImagesModel` through `DateTimeModel`.
  The cover appears above the message on phones and beside it on larger screens. Leave the
  description empty for a decorative image.
- An optional link: a path beginning with `/`, or an HTTP/HTTPS URL. Internal paths follow
  the current site language. Following a link does not mark an action as completed or close
  the banner.
- An audience (everyone, anonymous visitors or authenticated users), placement (home or all
  pages), priority and optional start/end dates. The start is inclusive and the end exclusive.
- A closing policy: permanently or for a number of days. Closing is remembered for the browser,
  shared by anonymous visitors and every account using it. It does not synchronize across devices.

The server filters candidates and sends at most the first 20, ordered by descending priority
and then creation ID. The browser shows the first candidate that has not been dismissed.
Closing it hides it immediately; another banner is eligible on the next navigation, rather
than appearing immediately in its place. Dismissals in another tab and history restoration
are also handled.

Permanent and timed dismissals use `localStorage`, with keys of the form
`bg:banner:<identifier>:v<version>:browser`. Existing browser dismissal keys are preserved.
Clearing browser data clears these preferences. Unavailable storage does not prevent immediate
closing; unreadable preferences keep promotional banners hidden.

Earlier `alertClosedTimestamp` preferences become permanent dismissals for `contributor-invite`,
version 1, including timestamps older than 24 hours and even if the banner uses timed closing.
This preserves the choice of users who already closed the invitation; increase the banner
version to show a new message.
Dismissals never write to the profile or call a server endpoint.

These are informational banners. Account requirements such as email verification must continue
to be checked on the server, independently of banner dismissal.

Checks:

```sh
.venv/bin/python manage.py test webapp.tests --keepdb --noinput
```
