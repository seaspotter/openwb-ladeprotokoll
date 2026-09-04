# Development

## Branching

- `main` — stable, releasable. Nothing lands here directly.
- `dev` — active development. Day-to-day work and commits happen here.

When `dev` is in good shape, merge it into `main` (PR or fast-forward
merge) and tag a release there — see `CHANGELOG.md` for what's shipped
since the last one. `main` is what `DEPLOYMENT.md`'s `git clone` /
`git pull` instructions assume.

## Versioning and releasing

[Semantic versioning](https://semver.org/): tags on `main` are
`vMAJOR.MINOR.PATCH`. Self-contained Docker app, no public API/library
surface, so:

- **PATCH** — bug fixes, no behavior/schema shape changed.
- **MINOR** — new features, new columns/settings, anything additive.
- **MAJOR** — anything that isn't a drop-in upgrade: a schema change
  without an automatic migration path, a removed/renamed setting, a
  required manual step.

Staying on `0.x.y` for now (starting at `0.1.0`) — nothing here is a
stable, load-bearing interface yet.

To cut a release:

1. On `dev`, rename `CHANGELOG.md`'s `## [Unreleased]` section to
   `## [X.Y.Z] - YYYY-MM-DD` and start a fresh empty `[Unreleased]` above
   it.
2. `git checkout main && git merge --ff-only dev` — fast-forward, not
   `--no-ff` (see `openwb-logger/DEVELOPMENT.md` for why this matters for
   self-update's `git describe`).
3. `git tag vX.Y.Z && git push origin main --tags`.

That last push triggers `.github/workflows/docker-publish.yml` to build
and publish the multi-arch image — see `DEPLOYMENT.md`.

## Setup

Requires Python 3.12+ and a local Postgres (easiest via Docker).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# start just the database
docker compose up -d postgres

export DATABASE_URL=postgresql://openwb_ladeprotokoll:openwb_ladeprotokoll@localhost:5432/openwb_ladeprotokoll

uvicorn app.main:app --reload --port 8080
```

Then open http://localhost:8080 and add a source (name + your openWB's
address) from the dashboard — there's no env var for it, sources are user
data in Postgres (see `app/sources.py`, `app/db.py`).

## Tests

```bash
pytest
```

Everything under `tests/` exercises pure logic only (`chargelog_parse.py`,
`sources.py`, `price_entries.py`, `report_build.py`) — no database or
network required, deliberately, so the suite stays fast. HTTP fetching,
DB upserts, and PDF rendering are integration-level concerns without an
automated suite entry, but see the next section for how to actually
exercise them against a real database without `docker compose up`.

## Testing against a real Postgres

`pip install pgserver` gets you a disposable, no-root Postgres (a real
`postgres` binary the package ships, not an emulation) usable from a
throwaway script — no Docker, no system package, no sudo:

```python
import pgserver, tempfile
srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="delete")
uri = srv.get_uri()  # postgresql://postgres:@/postgres?host=/tmp/...
```

Set `DATABASE_URL` to that URI **before** importing anything under `app/`
(`app/config.py` reads it once at import time), then drive the app
through `fastapi.testclient.TestClient` used as a context manager
(`with TestClient(app) as client:`) so the real lifespan runs — real
`init_pool()`, real schema bootstrap, real routes, real WeasyPrint
rendering. This is exactly how the report generation flow (source create
-> price entry -> `/api/sessions` price matching -> preview -> generate ->
PDF bytes -> list/delete) was verified end to end while building it,
including confirming the returned PDF bytes actually start with `%PDF`.

One gotcha: if you also want to seed rows directly (bypassing the HTTP
API — e.g. faking a `sessions` row without a live openWB to fetch from),
open a **separate** `asyncpg.connect(uri)` for that in its own
`asyncio.run()` call rather than reaching into the app's own pool —
that pool lives on `TestClient`'s event loop, and a separately-run
`asyncio.run()` uses a different one; asyncpg connections can't cross
loops. A raw connection like that also doesn't have the app's custom
JSONB codec (`app/db.py`'s `_init_connection`) registered, so pass
`json.dumps(...)` yourself for any JSONB column value.

## Project layout

| Path | Purpose |
|---|---|
| `app/config.py` | Infra-level config (DB URL) — env vars, fixed per process |
| `app/db.py` | asyncpg pool, schema bootstrap (`CREATE TABLE IF NOT EXISTS`) |
| `app/sources.py` | Pure: `Source` dataclass, `base_url` validation/normalization |
| `app/chargelog_parse.py` | Pure: one raw charge-log JSON record -> normalized `sessions` row + natural key |
| `app/openwb_client.py` | httpx GET of one source's `data/charge_log/<yyyymm>.json` |
| `app/fetch_service.py` | Orchestrates fetch -> parse -> upsert; per-source lock so manual/daily/backfill triggers can't race |
| `app/scheduler.py` | Daily background fetch (all enabled sources, current month), started as an `asyncio` task in `main.py`'s lifespan |
| `app/price_entries.py` | Pure: price-entry match/precedence + corrected-cost math |
| `app/report_build.py` | Pure: sessions + columns + price decisions -> formatted rows/totals for the template |
| `app/pdf_render.py` | Jinja2 (`templates/report_pdf.html`) + WeasyPrint, HTML preview or PDF bytes from the same template |
| `app/web.py` | FastAPI routes (all reads/writes are plain parameterized SQL) |
| `app/updater.py` | Optional in-app self-update (`git pull` + process restart) |
| `app/templates/index.html` | Sources + prices dashboard (German UI) — vanilla JS, no build step |
| `app/templates/report_review.html` | Session/column/price-override selection UI, at `/report-review` |
| `app/templates/report_pdf.html` | The actual report layout — rendered as both the HTML preview and the PDF |

## Data-format notes

`app/chargelog_parse.py`'s docstring is the source of truth for what's
confirmed about the raw JSON shape. Field mapping was cross-checked twice
against real data from the same openWB installation (2026-09-03): first
against a CSV export of the Ladeprotokoll UI, then against an actual
`chargelog-*.json` file — the whole sample file (35 records) parses
cleanly with no duplicate natural keys and no anomalous implied €/kWh
price, a useful smoke test to rerun (`parse_record` + `natural_key` over
every record in a file) if a new sample ever surfaces.

Four corrections came out of that, all load-bearing:

- The UI's plain "Energie" column (sum this for a report total) is
  `data.imported_since_mode_switch` — a *per-row* figure — not the
  cumulative `imported_since_plugged`. `report_build.py` sums `energy_kwh`,
  never `energy_since_plugged_kwh` — keep that if you touch its totals
  logic.
- `time.time_charged` is "H:MM", not "H:MM:SS".
- `time.begin`/`time.end` are `"MM/DD/YYYY, HH:MM:SS"` strings (confirmed
  from a real `.json` file) — not epoch numbers, which was the working
  assumption before that file was available.
- Energy figures (`imported_since_*`, chargepoint meter readings) are in
  **Wh**; `power_source.{grid,cp,bat,pv}` are **fractions (0.0-1.0)**.
  `chargelog_parse.py` converts both on the way in — the `sessions`
  columns (`_kwh`, `_pct`) are already in the converted unit.

Still unconfirmed: an actual nonzero V2H/V2G discharge value —
`data.exported_since_mode_switch` exists in every real record seen but has
only ever been 0 (no sample vehicle uses V2H). If a record with a nonzero
value ever turns up, check it against `parse_record`'s
`energy_discharged_kwh` handling.

## Code style

- Line length is 100 columns (`setup.cfg` / `pyproject.toml`).
- `sources.py`, `chargelog_parse.py`, `price_entries.py`, `report_build.py`
  must stay free of I/O (no httpx, no asyncpg) — that's what makes them
  cheap to unit test. Orchestration (HTTP calls, DB writes, WeasyPrint
  rendering) belongs in `fetch_service.py` / `web.py` / `pdf_render.py`.
- SQL is always parameterized (`$1`, `$2`, ...) — never interpolate
  request input into a query string.
- asyncpg returns `NUMERIC` columns as `decimal.Decimal`, not `float`.
  `price_entries.py`/`report_build.py`'s functions are written and tested
  against plain floats (`Decimal`/`float` don't compare or arithmetic
  cleanly together — see Python's own `decimal` docs). `web.py`'s
  `_to_float` helper converts DB rows before they reach those modules —
  follow that pattern for any new caller.
