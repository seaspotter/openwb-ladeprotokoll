# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Versions follow [semver](https://semver.org/); see `DEVELOPMENT.md` for
what that means in practice for this project.

## [Unreleased]

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
  preview or, via WeasyPrint, the final PDF -- landscape A4, since
  portrait cuts off the last columns once several of the 14 selectable
  ones are on). New routes: `POST /api/reports/preview` (nothing
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
