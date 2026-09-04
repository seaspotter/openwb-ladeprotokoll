# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A standalone tool that polls one or more openWB installations' charge-log
data (`data/charge_log/<yyyymm>.json`, served anonymously over plain HTTP,
no core changes needed) into Postgres, and turns it into audit-safe PDF
charging-cost reports mirroring openWB's own Ladeprotokoll UI table.
Originally scoped around German company-car tax reporting, but the user
explicitly asked (2026-09-04, after first real-world use) to drop that
framing and the term "Dienstwagenabrechnung" everywhere — don't reintroduce
it in code, docs, or the PDF; keep this generic ("charging-cost report").
Named after the Ladeprotokoll page so it's discoverable to openWB users
searching for it. Built as a sibling project rather than a PR into openWB
core because core already sells a paid version of this same report.
Sibling project: `../openwb-logger` (same author, same
Docker+Postgres+CLAUDE.md/CHANGELOG.md conventions) — worth checking there
first for how a pattern is usually done in this family of tools before
inventing a new one here.

Full picture in `README.md`; details in `DEVELOPMENT.md` and
`DEPLOYMENT.md`. `MANUAL.md` is the end-user guide (German).

## Architecture

- `app/config.py` — **infra-level** config only, read once from env vars
  at import time: `DATABASE_URL`/`POSTGRES_PASSWORD`. Nothing about a
  specific openWB installation lives here — that's user data, stored in
  the `sources` table and added/edited from the web UI.
- `app/db.py` — asyncpg pool, idempotent schema bootstrap (`CREATE TABLE
  IF NOT EXISTS`, no migration tool). Full schema for `sources`,
  `sessions`, `price_entries`, `reports`, `report_sessions`,
  `report_settings`, `vehicles`, `app_settings` already lives here — see
  the module for the natural-key and audit-snapshot reasoning inline.
  `vehicles` (`vehicle_name` PK, `license_plate`) is purely user-entered
  metadata — openWB's own charge-log JSON has no Kennzeichen field at all
  — so it's a plain new `CREATE TABLE`, no additive `ALTER` needed.
  `app_settings` is a second single-row settings table alongside
  `report_settings`, deliberately kept separate since it's unrelated to
  report generation — see `app_settings.py`.
- `app/sources.py` — **pure**: `Source` dataclass plus `base_url`
  validation/normalization (bare IP, host:port, or full URL, all
  normalized to `scheme://host[:port]` with no trailing slash). Unit
  tested.
- `app/chargelog_parse.py` — **pure**: one raw charge-log JSON record ->
  a normalized `sessions` row + its natural key
  `(source_id, chargepoint_serial_number, time_begin)`. Field mapping was
  cross-checked twice against real data from the same openWB installation
  (2026-09-03): a CSV export of the Ladeprotokoll UI, then an actual
  `chargelog-*.json` file (all 35 records in the sample parse cleanly, no
  duplicate natural keys, no anomalous implied €/kWh price). Four
  load-bearing corrections came out of that, worth knowing before touching
  this file: the UI's plain "Energie" column (the one to sum for a report
  total) is `data.imported_since_mode_switch`, a *per-row* figure — not
  `imported_since_plugged`, which is *cumulative* since plug-in and
  double-counts if summed across a session's rows; `time.time_charged` is
  "H:MM" (no seconds), not "H:MM:SS"; `time.begin`/`time.end` are
  `"MM/DD/YYYY, HH:MM:SS"` strings, not epoch numbers as first assumed;
  and every energy figure (`imported_since_*`, the chargepoint meter
  readings) is in **Wh**, and `power_source.{grid,cp,bat,pv}` are
  **fractions (0.0-1.0)**, not already the kWh/percentage units the
  `sessions` columns are named for — `chargelog_parse.py` converts on the
  way in. Still unconfirmed: an actual nonzero V2H/V2G discharge value
  (`exported_since_mode_switch` exists in every record but has only ever
  been 0). See the module docstring for full detail. Unit tested.
- `app/openwb_client.py` — httpx GET of one source's
  `data/charge_log/<yyyymm>.json`. A 404 means "no sessions that month
  yet" and returns `[]`, not an error.
- `app/fetch_service.py` — orchestrates month list -> `openwb_client` ->
  `chargelog_parse` -> idempotent `ON CONFLICT ... DO UPDATE` upsert.
  Single code path for every trigger (manual fetch-now, daily scheduler,
  on-demand backfill); a per-source `asyncio.Lock` stops those racing on
  the same source.
- `app/scheduler.py` — daily background fetch: refetches the current month
  for every enabled source, once at startup, then daily at a configurable
  wall-clock time (`app_settings.auto_fetch_time`, default `00:05`) rather
  than a fixed 24h-from-startup interval — `_next_run_at`/`_parse_time` are
  pure and unit tested, computing "seconds until the next occurrence of
  that HH:MM" fresh each cycle so a changed setting takes effect from the
  next wake (not instantly, same as the enabled flag below — accepted as
  simple and consistent rather than adding a way to interrupt an in-
  progress sleep). Can be disabled entirely via `app_settings
  .auto_fetch_enabled` (the "Automatischer Abruf aktiv" checkbox in
  Einstellungen -> Quellen) — the loop keeps running either way, just
  skipping the fetch (including the startup one) while disabled, so
  re-enabling doesn't need a restart. Runs as an `asyncio` task started in
  `main.py`'s lifespan; reuses `fetch_service.fetch_source` (same
  per-source lock, same upsert), so it can't race a concurrent manual
  fetch-now/backfill on the same source.
- `app/app_settings.py` — thin, mirrors `report_settings.py`'s pure
  `validate()` + upsert-on-first-read pattern for the single-row
  `app_settings` table (`auto_fetch_enabled`, `auto_fetch_time` as an
  `"HH:MM"` string, regex-validated). Read by both `web.py`'s `GET/PUT
  /api/app-settings` and `scheduler.py`'s own loop directly (not via an
  HTTP call) — kept as its own module specifically because it has two
  in-process callers, unlike `vehicles`, which only web.py touches and so
  stayed as inline SQL there.
- `app/price_entries.py` — **pure**: electricity price correction. A price
  entry is scoped per source (optional) and per vehicle name (optional),
  both nullable as wildcards. `match_price_entry` ranks candidates by
  specificity (source+vehicle > source-only > vehicle-only > wildcard,
  tie-broken by most recent `created_at`); `decide_price` combines a
  matched (or overridden) entry with a session's own `energy_kwh`/
  `cost_openwb` into the corrected cost, which cost to actually use (falls
  back to openWB's own when no entry applies), and whether the delta
  exceeds `DELTA_FLAG_THRESHOLD` (0.01). Always prices `energy_kwh`
  (per-row), never `energy_since_plugged_kwh` (cumulative) — see
  `chargelog_parse.py`'s docstring for why that distinction matters. Unit
  tested.
- `app/report_build.py` — **pure**: sessions + a selected column list +
  a `cost_basis` ("openwb" or "corrected") + each session's resolved price
  decision -> the `ReportData` structure (formatted display cells,
  deduplicated price-basis block, totals) the template renders and that
  gets frozen into `report_sessions.snapshot`. `COLUMN_LABELS` is the
  single source of truth for the 13 selectable columns (also served at
  `GET /api/report-columns` for the review UI) — note there is only ever
  **one** `cost` column/total ("Kosten"), not separate openWB/corrected
  ones side by side (a deliberate simplification per user feedback); which
  underlying figure it shows is `cost_basis`, itself set once in
  `report_settings.py`, not per-column. `ReportTotals` still keeps both
  raw `cost_openwb`/`cost_corrected` sums internally (needed for the
  `reports` table's own two total columns — no schema change was needed to
  add this) even though the template only ever prints the one matching
  `cost_basis`. Rows are always sorted chronologically ascending (oldest
  first, latest at the bottom — a printed ledger reads that way) regardless
  of what order sessions arrive in. Unit tested.
- `app/report_settings.py` — thin: a single-row `report_settings` table
  (id=1, `CHECK`-enforced) holding `default_columns` (the *only* column
  selection — see `_settings_modal.html`), `cost_basis`, `orientation`
  ("portrait"/"landscape"), and `show_signature_line` — edited from
  Einstellungen's "Berichts-Einstellungen" panel via `GET/PUT
  /api/report-settings`. `validate()` is pure and unit tested;
  `get_settings`/`update_settings` do the DB round trip (upsert-on-first-
  read, so there's no separate seeding step) — verified with an
  integration test that a setting written via `PUT` survives a completely
  fresh `GET` (simulating a page reload), since a user once reported
  settings "not remembered" (root cause was the now-removed duplicate
  column picker on `report_review.html`, not this module).
- `app/pdf_render.py` — Jinja2 (`templates/report_pdf.html`) + WeasyPrint.
  One template renders both the HTML preview and the actual PDF — `@page`
  rules WeasyPrint honors are simply ignored by a browser. The page is
  **portrait** by default, but `orientation` is now a real setting
  (`report_settings.py`, `ReportMeta.orientation`, `@page { size: A4{{ "
  landscape" if ... }}; }`) — portrait fits a lean column selection
  comfortably, landscape is there for whenever more columns are selected
  than portrait's ~17cm printable width can hold; this went back and
  forth (landscape -> portrait -> configurable) based on real feedback
  from real reports, don't collapse it back to a hardcoded default. The footer
  (disclaimer + optional signature line, `ReportMeta.show_signature_line`)
  has `page-break-inside: avoid` — without it, WeasyPrint can push just the
  signature line onto its own near-blank trailing page; the disclaimer
  itself is intentionally one sentence only (the redundant "changes to the
  source data afterward don't affect this already-generated document"
  follow-up sentence was cut per user feedback — the document being
  immutable is already true and doesn't need spelling out twice). The
  header's logo-to-title gap is `gap: 36px` on `header.doc-header` (went
  12px -> 22px -> 36px across two rounds of user feedback from actual
  screenshots — 22px still read as "too close" to the user even after
  confirming via the disclaimer text that the PDF really was rendered with
  the current template, not a stale one; don't shrink this back down
  without a real screenshot showing it's now too loose). The document
  deliberately never displays its own `report_id` — only the user-given
  `title` — per user feedback that a bare "Bericht 3" was meaningless; the
  id still drives the PDF's filename/URL behind the scenes.
  `ReportMeta.vehicle_names` (`web.py`'s `_report_meta`) is
  already-formatted display strings, not bare names — each vehicle with a
  `vehicles.license_plate` set is rendered `"<name> (<plate>)"` in the
  "Fahrzeug(e)" meta line, so the Kennzeichen ends up documented on every
  report without needing its own column. The "Kosten" column/cell never
  gets the red `.flagged` styling that `index.html`/`report_review.html`
  use for a session whose corrected cost diverges from openWB's own value
  — that highlighting is deliberately a review-time aid for deciding what
  to include in a report, not something that belongs in the final,
  immutable document itself (explicit user feedback after seeing it in a
  generated PDF); `row.delta_flagged` is still computed and present in
  `ReportData` for the pages that do use it, the PDF template just ignores
  it.
- `app/web.py` — FastAPI routes for source CRUD, fetch triggers, price
  entry CRUD (including price-entry `notes`), vehicle Kennzeichen CRUD,
  report-settings, app-settings (`GET/PUT /api/app-settings`, the same raw
  `patch: dict` + `validate()`-raises-400 pattern as report-settings, not
  a pydantic model — needed since it's a partial update of two unrelated
  fields), session listing (enriched with each session's matched
  price decision; filterable by source/vehicle/**chargepoint**/date), and
  report preview/generate/list/pdf/delete. Plain parameterized SQL via
  asyncpg, no ORM. asyncpg returns `NUMERIC` columns as `Decimal`; anything
  feeding `price_entries.py`/`report_build.py` converts to `float` first
  (`_to_float`), since those modules are written and tested against plain
  floats. A generated report is built in two DB steps: insert the
  `reports` row first (to get a real id, needed for the PDF's
  filename/URL even though the document body itself no longer shows it),
  *then* render the PDF and `UPDATE` the row with the bytes — one
  transaction, so a failure partway leaves nothing behind. `body.columns
  or settings["default_columns"]` (not `report_build.py`'s own
  all-columns fallback) is what "no columns specified" actually falls back
  to, so an API caller that omits `columns` gets the user's configured
  default, not every column.
  `GET /api/vehicles` returns every vehicle name ever seen across all
  sources' sessions (`SELECT DISTINCT ... FROM sessions`), left-joined with
  its optional `vehicles.license_plate` — not just the rows that happen to
  have a plate set, so the settings UI can always show an input for every
  known vehicle. `PUT /api/vehicles/{vehicle_name}` upserts
  (`ON CONFLICT (vehicle_name) DO UPDATE`); a `null` `license_plate`
  clears it, there's no separate delete route.
  `GET /reports/{id}/pdf`'s filename is `"<YYYYMMDD> Ladeprotokoll
  <title>.pdf"` (`_pdf_filename`, date-prefixed so files sort
  chronologically wherever they're saved) via
  `Content-Disposition: ...; filename="..."; filename*=UTF-8''...`
  (`_content_disposition`, RFC 6266) — the extended `filename*` parameter
  carries the real UTF-8 title (German titles routinely have umlauts), the
  plain `filename` is an ASCII-only fallback for user agents that don't
  read the extended one.
- `app/updater.py` — optional in-app self-update (`git pull` + process
  restart), identical pattern to `openwb-logger/app/updater.py`. Works
  because `docker-compose.yml` bind-mounts the repo onto the container's
  `WORKDIR`.
- `app/main.py` — app factory, lifespan (DB pool, starts/cancels the
  scheduler task).
- `app/templates/index.html` — the landing page (`/`): a read-only charge-log
  overview (filter by source/vehicle/chargepoint/date — vehicle and
  chargepoint are `<select>`s populated from the currently-loaded sessions,
  not free text, so filters can't typo their way to zero results) plus a
  "Jetzt abrufen" button (header, next to the settings/theme icons — not
  buried in the filter form) that fetches every enabled source's current
  month. Sources and price entries are deliberately **not** managed here
  — see `_settings_modal.html` — so this page stays focused on "what got
  fetched", not configuration (a user-feedback-driven split — apply the
  same split to any new page). The `#fetch-result` line under the filter
  panel (`updateLastFetchDisplay()`) shows the most recent `last_fetch_at`
  across *all* sources, not just a one-off "N Quelle(n) erfolgreich
  abgerufen" toast from the last button click — a persistent freshness
  indicator (updated on page load and after "Jetzt abrufen" via a fresh
  `GET /api/sources`, since the pre-fetch source list used to pick which
  sources to hit is stale by the time the fetches finish) that also
  surfaces any source whose last scheduled/manual fetch failed.
- `app/templates/_settings_modal.html` — a Jinja partial (`{% include %}`,
  **not** a route — there is no `/settings` page; an earlier version had
  one, replaced after explicit user feedback to match a gear-icon-opens-
  a-popup pattern from this author's other projects), included by both
  `index.html` and `report_review.html` right before each page's own
  `<script>` (load-order matters: the partial's `<script>` defines the
  shared `api()` helper and `loadSources()`/`loadPrices()`/
  `loadReportSettings()` that the host page's own script calls, so it must
  come first in document order). Opened via a gear button
  (`[data-open-settings]`, `&#9881;` glyph) in each page's header; a
  sun/moon button (`[data-theme-toggle]`, `id="theme-toggle"`) next to it
  is an explicit light/dark override on top of the CSS
  `prefers-color-scheme` default, persisted in `localStorage` (each page
  also has a tiny inline script at the top of `<body>` that applies a
  stored theme before first paint, to avoid a flash). Both icon buttons use
  the exact same plain `currentColor` SVG/glyph markup as this author's
  other projects (openwb-logger, knxpilot) — `updateThemeIcon()` sets
  `#theme-toggle`'s `innerHTML` to inline `SUN_ICON`/`MOON_ICON` SVG
  constants, not a color emoji (🌙/☀️ render as an inconsistently-shaped
  colored pill depending on the OS's emoji font, which is why an earlier
  version looked visually "off" next to the rest of the flat toolbar in a
  user screenshot). No button anywhere in this app (including
  `index.html`'s "Jetzt abrufen"/"Bericht erstellen" and
  `report_review.html`'s "Bericht erzeugen") uses a filled/accent
  `.primary` style any more — every button is the same flat
  `background: var(--panel)` outline, matching openwb-logger's header
  exactly (it has no filled buttons at all); this was a deliberate
  unification after the user asked twice to match that project's look.
  Header `padding`/`h1` font-size, and every button/input's padding, were
  also pulled to match openwb-logger's exact pixel values (`10px 16px`
  header padding, `17px` h1 with `letter-spacing: -0.01em`, `6px 8px`
  control padding) for the same reason — check openwb-logger's own
  `index.html` `<style>` before changing these again, don't just pick new
  numbers. Panel order is Quellen, Preise, Fahrzeuge, Verlauf abrufen,
  Berichts-Einstellungen (Fahrzeuge added between Preise and Verlauf
  abrufen since both Preise and Fahrzeuge key off vehicle names — don't
  reorder without reason). Source/price entry add-forms are collapsed
  behind a "+" icon button per panel, toggled via `el.hidden = !el.hidden`
  — **the modal's own `<style>` includes `[hidden] { display: none
  !important; }`**, needed because `.inline { display: flex }` (the
  add-forms carry that class) otherwise wins the specificity fight against
  the browser's default `[hidden]` rule and the form stays visible
  regardless of the `hidden` attribute; this was a real shipped bug,
  caught from a screenshot showing the form always open. The Quellen panel
  also has the "Automatischer Abruf aktiv" checkbox + a `<input
  type="time">` (`loadAppSettings()`, `GET/PUT /api/app-settings`) right
  where the old static explanatory text about the background scheduler
  used to sit — both save instantly on `change` (no separate "Speichern"
  button; a native time input's `change` event only fires once a value is
  committed, not per keystroke, so this doesn't spam the API). Price
  entries have a `notes` field here (form + table column) — an unlabeled
  provider+date-range row is meaningless months later. The "Fahrzeuge"
  panel (`loadVehicles()`, `GET /api/vehicles`, `PUT
  /api/vehicles/{name}`) lists every vehicle name ever seen with an
  editable Kennzeichen input and a per-row "Speichern" button — a small
  enough list (one row per vehicle, not per session) that per-row save
  beats trying to track which rows changed for one bulk save. "Berichts-
  Einstellungen" (`GET/PUT /api/report-settings`) is the **only** place
  PDF columns are chosen — `report_review.html` used to have its own
  second column checklist too, which was confusing (two places to set
  the same thing) and is gone; see `report_settings.py`.
- `app/templates/report_review.html` — session/price-override selection UI
  (`/report-review`): filters (source/vehicle/chargepoint/date, same
  dropdown-not-free-text pattern as `index.html`) load sessions via
  `/api/sessions`; recomputes totals client-side as the selection changes
  (mirroring `report_build.py`'s summing logic in JS, since this is just
  an interactive preview — the server-side build via
  `/api/reports/preview`/`/api/reports` is the actual source of truth for
  what a generated report contains); lists/links previously generated
  reports. Sends no `columns` in its request bodies at all (see
  `_settings_modal.html` above for why) — `web.py` falls back to
  `report_settings`'s `default_columns` whenever `columns` is omitted.
  Keep new UI copy in German too.

Header navigation is consistent across pages: a secondary "back" link on
the left where relevant (`← Übersicht`; `index.html` has none, it *is*
"back"), the gear/theme icon pair on the right, and (`index.html` only)
"Jetzt abrufen" plus "Bericht erstellen →" — both plain flat buttons like
everything else, no accent-filled "primary" style (see
`_settings_modal.html` above); `report_review.html`'s own in-page "Bericht
erzeugen" button is styled the same way.
- An MCP endpoint — deliberately deferred past v1, see `ROADMAP.md`.

Storage is Postgres only. Reports, once generated, are immutable — the
rendered PDF bytes and a frozen JSONB snapshot of every included session
and price entry are stored in `reports`/`report_sessions`, so a report
stays defensible even if the underlying `sessions`/`price_entries` are
edited or refetched afterward.

## Commands

```bash
# tests (pure logic only, no DB/network required)
pytest

# local dev: DB via docker, app via uvicorn with reload
docker compose up -d postgres
export DATABASE_URL=postgresql://openwb_ladeprotokoll:openwb_ladeprotokoll@localhost:5432/openwb_ladeprotokoll
uvicorn app.main:app --reload --port 8080

# full stack
docker compose up -d --build
```

## Conventions

- No ORM: plain parameterized SQL via asyncpg everywhere.
- Pure modules (no DB/HTTP) are unit tested directly. Anything touching
  Postgres has no automated test suite entry, but *is* verifiable without
  Docker — see DEVELOPMENT.md's "Testing against a real Postgres" for a
  disposable, no-root embedded server that the full HTTP route surface has
  actually been run against, including the report generation flow end to
  end. An openWB instance itself still can't be simulated that way; that
  part stays manual against a real (or `docker compose up`) target.
- German for all user-facing UI text and PDF content; English for code,
  comments, commit messages, and this file.
- Comments explain *why*, not *what* — see the existing modules for the
  expected density and tone.
