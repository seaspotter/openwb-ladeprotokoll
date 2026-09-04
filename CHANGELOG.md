# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Versions follow [semver](https://semver.org/); see `DEVELOPMENT.md` for
what that means in practice for this project.

## [Unreleased]

### Added
- MCP server at `/mcp` (`app/mcp_server.py`, `FastMCP`, Streamable HTTP
  transport, same pattern as the sibling `openwb-logger` project):
  `search_sessions` (source/vehicle/chargepoint/date filters, same price-
  decision enrichment as `/api/sessions`) and `generate_report` (session
  ids -> a real, immutable, persisted PDF report) tools, plus
  `openwb://sources`/`openwb://report-columns` resources for discovering
  valid parameter values. No new authentication -- same no-auth, LAN-trust
  model as the web UI.
- Monthly/yearly statistics at `/statistik` (`app/statistics.py`): total
  energy and cost per period, plus the grid/PV/battery/chargepoint split
  as absolute kWh (not an averaged percentage, which would misrepresent
  the mix once session sizes vary a lot), a PV-self-consumption KPI, and a
  per-vehicle breakdown table for comparing vehicles against each other
  rather than only against time. Two Chart.js bar charts (vendored locally
  as `app/static/chart.umd.min.js`, not CDN-loaded -- this app otherwise
  has zero external network dependencies and should keep working on a
  fully offline LAN).
- The app's own page headers (`index.html`/`report_review.html`/
  `statistik.html`) now show the lightning-bolt brand icon next to
  "openWB Ladeprotokoll", matching the favicon and the PDF header -- it
  was missing from the actual web UI this whole time.
- Report generation gets a "Kostenbasis" choice (openWB-Wert/Korrigiert)
  right next to the title field in "Bericht erstellen" -- a conscious,
  per-report override of the existing Berichts-Einstellungen default, not
  a change to what that default means. "Bisherige Berichte" shows which
  basis each report actually used; the PDF itself deliberately does not
  (a "Kostenbasis" meta line was tried and removed per user feedback --
  it's a review-time detail, not something the document needs to state).
- The Übersicht and Bericht-erstellen session tables' cost columns
  renamed: "Kosten (openWB)" -> "Kosten (real)", "Kosten (verwendet)" ->
  "Kosten (korrigiert)" -- clearer than "verwendet" for what the second
  column actually shows (the price-corrected/used cost), matching the
  first column's plain "real"-cost framing. Display-only; the underlying
  `cost_openwb`/`cost_used` field names are unchanged.
- `/statistik`'s "Kosten" stat card, chart heading, and "Nach Fahrzeug"
  column now all say which cost basis they're summing (e.g. "Kosten
  (Korrigiert)") -- previously the page never said whether it was showing
  openWB's own cost or the corrected one. "Nach Fahrzeug"'s single
  combined "PV-Anteil" column split into separate Netz/PV/Speicher
  percentage columns, so the grid/PV/battery mix is visible per vehicle,
  not just self-consumption as one number.

### Changed
- Dropped the standalone CSV-export roadmap item -- openWB's own UI
  already offers a CSV export directly, no need to duplicate it here.
- `web.py`'s session-query and report-generation logic extracted into
  `_query_sessions`/`_generate_report` module functions, shared by the
  HTTP routes and the new MCP tools rather than duplicated.
- `_query_sessions` now converts `energy_kwh`/`cost_openwb`/every
  `power_source_*_pct` field to plain `float` before returning, not just
  the price-matching-derived fields -- needed once `statistics.py` started
  doing real arithmetic on them (a bare `Decimal`, which is what asyncpg
  returns for `NUMERIC` columns, doesn't arithmetic against a `float`).

## [0.1.0] - 2026-09-04

First release. Everything below shipped before this project had a
version number, so it's all bundled into this one entry rather than
retroactively split across nonexistent prior releases.

### Added
- Automatic daily fetch is now configurable instead of a hardcoded fixed
  interval: a new "Automatischer Abruf aktiv" checkbox + time picker in
  Einstellungen -> Quellen (`app_settings` table, `GET/PUT
  /api/app-settings`) lets it be turned off entirely, or scheduled at any
  wall-clock time (default `00:05`, shortly after midnight) instead of
  always running 24h after whenever the process last started.
- The overview page (`/`) now shows "Letzter Abruf: ..." — the most
  recent successful fetch across all sources — instead of a one-off
  "N Quelle(n) erfolgreich abgerufen" message that only appeared right
  after clicking "Jetzt abrufen" and said nothing once the page had been
  open a while.
- Vehicle Kennzeichen (license plate) documentation: a new "Fahrzeuge"
  settings panel lists every vehicle name ever seen with an editable
  Kennzeichen field (`vehicles` table, `GET /api/vehicles`, `PUT
  /api/vehicles/{name}`) — openWB itself has no such field, this is purely
  user-entered. A vehicle with a Kennzeichen set has it appended to the
  PDF's "Fahrzeug(e)" line (e.g. "VW ID3 (AB-CD 123)").
- The downloaded PDF's filename is now `"<YYYYMMDD> Ladeprotokoll
  <title>.pdf"` (date-prefixed so files sort chronologically) instead of
  the old `"ladeprotokoll-<id>.pdf"`.

### Changed
- PDF: the "Kosten" cell no longer gets the red highlight for a session
  whose corrected cost diverges from openWB's own value — that stays on
  the overview/review pages (still useful there for deciding what to
  include), but doesn't belong on the final immutable document. Header
  logo-to-title gap widened again, `22px` -> `36px` — still looked too
  close in a follow-up screenshot even after confirming the PDF really was
  using the already-widened template.

### Fixed
- Settings modal couldn't be closed: the double-scrollbar fix below added
  an unqualified `dialog#settings-modal { display: flex }` rule, which
  (ID selector) outranks the browser's own `dialog:not([open]) { display:
  none }` UA rule on specificity — so clicking "×" still called
  `.close()` correctly, but the panel stayed visibly stuck on the page
  instead of disappearing. Scoped the rule to `dialog#settings-modal[open]`
  so it only applies while actually open.
- Settings modal showed two nested scrollbars once its content overflowed
  (`dialog#settings-modal` had a `max-height` but no `overflow: hidden`,
  and `.modal-body`'s own scroll area was a hardcoded `calc(88vh - 56px)`
  guess at the header's height, which could fall short and leave both the
  dialog and the body scrollable at once). Restructured as a flex column
  (header `flex-shrink: 0`, body `flex: 1; min-height: 0`) so only
  `.modal-body` ever scrolls, regardless of the header's actual height.

### Changed
- Third real-usage feedback round (2026-09-04, same day, after a PDF
  header screenshot and a side-by-side comparison with openwb-logger):
  - PDF disclaimer trimmed to one sentence — cut the redundant "changes to
    the source data afterward don't affect this document" follow-up, which
    just restated what "the document is immutable" already implies.
  - More visual space between the PDF header's logo and "Ladeprotokoll"
    title (`gap: 12px` -> `22px` on `header.doc-header`).
  - Every button across `index.html`/`report_review.html`/
    `_settings_modal.html` unified to the same flat, unfilled style — the
    accent-colored `.primary` variant (used on "Jetzt abrufen", "Bericht
    erstellen", "Bericht erzeugen", the report-settings "Speichern") is
    gone; openwb-logger's header has no filled buttons at all, and this
    project's own icon buttons (⚙️/🌙) were also color emoji next to
    otherwise-flat controls, which read as visually inconsistent in a
    side-by-side comparison. Header padding, `h1` font-size/letter-
    spacing, and button/input padding now match openwb-logger's exact
    pixel values.
  - Settings/theme header icons switched from color emoji (⚙️/🌙/☀️, which
    render as an inconsistently-shaped colored pill depending on the OS's
    emoji font) to the same plain `currentColor` SVG/glyph markup as
    openwb-logger and knxpilot (`&#9881;` gear entity, inline sun/moon
    SVGs) — this incidentally fixed a latent bug where the theme icon
    never actually updated on toggle, because the button was missing the
    `id="theme-toggle"` the shared script looked up by.
- Second real-usage feedback round (2026-09-04, same day, after reviewing
  an actual generated PDF and dashboard screenshots):
  - Einstellungen is now a `<dialog>` popup (new `app/templates/
    _settings_modal.html`, a Jinja partial with no route of its own,
    included by both `/` and `/report-review`) opened via a `⚙️` button in
    the header, replacing the standalone `/settings` page from the first
    feedback round -- matches this author's other projects' pattern.
  - Added an explicit 🌙/☀️ theme toggle button, `localStorage`-persisted,
    layered on top of the existing `prefers-color-scheme` default.
  - "Jetzt abrufen" moved into the header on `/`, next to the theme/
    settings buttons, so the page's own filter panel is just filters.
  - Removed `/report-review`'s own PDF-column checklist -- Berichts-
    Einstellungen is now the *only* place columns are chosen. The
    duplication was the likely cause of an earlier "the report settings
    aren't remembered" report: a per-request override there could easily
    look like a forgotten setting.
  - Settings panel order changed to Quellen, Preise, Verlauf abrufen (was
    Quellen, Verlauf abrufen, Preise).
  - New `orientation` setting (portrait/landscape, `report_settings.py`,
    additive `report_settings.orientation` column) -- resolves the
    portrait-vs-landscape back-and-forth from the first feedback round
    with an actual choice instead of a hardcoded default.
  - Fixed a real bug: the source/price "+"-toggled add-forms never
    actually stayed hidden, because `.inline { display: flex }` (a class
    on those forms) beat the browser's own `[hidden]` rule on CSS
    specificity. Fixed with an explicit `[hidden] { display: none
    !important; }` rule.
- First real-usage feedback round (2026-09-04, after testing against a
  real openWB and a real Proxmox deployment):
  - Removed "Dienstwagenabrechnung" everywhere (code, docs, the PDF
    itself) per explicit request — the tool is now framed generically as
    a charging-cost report, not tied to German company-car tax reporting.
  - The PDF's `@page` size flipped back to **portrait** (was landscape).
    With the cost column collapsed to one (see below) and a lean default
    column selection, portrait fits — but selecting most/all columns at
    once can still overflow it, same tradeoff as before landscape was
    tried.
  - The PDF no longer shows its own `report_id` ("Bericht 3" was
    meaningless to a reader) — the user-given title is shown instead; the
    id still drives the file's URL/filename behind the scenes.
  - The PDF's two cost columns/totals ("Kosten (openWB)" and "Kosten
    (korrigiert)") collapsed into a single "Kosten", driven by a new
    `cost_basis` setting (openWB's own value, or the corrected one with
    its existing per-row fallback) — new `app/report_settings.py` and a
    "Berichts-Einstellungen" panel in `/settings`, alongside a
    `default_columns` setting (was: always all columns) and a
    `show_signature_line` toggle (was: always shown; now off by default).
  - PDF rows now sort chronologically ascending (oldest first, latest at
    the bottom, like a ledger) regardless of selection order; the totals'
    "Energie" row is now labelled "Geladene Energie", and "Entladene
    Energie" is omitted entirely when it's zero (true for every session
    seen so far, no V2H/V2G vehicle in the sample data).
  - Vehicle and chargepoint became filterable dropdowns (populated from
    real data, optionally scoped to the selected source) instead of free
    text, on both `/` and `/report-review`; `/report-review` gained a
    chargepoint filter it didn't have before.
  - Price entries gained a `notes` field (already existed in the schema
    and API, never exposed in the UI) — now a form field and a table
    column in `/settings`, since an unlabeled provider+date-range row is
    meaningless months later.
  - Source and price entry "add" forms collapsed behind a "+" icon next
    to their panel headings instead of always being visible.
  - Header navigation across all three pages (`/`, `/settings`,
    `/report-review`) now uses consistent button-styled links instead of
    plain text, with the primary forward action right-aligned.
- Split the single sources+prices dashboard into two pages: `/` is now a
  read-only charge-log overview (filter by source/vehicle/date, a "Jetzt
  abrufen" button that fetches every enabled source's current month) with
  no configuration on it; source and price entry management moved to a
  new `/settings` page.
- Surfaced the backfill endpoint (`POST /api/sources/{id}/backfill`,
  which already existed but had no UI) in `/settings` as "Verlauf
  abrufen": pick a source and a from/to month to pull in history older
  than the current month, which neither the daily scheduler nor "Jetzt
  abrufen" ever touch.

### Fixed
- CI's Docker image build failed outright (`docker-publish.yml`, caught on
  the first push to GitHub): `Dockerfile` installed `libcairo2` and
  `libgdk-pixbuf2.0-0` for WeasyPrint per older install guides, but
  WeasyPrint 53+ (we're on 63.1) dropped that dependency entirely -- PDF
  output goes through its own `pydyf` backend now, images through Pillow,
  both plain pip packages already in `requirements.txt`. Debian trixie
  (the current `python:3.12-slim` base) renamed/dropped
  `libgdk-pixbuf2.0-0` with no direct replacement in its default repos,
  which is what actually broke the build; the real fix is removing both
  now-unnecessary packages (confirmed via WeasyPrint's own FFI bindings
  module, which only references `pango`/`pangoft2`/`fontconfig`/
  `harfbuzz`), not chasing the renamed package.
- `chargelog_parse.py` had the openWB UI's "Energie" and "Energie seit
  Anstecken" columns swapped (`imported_since_mode_switch` is the per-row
  figure to sum for a report total; `imported_since_plugged` is
  cumulative since plug-in and would have double-counted energy across a
  multi-segment charging session), and parsed `time.time_charged`
  ("Dauer") as "H:MM:SS" when the real format is "H:MM" — both caught by
  cross-checking against a real CSV export of the Ladeprotokoll UI.
  `sessions.power_source_grid/cp/bat/pv_kwh` renamed to `..._pct`: these
  are percentage shares (0-100), not kWh amounts.
- A follow-up cross-check against an actual `chargelog-*.json` file (as
  opposed to its CSV export, which already has these converted) found two
  more: `time.begin`/`time.end` are `"MM/DD/YYYY, HH:MM:SS"` strings, not
  epoch numbers as previously assumed; and every energy figure
  (`imported_since_*`, the chargepoint meter readings) is in Wh rather
  than kWh, and `power_source.{grid,cp,bat,pv}` are fractions (0.0-1.0)
  rather than already being 0-100 percentages. `chargelog_parse.py` now
  converts both on the way in.

### Added
- Report generation: `app/report_build.py` (pure -- sessions + selected
  columns + price decisions -> formatted rows/totals/price-basis block)
  and `app/pdf_render.py` (one Jinja2 template rendered as either an HTML
  preview or, via WeasyPrint, the final PDF). New routes:
  `POST /api/reports/preview` (nothing
  persisted), `POST /api/reports` (inserts an immutable `reports` row plus
  one frozen `report_sessions` snapshot per included session, stores the
  rendered PDF bytes), `GET /reports`, `GET /reports/{id}`,
  `GET /reports/{id}/pdf`, `DELETE /reports/{id}`. New review UI at
  `/report-review`: filter sessions, toggle PDF columns, override the
  auto-matched price per row, live client-side totals, preview, generate,
  browse past reports. Verified end to end against a real (embedded,
  disposable, no-root) Postgres, not just unit tests -- see
  `DEVELOPMENT.md`.
- Electricity price correction: `price_entries` CRUD routes, a "Preise"
  panel in the dashboard, and pure match/precedence + corrected-cost logic
  (`app/price_entries.py`) — an entry is scoped per source and/or vehicle
  (both nullable as wildcards), ranked by specificity when several match,
  and priced against `energy_kwh` (never the cumulative
  `energy_since_plugged_kwh`). `/api/sessions` now includes each session's
  matched price decision (provider, corrected cost, delta, and whether the
  delta exceeds the 0.01 flag threshold).
- Daily background fetch scheduler: refetches every enabled source's
  current month once at startup and then every 24h, reusing
  `fetch_service`'s per-source lock so it can't race a manual fetch-now or
  backfill (`app/scheduler.py`, started as an `asyncio` task in
  `app/main.py`'s lifespan).
- Initial project scaffolding: Docker + Postgres setup, schema bootstrap
  for `sources`, `sessions`, `price_entries`, `reports`, `report_sessions`
  (`app/db.py`).
- Source configuration with `base_url` validation/normalization
  (`app/sources.py`).
- Charge-log JSON parsing into normalized session rows, with a natural
  key of `(source_id, chargepoint_serial_number, time_begin)`
  (`app/chargelog_parse.py`).
- openWB HTTP client for `data/charge_log/<yyyymm>.json`
  (`app/openwb_client.py`).
- Fetch orchestration with idempotent upsert and a per-source lock, so
  manual, scheduled, and backfill fetches can't race
  (`app/fetch_service.py`).
- Sources dashboard web UI (add/list/delete sources, manual "Jetzt
  abrufen" trigger) and optional in-app self-update, mirroring
  `openwb-logger`'s pattern.
