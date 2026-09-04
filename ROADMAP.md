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
      that distinction matters). Charts via Chart.js, vendored locally
      (`app/static/chart.umd.min.js`) rather than CDN-loaded, since this
      app otherwise has zero external network dependencies anywhere and
      should keep working on a fully offline LAN.
- [x] Report generation gained a per-report "Kostenbasis" choice
      (openWB-Wert/Korrigiert) next to the title field in "Bericht
      erstellen" — overrides Berichts-Einstellungen's own default for
      that one report; the PDF and "Bisherige Berichte" both show which
      basis a given report actually used. A third grid-only-pricing basis
      was tried alongside this (and separately, as an overview-only
      column) and fully reverted after repeated user feedback the same
      day — `report_build.COST_BASES` stays exactly
      `("openwb", "corrected")`, don't reintroduce a third value without
      being asked again.
- [x] Statistik's corrected cost splits a session by its actual
      grid/PV/battery mix instead of applying one flat rate to the total
      kWh (`price_entries.corrected_cost`) — the matched `price_entries`
      row still only prices the grid share; two new global settings,
      "PV-Preis"/"Batterie-Preis" (`report_settings.pv_price_per_kwh`/
      `bat_price_per_kwh`, top of the "Preise" panel), price the rest.
      Deliberately scoped to `/statistik` only (`web.py`'s
      `_query_sessions(..., split_pv_bat=True)`) after an initial version
      applied it app-wide and visibly changed "Kosten (korrigiert)" on
      Übersicht/Bericht erstellen/generated PDFs too — the user had only
      asked for better statistics ("i only wanted to make the statistics
      better"), not a change to those other figures; don't widen the split
      beyond `/statistik` without being asked again. Not the same idea as
      the grid-only cost basis above (that added a third *cost_basis
      value* and was rejected); this changes what "korrigiert" itself
      computes, still producing one cost figure. Raised 2026-09-04 after
      the user pointed out that a single flat corrected rate can't
      reflect openWB's own per-source pricing once it's configured
      differently there.

## Next

Nothing queued right now — see "Someday / maybe" below.

## Someday / maybe

- [ ] Multi-currency support, if this is ever useful outside Germany/EUR.
- [ ] Dynamische Stromtarife (variable/spot-price electricity tariffs) —
      `price_entries.py`'s correction model is currently a flat €/kWh over
      a validity date range, which doesn't fit a tariff that varies by
      hour. Needs research before design: does openWB's own `data.costs`
      per session already reflect the correct dynamic-tariff cost at charge
      time (in which case a dynamic-tariff user may just want `cost_basis
      = "openwb"` and no correction at all), or would this need per-hour
      price data of its own? Raised by the user (2026-09-04) as a gap, not
      yet scoped.
