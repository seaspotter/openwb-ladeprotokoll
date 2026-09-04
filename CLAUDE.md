# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A standalone tool that polls one or more openWB installations' charge-log
data (`data/charge_log/<yyyymm>.json`, served anonymously over plain HTTP,
no core changes needed) into Postgres, and turns it into audit-safe PDF
"Dienstwagenabrechnung" (company-car tax) reports mirroring openWB's own
Ladeprotokoll UI table. Named after that page so it's discoverable to
openWB users searching for it. Built as a sibling project rather than a PR
into openWB core because core already sells a paid version of this same
report. Sibling project: `../openwb-logger` (same author, same
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
  `sessions`, `price_entries`, `reports`, `report_sessions` already lives
  here — see the module for the natural-key and audit-snapshot reasoning
  inline.
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
- `app/scheduler.py` — daily background fetch: refetches the current
  month for every enabled source, once at startup and then every 24h.
  Runs as an `asyncio` task started in `main.py`'s lifespan; reuses
  `fetch_service.fetch_source` (same per-source lock, same upsert), so it
  can't race a concurrent manual fetch-now/backfill on the same source.
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
  each session's resolved price decision -> the `ReportData` structure
  (formatted display cells, deduplicated price-basis block, totals) the
  template renders and that gets frozen into `report_sessions.snapshot`.
  `COLUMN_LABELS` is the single source of truth for the 14 selectable
  columns (also served at `GET /api/report-columns` for the review UI).
  Totals sum `cost_used` (not raw `cost_corrected`) for the "corrected"
  total, so an unpriced session's own openWB cost still counts rather than
  silently dropping out. Unit tested.
- `app/pdf_render.py` — Jinja2 (`templates/report_pdf.html`) + WeasyPrint.
  One template renders both the HTML preview and the actual PDF — `@page`
  rules WeasyPrint honors are simply ignored by a browser. The page is
  **landscape**: portrait's ~17cm printable width cuts off the last
  columns once several are selected (verified visually, not just assumed
  — see DEVELOPMENT.md). The footer (disclaimer + signature line) has
  `page-break-inside: avoid` — without it, WeasyPrint can push just the
  signature line onto its own near-blank trailing page.
- `app/web.py` — FastAPI routes for source CRUD, fetch triggers, price
  entry CRUD, session listing (enriched with each session's matched price
  decision), and report preview/generate/list/pdf/delete. Plain
  parameterized SQL via asyncpg, no ORM. asyncpg returns `NUMERIC` columns
  as `Decimal`; anything feeding `price_entries.py`/`report_build.py`
  converts to `float` first (`_to_float`), since those modules are written
  and tested against plain floats. A generated report is built in two DB
  steps: insert the `reports` row first (to get a real id), *then* render
  the PDF (its own header/footer displays that id) and `UPDATE` the row
  with the bytes — one transaction, so a failure partway leaves nothing
  behind.
- `app/updater.py` — optional in-app self-update (`git pull` + process
  restart), identical pattern to `openwb-logger/app/updater.py`. Works
  because `docker-compose.yml` bind-mounts the repo onto the container's
  `WORKDIR`.
- `app/main.py` — app factory, lifespan (DB pool, starts/cancels the
  scheduler task).
- `app/templates/index.html` — sources + prices dashboard, **in German**:
  vanilla JS, no build step.
- `app/templates/report_review.html` — session/column/price-override
  selection UI (`/report-review`): loads sessions via `/api/sessions`,
  recomputes totals client-side as the selection changes (mirroring
  `report_build.py`'s summing logic in JS, since this is just an
  interactive preview — the server-side build via
  `/api/reports/preview`/`/api/reports` is the actual source of truth for
  what a generated report contains), and lists/links previously generated
  reports. Keep new UI copy in German too.
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
