# Roadmap

Loose notes on where this is headed, not a commitment. Reorder freely —
open an issue or just start working if something here matters to you.

## Done (v0.1.0, released 2026-09-04)

- [x] Source config + `base_url` validation/normalization (`app/sources.py`)
- [x] Charge-log JSON -> normalized `sessions` row parsing (`app/chargelog_parse.py`)
- [x] openWB HTTP client (`app/openwb_client.py`)
- [x] Fetch orchestration + idempotent upsert, manual/backfill triggers (`app/fetch_service.py`)
- [x] Sources dashboard web UI, self-update
- [x] Cross-check `chargelog_parse.py`'s field mapping against real data —
      a CSV export of the Ladeprotokoll UI, then an actual
      `chargelog-*.json` file (35 records, all parse cleanly). Fixed four
      bugs: Energie vs. Energie seit Anstecken swapped; Dauer parsed as
      H:MM:SS instead of H:MM; time.begin/end assumed epoch instead of
      "MM/DD/YYYY, HH:MM:SS" strings; energy figures assumed kWh instead
      of Wh and power_source assumed already-percentage instead of a
      0.0-1.0 fraction. Still open: an actual nonzero V2H/V2G discharge
      value has never been observed — see `DEVELOPMENT.md`.
- [x] Daily background fetch scheduler (`app/scheduler.py`): refetches
      every enabled source's current month once at startup and then every
      24h, as an `asyncio` task in `main.py`'s lifespan.
- [x] CI: `.github/workflows/docker-publish.yml` (multi-arch image on GHCR)
- [x] Electricity price correction: entries, match/precedence (source+
      vehicle > source-only > vehicle-only > wildcard), corrected-cost math
      and delta flagging (`app/price_entries.py`), price CRUD routes, and a
      "Preise" panel in the dashboard.
- [x] Report review UI (`/report-review`, `app/templates/report_review.html`):
      filter/select sessions, toggle PDF columns, per-row price override
      ("Automatisch" / "openWB-Wert verwenden" / a specific price entry),
      live client-side totals, preview, generate, and a list of previously
      generated reports.
- [x] Report build + WeasyPrint PDF rendering, immutable stored reports
      (`app/report_build.py`, `app/pdf_render.py`, `templates/report_pdf.html`).
      Report id assigned before PDF render (needed for the filename/URL,
      no longer shown in the document itself — see below), one DB
      transaction covering the `reports` row, its `pdf_data` update, and
      every `report_sessions` snapshot.
- [x] Verified end to end against a real (embedded, no-root) Postgres —
      not just unit tests: source create, session listing with price
      matching, price entry CRUD, report preview/generate/list/pdf/delete,
      price overrides, and error handling (unknown column, missing
      session) all actually exercised through the real HTTP routes. See
      DEVELOPMENT.md's "Testing against a real Postgres".
- [x] Pushed to GitHub, CI green (github.com/seaspotter/openwb-ladeprotokoll)
      — first CI run failed on a WeasyPrint apt dependency that's no
      longer needed since WeasyPrint 53+ (`libcairo2`/`libgdk-pixbuf2.0-0`
      removed from `Dockerfile`), fixed same day.
- [x] Exercised against a real, running openWB and a real Proxmox LXC
      `docker compose up` deployment (2026-09-04) — both work. One
      deployment issue hit along the way was environmental, not this
      project's: an IP address conflict with an unrelated macvlan Docker
      container elsewhere on the user's LAN, not a bug here.
- [x] First real-usage feedback round, all shipped: dashboard split into
      a read-only overview (`/`) and a source/price/backfill/Berichts-
      Einstellungen area (initially its own `/settings` page — see the
      *second* feedback round below, which turned this into a modal
      instead); source/price entry add-forms collapsed behind a "+" icon;
      price entries gained a `notes` field, now shown in the UI;
      vehicle/chargepoint filters became dropdowns (index + report-review)
      instead of free text, and report-review gained a chargepoint filter;
      the PDF's two "Kosten" columns collapsed into one, driven by a new
      `cost_basis` setting ("openwb" or "corrected"); default page
      orientation flipped back to **portrait**; "Dienstwagenabrechnung"
      removed everywhere (code, docs, PDF) per explicit request; the PDF
      no longer shows its own report id, only the user-given title; rows
      in the PDF sort chronologically ascending (latest at the bottom);
      "Entladene Energie" is hidden in the totals when zero; the
      signature line is now off by default and toggleable in settings;
      header nav across all three pages uses consistent button styling.
- [x] Second real-usage feedback round (same day, after looking at an
      actual generated PDF with real data and screenshots of the UI):
      Einstellungen became a `<dialog>` popup (`_settings_modal.html`,
      opened via a `⚙️` header button) instead of a separate `/settings`
      page, matching this author's other projects; added an explicit
      🌙/☀️ theme toggle (`localStorage`-persisted, on top of the existing
      `prefers-color-scheme` default); moved "Jetzt abrufen" into the
      header on `/`; removed the second, duplicate PDF-column picker that
      had existed on `/report-review` (Berichts-Einstellungen is now the
      only place columns are chosen — the duplication was the likely
      cause of an earlier "settings aren't remembered" report, since a
      per-request override there could look like a forgotten setting);
      reordered the settings panels to Quellen, Preise, Verlauf abrufen
      (was Quellen, Verlauf abrufen, Preise); added an `orientation`
      setting (portrait/landscape) so the earlier portrait-vs-landscape
      backtracking has a real answer instead of a hardcoded guess; fixed
      a real shipped bug where the source/price "+"-toggled add-forms
      never actually stayed hidden, because `.inline { display: flex }`
      beat the browser's own `[hidden]` rule on specificity.

- [x] Third real-usage feedback round (same day, after a PDF header
      screenshot and a direct "why doesn't this look like openwb-logger"
      comparison): trimmed the PDF disclaimer to one sentence; widened the
      gap between the PDF header's logo and title; added a "Fahrzeuge"
      settings panel + `vehicles` table so a Kennzeichen (license plate)
      can be recorded per vehicle name and shown in the PDF's "Fahrzeug(e)"
      line; PDF downloads now get a date-prefixed filename
      (`"<YYYYMMDD> Ladeprotokoll <title>.pdf"`); unified every button's
      styling with openwb-logger's (flat, no `.primary` filled variant;
      matching header/button padding and font-size) and switched the
      settings/theme header icons from color emoji to the same plain SVG/
      glyph markup openwb-logger and knxpilot use.
- [x] Fixed a real double-scrollbar bug in the settings `<dialog>` (it had
      a `max-height` but no `overflow: hidden`, and `.modal-body`'s own
      scroll area was a hardcoded height guess that could fall short) —
      restructured as a flex column so only `.modal-body` ever scrolls.
- [x] Automatic daily fetch is now configurable (on/off + wall-clock time,
      default `00:05`, `app_settings` table/`app_settings.py`) instead of
      a fixed 24h-from-startup interval; the overview page now shows a
      persistent "Letzter Abruf" freshness indicator instead of a one-off
      post-click success toast.
## Done (since v0.1.0, on `dev` — not yet released)

- [x] MCP server (`app/mcp_server.py`, `FastMCP`, Streamable HTTP
      transport mounted at `/mcp` on the same app/port), mirroring
      `openwb-logger`'s `/mcp`: `search_sessions`/`generate_report` tools
      plus `openwb://sources`/`openwb://report-columns` resources, both
      tools thin wrappers around `web.py`'s own `_query_sessions`/
      `_generate_report` (extracted so the HTTP routes and MCP tools share
      one implementation). Dropped the standalone CSV-export roadmap item
      per explicit user feedback (2026-09-04) — openWB's own UI already
      offers a CSV export directly, no need to duplicate it here.
- [x] Monthly/yearly statistics with a chart (`/statistik`,
      `app/statistics.py`): total energy and cost, plus the grid/PV/
      battery/chargepoint split as absolute kWh per period, not an
      averaged percentage (see `app/statistics.py`'s docstring for why
      that distinction matters), a PV-self-consumption KPI, and a
      per-vehicle breakdown table. Charts via Chart.js, vendored locally
      (`app/static/chart.umd.min.js`) rather than CDN-loaded, since this
      app otherwise has zero external network dependencies anywhere and
      should keep working on a fully offline LAN.
- [x] The app's own page headers gained the lightning-bolt brand icon the
      favicon and PDF header already used — a real gap caught from a user
      screenshot, not previously noticed.
- [x] Grid-only price correction: `price_entries.py` always computes a
      grid-only corrected cost alongside the existing total-energy one
      (priced against only a session's `power_source_grid_pct` share),
      deliberately *not* behind a per-price-entry flag (considered and
      rejected — too easy to forget). `cost_basis` ("openwb"/"corrected"/
      "corrected_grid_only") is choosable per report at generation time,
      not just as a global default — a report's own "Kostenbasis" is shown
      in its PDF meta info and in "Bisherige Berichte", and an optional
      "Netzbezug (kWh)" PDF column documents the underlying figure.
      Closed the "Dynamische Stromtarife" idea instead of building it —
      see below.
- [x] ~~Dynamische Stromtarife~~ — investigated and closed, not building
      this: the charge-log gives exactly one row per session (one
      `time_begin`/`time_end`/`energy_kwh`), no intra-session time-of-use
      breakdown, so there's no way to know how many kWh happened during
      which price-hour from this data at all — only openWB's own
      real-time control loop has that resolution, which is presumably
      already folded into `data.costs`/`cost_openwb`. A dynamic-tariff
      user should use `cost_basis = "openwb"` for that vehicle/source and
      skip this app's flat-€/kWh price-entry correction for it, rather
      than this app trying to approximate hourly pricing it structurally
      cannot see. Concluded with the user 2026-09-04.

## Next

Nothing queued right now — see "Someday / maybe" below.

## Someday / maybe

- [ ] Multi-currency support, if this is ever useful outside Germany/EUR.
