# Roadmap

Loose notes on where this is headed, not a commitment. Reorder freely —
open an issue or just start working if something here matters to you.

## Done (toward v0.1.0)

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
      Landscape A4 (portrait cuts off columns once several are selected —
      caught by actually rendering and looking at it, not just reasoning
      about CSS). Report id assigned before PDF render (the doc's own
      header/footer needs it), one DB transaction covering the `reports`
      row, its `pdf_data` update, and every `report_sessions` snapshot.
- [x] Verified end to end against a real (embedded, no-root) Postgres —
      not just unit tests: source create, session listing with price
      matching, price entry CRUD, report preview/generate/list/pdf/delete,
      price overrides, and error handling (unknown column, missing
      session) all actually exercised through the real HTTP routes. See
      DEVELOPMENT.md's "Testing against a real Postgres".

## Next

- [ ] Exercise the full flow against a real, running openWB instance (only
      `chargelog_parse.py` has been checked against real openWB data so
      far — `openwb_client.py`'s actual HTTP fetch has not)
- [ ] A real `docker compose up` deployment (verified so far via a
      TestClient + embedded Postgres, not the actual Docker image/compose
      file)
- [ ] CSV export of the currently selected sessions, alongside the PDF

## Someday / maybe

- [ ] MCP server (`search_sessions`/`generate_report` type tools),
      mirroring `openwb-logger`'s `/mcp` — deliberately out of v1 scope,
      wasn't requested and adds surface area before the core flow is even
      done.
- [ ] Multi-currency support, if this is ever useful outside Germany/EUR.
