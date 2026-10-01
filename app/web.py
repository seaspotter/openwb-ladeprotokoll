"""FastAPI routes: source CRUD, fetch triggers, session listing, price
entry CRUD, and report preview/generate/list/pdf. All reads/writes are
plain parameterized SQL via asyncpg -- no ORM."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .app_settings import AppSettingsError
from .app_settings import get_settings as get_app_settings
from .app_settings import update_settings as update_app_settings
from .db import get_pool
from .fetch_service import current_month, fetch_service, month_range
from .pdf_render import ReportMeta, render_html, render_pdf
from .price_entries import PriceEntry, decide_price, match_and_decide
from .report_build import COLUMN_LABELS, ReportBuildError, _fmt_cost, _fmt_duration, _fmt_number
from .report_build import build as build_report_data
from .report_settings import ReportSettingsError
from .report_settings import get_settings as get_report_settings
from .report_settings import update_settings as update_report_settings
from .sources import SourceValidationError, normalize_base_url, validate_name
from .statistics import StatisticsError
from .statistics import aggregate as aggregate_statistics
from .statistics import aggregate_by_vehicle as aggregate_by_vehicle_statistics
from .updater import check_for_update, get_current_version, run_update, self_update_available

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class SourceIn(BaseModel):
    name: str
    base_url: str
    enabled: bool = True


class BackfillIn(BaseModel):
    from_month: str
    to_month: str


class PriceEntryIn(BaseModel):
    source_id: int | None = None
    vehicle_name: str | None = None
    provider: str
    price_per_kwh: float
    valid_from: date
    valid_to: date | None = None
    notes: str | None = None


class ReportBuildIn(BaseModel):
    session_ids: list[int]
    columns: list[str] | None = None
    # Per-session price choice, keyed by session id: an integer price_entry
    # id to force that specific entry regardless of whether it would have
    # auto-matched, the literal "openwb" to force openWB's own cost (skip
    # correction entirely), or omitted/None for the normal auto-match.
    price_overrides: dict[int, int | str | None] = {}
    # Overrides report_settings' cost_basis for this one report/preview --
    # same "global default, overridable per request" pattern as `columns`
    # above. None (the default) means "use the configured default".
    cost_basis: str | None = None


class ReportGenerateIn(ReportBuildIn):
    title: str


class VehicleIn(BaseModel):
    license_plate: str | None = None


def _fmt_dt_de(dt: datetime | None) -> str:
    """Matches the JS `toLocaleString('de-DE')` format the hx fragments
    replace: unpadded day/month, full year, comma, zero-padded H:M:S."""
    if dt is None:
        return "–"
    return f"{dt.day}.{dt.month}.{dt.year}, {dt:%H:%M:%S}"


def _source_row(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "base_url": r["base_url"],
        "enabled": r["enabled"],
        "last_fetch_at": r["last_fetch_at"].isoformat() if r["last_fetch_at"] else None,
        "last_fetch_status": r["last_fetch_status"],
    }


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/report-review", response_class=HTMLResponse)
async def report_review(request: Request):
    return templates.TemplateResponse("report_review.html", {"request": request})


@router.get("/statistik", response_class=HTMLResponse)
async def statistik(request: Request):
    return templates.TemplateResponse("statistik.html", {"request": request})


@router.get("/api/sources")
async def api_list_sources():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM sources ORDER BY name")
    return {"sources": [_source_row(r) for r in rows]}


@router.post("/api/sources")
async def api_create_source(body: SourceIn):
    try:
        name = validate_name(body.name)
        base_url = normalize_base_url(body.base_url)
    except SourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO sources (name, base_url, enabled) VALUES ($1, $2, $3) RETURNING *",
        name, base_url, body.enabled,
    )
    return _source_row(row)


@router.get("/api/sources/{source_id}")
async def api_get_source(source_id: int):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM sources WHERE id = $1", source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return _source_row(row)


@router.put("/api/sources/{source_id}")
async def api_update_source(source_id: int, body: SourceIn):
    try:
        name = validate_name(body.name)
        base_url = normalize_base_url(body.base_url)
    except SourceValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE sources SET name = $2, base_url = $3, enabled = $4 WHERE id = $1 RETURNING *",
        source_id, name, base_url, body.enabled,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return _source_row(row)


@router.delete("/api/sources/{source_id}")
async def api_delete_source(source_id: int):
    pool = get_pool()
    result = await pool.execute("DELETE FROM sources WHERE id = $1", source_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return {"ok": True}


@router.get("/api/app-settings")
async def api_get_app_settings():
    pool = get_pool()
    return await get_app_settings(pool)


@router.put("/api/app-settings")
async def api_update_app_settings(patch: dict):
    pool = get_pool()
    try:
        return await update_app_settings(pool, patch)
    except AppSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# htmx fragment routes for the Einstellungen modal (app/templates/hx/...).
# Return rendered HTML, not JSON; reuse the same helpers/SQL as the
# /api/... routes above, which stay untouched for MCP/external consumers.
# ---------------------------------------------------------------------------

async def _sources_panel_response(
    request: Request, pool, error: str | None = None, posted: dict | None = None,
):
    rows = await pool.fetch("SELECT * FROM sources ORDER BY name")
    sources = []
    for r in rows:
        s = _source_row(r)
        s["last_fetch_at_display"] = _fmt_dt_de(r["last_fetch_at"])
        sources.append(s)
    return templates.TemplateResponse(
        "hx/sources/panel.html",
        {
            "request": request,
            "sources": sources,
            "app_settings": await get_app_settings(pool),
            "error": error,
            "posted": posted or {},
        },
    )


@router.get("/hx/sources", response_class=HTMLResponse)
async def hx_sources(request: Request):
    return await _sources_panel_response(request, get_pool())


@router.post("/hx/sources", response_class=HTMLResponse)
async def hx_create_source(request: Request):
    pool = get_pool()
    form = await request.form()
    posted = {"name": form.get("name", ""), "base_url": form.get("base_url", "")}
    try:
        name = validate_name(form.get("name", ""))
        base_url = normalize_base_url(form.get("base_url", ""))
    except SourceValidationError as exc:
        return await _sources_panel_response(request, pool, error=str(exc), posted=posted)
    await pool.execute(
        "INSERT INTO sources (name, base_url, enabled) VALUES ($1, $2, true)", name, base_url,
    )
    response = await _sources_panel_response(request, pool)
    response.headers["HX-Trigger"] = "sources-changed"
    return response


@router.delete("/hx/sources/{source_id}", response_class=HTMLResponse)
async def hx_delete_source(request: Request, source_id: int):
    pool = get_pool()
    await pool.execute("DELETE FROM sources WHERE id = $1", source_id)
    response = await _sources_panel_response(request, pool)
    response.headers["HX-Trigger"] = "sources-changed"
    return response


@router.post("/hx/sources/{source_id}/fetch-now", response_class=HTMLResponse)
async def hx_fetch_now(request: Request, source_id: int):
    pool = get_pool()
    source = await _require_source(pool, source_id)
    result = await fetch_service.fetch_source(pool, source, months=[current_month()])
    error = None if result.ok else result.error
    response = await _sources_panel_response(request, pool, error=error)
    response.headers["HX-Trigger"] = "sources-changed"
    return response


@router.put("/hx/app-settings", response_class=HTMLResponse)
async def hx_update_app_settings(request: Request):
    """Each input PUTs independently (not wrapped in one <form>, so htmx
    only sends that one field) -- HX-Trigger-Name (htmx sets it to the
    triggering element's `name`) says which one fired. A checkbox's
    absence from the form means unchecked (standard HTML)."""
    pool = get_pool()
    form = await request.form()
    if request.headers.get("HX-Trigger-Name") == "auto_fetch_enabled":
        patch = {"auto_fetch_enabled": "auto_fetch_enabled" in form}
    else:
        patch = {"auto_fetch_time": form.get("auto_fetch_time", "")}
    try:
        await update_app_settings(pool, patch)
    except AppSettingsError as exc:
        return await _sources_panel_response(request, pool, error=str(exc))
    return await _sources_panel_response(request, pool)


def _price_row(r) -> dict:
    return {
        "id": r["id"],
        "source_id": r["source_id"],
        "vehicle_name": r["vehicle_name"],
        "provider": r["provider"],
        "price_per_kwh": float(r["price_per_kwh"]),
        "valid_from": r["valid_from"].isoformat(),
        "valid_to": r["valid_to"].isoformat() if r["valid_to"] else None,
        "notes": r["notes"],
        "created_at": r["created_at"].isoformat(),
    }


def _price_entry_for_matching(r) -> PriceEntry:
    """Same row, kept as native date/Decimal-free types for price_entries.py's
    pure matching/cost functions (asyncpg returns NUMERIC as Decimal, which
    doesn't compare/arithmetic cleanly against the plain floats those
    functions are written and tested against)."""
    return {
        "id": r["id"],
        "source_id": r["source_id"],
        "vehicle_name": r["vehicle_name"],
        "provider": r["provider"],
        "price_per_kwh": float(r["price_per_kwh"]),
        "valid_from": r["valid_from"],
        "valid_to": r["valid_to"],
        "notes": r["notes"],
        "created_at": r["created_at"],
    }


@router.get("/api/prices")
async def api_list_prices():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM price_entries ORDER BY valid_from DESC")
    return {"prices": [_price_row(r) for r in rows]}


@router.post("/api/prices")
async def api_create_price(body: PriceEntryIn):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO price_entries "
        "(source_id, vehicle_name, provider, price_per_kwh, valid_from, valid_to, notes) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
        body.source_id, body.vehicle_name, body.provider, body.price_per_kwh,
        body.valid_from, body.valid_to, body.notes,
    )
    return _price_row(row)


@router.get("/api/prices/{price_id}")
async def api_get_price(price_id: int):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM price_entries WHERE id = $1", price_id)
    if not row:
        raise HTTPException(status_code=404, detail="Preis nicht gefunden")
    return _price_row(row)


@router.put("/api/prices/{price_id}")
async def api_update_price(price_id: int, body: PriceEntryIn):
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE price_entries SET source_id = $2, vehicle_name = $3, provider = $4, "
        "price_per_kwh = $5, valid_from = $6, valid_to = $7, notes = $8 "
        "WHERE id = $1 RETURNING *",
        price_id, body.source_id, body.vehicle_name, body.provider, body.price_per_kwh,
        body.valid_from, body.valid_to, body.notes,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Preis nicht gefunden")
    return _price_row(row)


@router.delete("/api/prices/{price_id}")
async def api_delete_price(price_id: int):
    pool = get_pool()
    result = await pool.execute("DELETE FROM price_entries WHERE id = $1", price_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Preis nicht gefunden")
    return {"ok": True}


async def _prices_panel_response(
    request: Request, pool, error: str | None = None, pv_bat_message: str | None = None,
    posted: dict | None = None,
):
    rows = await pool.fetch(
        "SELECT p.*, s.name AS source_name FROM price_entries p "
        "LEFT JOIN sources s ON s.id = p.source_id ORDER BY p.valid_from DESC"
    )
    prices = []
    for r in rows:
        p = _price_row(r)
        p["source_name"] = r["source_name"] or "Alle"
        prices.append(p)
    sources = await pool.fetch("SELECT id, name FROM sources ORDER BY name")
    settings = await get_report_settings(pool)
    return templates.TemplateResponse(
        "hx/prices/panel.html",
        {
            "request": request,
            "prices": prices,
            "sources": sources,
            "pv_price_per_kwh": settings["pv_price_per_kwh"],
            "bat_price_per_kwh": settings["bat_price_per_kwh"],
            "error": error,
            "pv_bat_message": pv_bat_message,
            "posted": posted or {},
        },
    )


@router.get("/hx/prices", response_class=HTMLResponse)
async def hx_prices(request: Request):
    return await _prices_panel_response(request, get_pool())


@router.post("/hx/prices", response_class=HTMLResponse)
async def hx_create_price(request: Request):
    pool = get_pool()
    form = await request.form()
    source_val = form.get("source_id") or None
    posted = {k: form.get(k, "") for k in (
        "provider", "price_per_kwh", "vehicle_name", "valid_from", "valid_to", "notes",
    )}
    try:
        await pool.execute(
            "INSERT INTO price_entries "
            "(source_id, vehicle_name, provider, price_per_kwh, valid_from, valid_to, notes) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7)",
            int(source_val) if source_val else None,
            form.get("vehicle_name") or None,
            form.get("provider", ""),
            float(form.get("price_per_kwh", 0) or 0),
            date.fromisoformat(form.get("valid_from", "")),
            date.fromisoformat(form["valid_to"]) if form.get("valid_to") else None,
            form.get("notes") or None,
        )
    except (ValueError, KeyError) as exc:
        return await _prices_panel_response(
            request, pool, error=f"Ungültige Eingabe: {exc}", posted=posted,
        )
    return await _prices_panel_response(request, pool)


@router.delete("/hx/prices/{price_id}", response_class=HTMLResponse)
async def hx_delete_price(request: Request, price_id: int):
    pool = get_pool()
    await pool.execute("DELETE FROM price_entries WHERE id = $1", price_id)
    return await _prices_panel_response(request, pool)


@router.put("/hx/report-settings/pv-bat-price", response_class=HTMLResponse)
async def hx_update_pv_bat_price(request: Request):
    pool = get_pool()
    form = await request.form()
    try:
        patch = {
            "pv_price_per_kwh": float(form.get("pv_price_per_kwh", 0) or 0),
            "bat_price_per_kwh": float(form.get("bat_price_per_kwh", 0) or 0),
        }
        await update_report_settings(pool, patch)
    except (ValueError, ReportSettingsError) as exc:
        return await _prices_panel_response(request, pool, error=str(exc))
    return await _prices_panel_response(request, pool, pv_bat_message="Gespeichert.")


async def _require_source(pool, source_id: int):
    row = await pool.fetchrow("SELECT * FROM sources WHERE id = $1", source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Quelle nicht gefunden")
    return row


@router.post("/api/sources/{source_id}/fetch-now")
async def api_fetch_now(source_id: int):
    pool = get_pool()
    source = await _require_source(pool, source_id)
    result = await fetch_service.fetch_source(pool, source, months=[current_month()])
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error)
    return {"ok": True, "sessions_upserted": result.sessions_upserted}


@router.post("/api/sources/{source_id}/backfill")
async def api_backfill(source_id: int, body: BackfillIn):
    pool = get_pool()
    source = await _require_source(pool, source_id)
    try:
        months = month_range(body.from_month, body.to_month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = await fetch_service.fetch_source(pool, source, months=months)
    if not result.ok:
        raise HTTPException(status_code=502, detail=result.error)
    return {"ok": True, "sessions_upserted": result.sessions_upserted}


async def _backfill_panel_response(request: Request, pool, result_message: str | None = None):
    sources = await pool.fetch("SELECT id, name FROM sources ORDER BY name")
    return templates.TemplateResponse(
        "hx/backfill/panel.html",
        {"request": request, "sources": sources, "result_message": result_message},
    )


@router.get("/hx/backfill", response_class=HTMLResponse)
async def hx_backfill_form(request: Request):
    return await _backfill_panel_response(request, get_pool())


@router.post("/hx/backfill", response_class=HTMLResponse)
async def hx_backfill_run(request: Request):
    pool = get_pool()
    form = await request.form()
    source_val = form.get("source_id") or None
    if not source_val:
        return await _backfill_panel_response(
            request, pool, result_message="Bitte eine Quelle wählen.",
        )
    source = await pool.fetchrow("SELECT * FROM sources WHERE id = $1", int(source_val))
    if not source:
        return await _backfill_panel_response(
            request, pool, result_message="Quelle nicht gefunden.",
        )
    try:
        from_month = form.get("from_month", "").replace("-", "")
        to_month = form.get("to_month", "").replace("-", "")
        months = month_range(from_month, to_month)
    except ValueError as exc:
        return await _backfill_panel_response(request, pool, result_message=f"Fehler: {exc}")
    result = await fetch_service.fetch_source(pool, source, months=months)
    message = (
        f"Fertig: {result.sessions_upserted} Ladevorgänge verarbeitet."
        if result.ok else f"Fehler: {result.error}"
    )
    response = await _backfill_panel_response(request, pool, result_message=message)
    if result.ok:
        response.headers["HX-Trigger"] = "sources-changed"
    return response


async def _fetch_session_rows(
    pool,
    source_id: int | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: date | None = None,
    to: date | None = None,
):
    """Raw asyncpg rows for the same source/vehicle/chargepoint/date
    filter _query_sessions applies, for callers (the report-review table)
    that need the unconverted row to resolve a price decision themselves
    rather than _query_sessions' own already-dict-ified output."""
    clauses = []
    params: list = []

    def add(clause: str, value) -> None:
        params.append(value)
        clauses.append(clause.format(len(params)))

    if source_id is not None:
        add("source_id = ${}", source_id)
    if vehicle:
        add("vehicle_name = ${}", vehicle)
    if chargepoint:
        add("chargepoint_name = ${}", chargepoint)
    if from_:
        add("time_begin::date >= ${}", from_)
    if to:
        add("time_begin::date <= ${}", to)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return await pool.fetch(f"SELECT * FROM sessions {where} ORDER BY time_begin DESC", *params)


async def _query_sessions(
    pool,
    source_id: int | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: date | None = None,
    to: date | None = None,
    split_pv_bat: bool = False,
) -> list[dict]:
    """Shared by GET /api/sessions, MCP's search_sessions, and
    /api/statistics. `split_pv_bat` must stay False for everything except
    /api/statistics -- it changes what cost_corrected means, and widening
    it elsewhere changed "Kosten (korrigiert)" app-wide unexpectedly once."""
    rows = await _fetch_session_rows(pool, source_id, vehicle, chargepoint, from_, to)
    # Loaded once per request, not per session -- price_entries is a small
    # table (a handful of rows per fleet/tariff), so this stays cheap even
    # for a large session list.
    price_rows = await pool.fetch("SELECT * FROM price_entries")
    entries = [_price_entry_for_matching(r) for r in price_rows]
    split_kwargs = {}
    if split_pv_bat:
        settings = await get_report_settings(pool)
        split_kwargs = {"pv_price_per_kwh": settings["pv_price_per_kwh"],
                         "bat_price_per_kwh": settings["bat_price_per_kwh"]}

    sessions = []
    for r in rows:
        d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()
             if k != "raw_json"}
        energy_kwh = float(r["energy_kwh"]) if r["energy_kwh"] is not None else None
        cost_openwb = float(r["cost_openwb"]) if r["cost_openwb"] is not None else None
        if split_pv_bat:
            decision = match_and_decide(
                entries,
                source_id=r["source_id"],
                vehicle_name=r["vehicle_name"],
                session_date=r["time_begin"].date(),
                energy_kwh=energy_kwh,
                cost_openwb=cost_openwb,
                power_source_grid_pct=_to_float(r["power_source_grid_pct"]),
                power_source_pv_pct=_to_float(r["power_source_pv_pct"]),
                power_source_bat_pct=_to_float(r["power_source_bat_pct"]),
                power_source_cp_pct=_to_float(r["power_source_cp_pct"]),
                **split_kwargs,
            )
        else:
            decision = match_and_decide(
                entries,
                source_id=r["source_id"],
                vehicle_name=r["vehicle_name"],
                session_date=r["time_begin"].date(),
                energy_kwh=energy_kwh,
                cost_openwb=cost_openwb,
            )
        # Decimal (asyncpg's NUMERIC type) breaks statistics.py's float math.
        d["energy_kwh"] = energy_kwh
        d["cost_openwb"] = cost_openwb
        for pct_key in (
            "power_source_grid_pct", "power_source_cp_pct",
            "power_source_bat_pct", "power_source_pv_pct",
        ):
            d[pct_key] = _to_float(r[pct_key])
        d["price_entry_id"] = decision.price_entry["id"] if decision.price_entry else None
        d["price_provider"] = decision.price_entry["provider"] if decision.price_entry else None
        d["cost_corrected"] = decision.cost_corrected
        d["cost_used"] = decision.cost_used
        d["cost_delta"] = decision.delta
        d["cost_delta_flagged"] = decision.delta_flagged
        if split_pv_bat:
            breakdown = decision.cost_breakdown
            d["cost_corrected_grid"] = breakdown.grid if breakdown else 0.0
            d["cost_corrected_pv"] = breakdown.pv if breakdown else 0.0
            d["cost_corrected_bat"] = breakdown.bat if breakdown else 0.0
        sessions.append(d)
    return sessions


@router.get("/api/sessions")
async def api_sessions(
    source_id: int | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: date | None = None,
    to: date | None = None,
):
    pool = get_pool()
    sessions = await _query_sessions(pool, source_id, vehicle, chargepoint, from_, to)
    return {"sessions": sessions}


# ---------------------------------------------------------------------------
# htmx fragment routes for the three pages' own filter dropdowns (source/
# vehicle/chargepoint <select>s) -- shared across index.html,
# report_review.html, statistik.html, since all three populate the same
# "Alle Quellen" source select the same way.
# ---------------------------------------------------------------------------

async def _distinct_values(pool, column: str, source_id: int | None) -> list[str]:
    """column is always one of the two hardcoded literals below, never
    request input, so building the query with an f-string is safe here."""
    query = f"SELECT DISTINCT {column} FROM sessions WHERE {column} IS NOT NULL"
    params = []
    if source_id is not None:
        query += " AND source_id = $1"
        params.append(source_id)
    query += f" ORDER BY {column}"
    rows = await pool.fetch(query, *params)
    return [r[column] for r in rows]


@router.get("/hx/filters/sources", response_class=HTMLResponse)
async def hx_filter_sources(request: Request, with_freshness: str | None = None):
    """Shared "Alle Quellen" <select> options. `with_freshness` additionally
    renders an hx-swap-oob update for index.html's #fetch-result line --
    only index.html passes it; report_review.html/statistik.html don't have
    that element, and htmx logs an oobErrorNoTarget console error for an
    oob fragment with no matching target, so this is opt-in, not harmlessly
    ignored."""
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM sources ORDER BY name")
    sources = [_source_row(r) for r in rows]
    freshness = None
    if with_freshness:
        timestamps = [s["last_fetch_at"] for s in sources if s["last_fetch_at"]]
        if not timestamps:
            freshness = "Noch kein Abruf erfolgt."
        else:
            latest = max(timestamps)
            failed = sum(
                1 for s in sources
                if s["enabled"] and s["last_fetch_status"] and s["last_fetch_status"] != "ok"
            )
            freshness = f"Letzter Abruf: {_fmt_dt_de(datetime.fromisoformat(latest))}"
            if failed:
                freshness += (
                    f" ({failed} Quelle(n) zuletzt fehlgeschlagen -- "
                    'Details unter "⚙ Einstellungen")'
                )
    return templates.TemplateResponse(
        "hx/filters/sources.html", {"request": request, "sources": sources, "freshness": freshness},
    )


@router.get("/hx/filters/vehicles", response_class=HTMLResponse)
async def hx_filter_vehicles(request: Request):
    """Every distinct vehicle name ever seen, unfiltered -- statistik.html's
    vehicle filter isn't chained off the source filter the way
    index.html's/report_review.html's are."""
    vehicles = await _distinct_values(get_pool(), "vehicle_name", None)
    return templates.TemplateResponse(
        "hx/filters/vehicles.html", {"request": request, "vehicles": vehicles},
    )


@router.get("/hx/filters/vehicle-chargepoint", response_class=HTMLResponse)
async def hx_filter_vehicle_chargepoint(
    request: Request,
    source_id: str | None = None, vehicle: str | None = None, chargepoint: str | None = None,
):
    """index.html/report_review.html: vehicle/chargepoint options narrowed
    to the currently-selected source. One request renders both selects
    (chargepoint via hx-swap-oob) since both depend on the same source
    filter. `vehicle`/`chargepoint` are the selects' own current values
    (re-included on every request) so a still-valid selection survives a
    source change instead of silently resetting to "Alle"."""
    pool = get_pool()
    sid = int(source_id) if source_id else None
    vehicles = await _distinct_values(pool, "vehicle_name", sid)
    chargepoints = await _distinct_values(pool, "chargepoint_name", sid)
    return templates.TemplateResponse(
        "hx/filters/vehicle_chargepoint.html",
        {
            "request": request, "vehicles": vehicles, "chargepoints": chargepoints,
            "selected_vehicle": vehicle, "selected_chargepoint": chargepoint,
        },
    )


@router.get("/hx/sessions", response_class=HTMLResponse)
async def hx_sessions(
    request: Request,
    source_id: str | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: str | None = None,
    to: str | None = None,
):
    """Query params come from htmx serializing the whole filter <form>,
    including empty/unselected fields as empty strings rather than
    omitting them -- unlike /api/sessions's typed int|None/date|None
    params (used by real API callers who only ever send what they mean),
    these need to tolerate "" as "no filter"."""
    pool = get_pool()
    sessions = await _query_sessions(
        pool,
        int(source_id) if source_id else None,
        vehicle or None,
        chargepoint or None,
        date.fromisoformat(from_) if from_ else None,
        date.fromisoformat(to) if to else None,
    )
    source_rows = await pool.fetch("SELECT id, name FROM sources")
    names_by_id = {r["id"]: r["name"] for r in source_rows}
    rows = []
    for s in sessions:
        rows.append({
            "time_begin_display": _fmt_dt_de(
                datetime.fromisoformat(s["time_begin"]) if s["time_begin"] else None
            ),
            "source_name": names_by_id.get(s["source_id"], f"#{s['source_id']}"),
            "vehicle_name": s["vehicle_name"],
            "chargepoint_name": s["chargepoint_name"],
            "energy_display": _fmt_number(s["energy_kwh"], 2, " kWh"),
            "cost_openwb_display": _fmt_cost(s["cost_openwb"]),
            "price_label": s["price_provider"] or "kein Preis hinterlegt",
            "cost_used_display": _fmt_cost(s["cost_used"]),
            "flagged": s["cost_delta_flagged"],
        })
    return templates.TemplateResponse(
        "hx/sessions/table.html", {"request": request, "sessions": rows, "count": len(rows)},
    )


@router.post("/hx/fetch-now", response_class=HTMLResponse)
async def hx_fetch_now_all(request: Request):
    """Fetches every enabled source's current month in one request
    (server-side loop) instead of the page issuing one fetch-now call per
    source and recombining the results client-side."""
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM sources WHERE enabled")
    if not rows:
        message = 'Keine aktive Quelle -- unter "⚙ Einstellungen" hinzufügen.'
    else:
        for source in rows:
            await fetch_service.fetch_source(pool, source, months=[current_month()])
        message = "Abruf abgeschlossen."
    response = templates.TemplateResponse(
        "hx/_msg.html", {"request": request, "msg": message},
    )
    if rows:
        response.headers["HX-Trigger"] = "sources-changed"
    return response


@router.get("/api/vehicles")
async def api_list_vehicles():
    """Every vehicle name ever seen across all sources' sessions, left-joined
    with its optionally configured Kennzeichen -- openWB's own data has no
    license-plate field, so this is purely user-entered metadata, documented
    on generated reports (see _report_meta below)."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT s.vehicle_name, v.license_plate "
        "FROM (SELECT DISTINCT vehicle_name FROM sessions WHERE vehicle_name IS NOT NULL) s "
        "LEFT JOIN vehicles v ON v.vehicle_name = s.vehicle_name "
        "ORDER BY s.vehicle_name"
    )
    return {
        "vehicles": [
            {"vehicle_name": r["vehicle_name"], "license_plate": r["license_plate"]} for r in rows
        ]
    }


@router.put("/api/vehicles/{vehicle_name}")
async def api_update_vehicle(vehicle_name: str, body: VehicleIn):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO vehicles (vehicle_name, license_plate, updated_at) "
        "VALUES ($1, $2, now()) "
        "ON CONFLICT (vehicle_name) DO UPDATE SET license_plate = $2, updated_at = now() "
        "RETURNING vehicle_name, license_plate",
        vehicle_name, body.license_plate,
    )
    return {"vehicle_name": row["vehicle_name"], "license_plate": row["license_plate"]}


async def _vehicles_panel_response(request: Request, pool, saved: str | None = None):
    rows = await pool.fetch(
        "SELECT s.vehicle_name, v.license_plate "
        "FROM (SELECT DISTINCT vehicle_name FROM sessions WHERE vehicle_name IS NOT NULL) s "
        "LEFT JOIN vehicles v ON v.vehicle_name = s.vehicle_name "
        "ORDER BY s.vehicle_name"
    )
    vehicles = [
        {"vehicle_name": r["vehicle_name"], "license_plate": r["license_plate"]} for r in rows
    ]
    return templates.TemplateResponse(
        "hx/vehicles/panel.html",
        {"request": request, "vehicles": vehicles, "saved": saved},
    )


@router.get("/hx/vehicles", response_class=HTMLResponse)
async def hx_vehicles(request: Request):
    return await _vehicles_panel_response(request, get_pool())


@router.put("/hx/vehicles/{vehicle_name}", response_class=HTMLResponse)
async def hx_update_vehicle(request: Request, vehicle_name: str):
    pool = get_pool()
    form = await request.form()
    await pool.execute(
        "INSERT INTO vehicles (vehicle_name, license_plate, updated_at) "
        "VALUES ($1, $2, now()) "
        "ON CONFLICT (vehicle_name) DO UPDATE SET license_plate = $2, updated_at = now()",
        vehicle_name, form.get("license_plate") or None,
    )
    return await _vehicles_panel_response(request, pool, saved=vehicle_name)


@router.get("/api/statistics")
async def api_statistics(
    granularity: str = "month",
    source_id: int | None = None,
    vehicle: str | None = None,
):
    """Per-month/year + per-vehicle aggregates for /statistik. split_pv_bat=
    True here only (see _query_sessions)."""
    pool = get_pool()
    settings = await get_report_settings(pool)
    sessions = await _query_sessions(
        pool, source_id, vehicle, None, None, None, split_pv_bat=True
    )
    try:
        periods = aggregate_statistics(sessions, granularity, settings["cost_basis"])
        by_vehicle = aggregate_by_vehicle_statistics(sessions, settings["cost_basis"])
    except StatisticsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "periods": [vars(p) for p in periods],
        "by_vehicle": [vars(v) for v in by_vehicle],
    }


@router.get("/hx/statistik", response_class=HTMLResponse)
async def hx_statistik(
    request: Request,
    granularity: str = "month",
    source_id: str | None = None,
    vehicle: str | None = None,
):
    pool = get_pool()
    settings = await get_report_settings(pool)
    cost_basis = settings["cost_basis"]
    sessions = await _query_sessions(
        pool, int(source_id) if source_id else None, vehicle or None, None, None, None,
        split_pv_bat=True,
    )
    try:
        periods = aggregate_statistics(sessions, granularity, cost_basis)
        by_vehicle = aggregate_by_vehicle_statistics(sessions, cost_basis)
    except StatisticsError as exc:
        return HTMLResponse(f"Fehler: {exc}", status_code=200)

    def _share(part: float, whole: float) -> str:
        return _fmt_number(part / whole * 100, 0, " %") if whole > 0 else "–"

    total_sessions = sum(p.session_count for p in periods)
    total_energy = sum(p.energy_kwh for p in periods)
    total_pv = sum(p.energy_pv_kwh + p.energy_bat_kwh for p in periods)

    vehicles = [
        {
            "vehicle_name": v.vehicle_name,
            "session_count": v.session_count,
            "energy_display": _fmt_number(v.energy_kwh, 1, " kWh"),
            "grid_share_display": _share(v.energy_grid_kwh, v.energy_kwh),
            "pv_share_display": _share(v.energy_pv_kwh, v.energy_kwh),
            "bat_share_display": _share(v.energy_bat_kwh, v.energy_kwh),
            "cost_display": _fmt_cost(v.cost),
        }
        for v in by_vehicle
    ]

    chart_data = {
        "labels": [p.period for p in periods],
        "energy_grid": [p.energy_grid_kwh for p in periods],
        "energy_pv": [p.energy_pv_kwh for p in periods],
        "energy_bat": [p.energy_bat_kwh for p in periods],
        "energy_cp": [p.energy_cp_kwh for p in periods],
        "cost_basis": cost_basis,
    }
    cost_breakdown_totals = {}
    if cost_basis == "corrected":
        chart_data["cost_grid"] = [p.cost_grid for p in periods]
        chart_data["cost_pv"] = [p.cost_pv for p in periods]
        chart_data["cost_bat"] = [p.cost_bat for p in periods]
        cost_breakdown_totals = {
            "cost_grid_total_display": _fmt_cost(sum(p.cost_grid for p in periods)),
            "cost_pv_total_display": _fmt_cost(sum(p.cost_pv for p in periods)),
            "cost_bat_total_display": _fmt_cost(sum(p.cost_bat for p in periods)),
        }
    else:
        chart_data["cost"] = [p.cost for p in periods]

    return templates.TemplateResponse(
        "hx/statistik/stats.html",
        {
            "request": request,
            "empty": not periods,
            "stat_sessions": total_sessions,
            "stat_energy_display": _fmt_number(total_energy, 1, " kWh"),
            "cost_label": f"Kosten ({_COST_BASIS_LABELS[cost_basis]})",
            "stat_cost_display": _fmt_cost(sum(p.cost for p in periods)),
            "stat_pv_share_display": _share(total_pv, total_energy),
            "cost_basis": cost_basis,
            "vehicles": vehicles,
            "chart_data_json": json.dumps(chart_data),
            **cost_breakdown_totals,
        },
    )


@router.get("/api/report-columns")
async def api_report_columns():
    """Ordered list of every column report_build.py can render, plus which
    ones are pre-checked by default (Berichts-Einstellungen) -- so the
    review UI's toggle checklist stays in sync with both instead of
    hardcoding a second copy."""
    pool = get_pool()
    settings = await get_report_settings(pool)
    return {
        "columns": [{"key": k, "label": v} for k, v in COLUMN_LABELS.items()],
        "default_columns": settings["default_columns"],
    }


@router.get("/api/report-settings")
async def api_get_report_settings():
    pool = get_pool()
    return await get_report_settings(pool)


@router.put("/api/report-settings")
async def api_update_report_settings(patch: dict):
    pool = get_pool()
    try:
        return await update_report_settings(pool, patch)
    except ReportSettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


async def _report_settings_panel_response(
    request: Request, pool, error: str | None = None, saved: bool = False,
):
    settings = await get_report_settings(pool)
    columns = [
        {"key": k, "label": v, "checked": k in settings["default_columns"]}
        for k, v in COLUMN_LABELS.items()
    ]
    return templates.TemplateResponse(
        "hx/report_settings/panel.html",
        {
            "request": request, "columns": columns, "settings": settings,
            "error": error, "saved": saved,
        },
    )


@router.get("/hx/report-settings", response_class=HTMLResponse)
async def hx_report_settings(request: Request):
    return await _report_settings_panel_response(request, get_pool())


@router.put("/hx/report-settings", response_class=HTMLResponse)
async def hx_update_report_settings(request: Request):
    pool = get_pool()
    form = await request.form()
    patch = {
        "default_columns": form.getlist("default_columns"),
        "cost_basis": form.get("cost_basis", ""),
        "orientation": form.get("orientation", ""),
        "show_signature_line": "show_signature_line" in form,
    }
    try:
        await update_report_settings(pool, patch)
    except ReportSettingsError as exc:
        return await _report_settings_panel_response(request, pool, error=str(exc))
    return await _report_settings_panel_response(request, pool, saved=True)


def _to_float(value) -> float | None:
    """asyncpg returns NUMERIC columns as Decimal; every consumer here
    (price_entries.py, report_build.py, pdf_render.py) is written and
    tested against plain floats -- see DEVELOPMENT.md."""
    return None if value is None else float(value)


def _jsonable(value):
    """Recursively converts date/datetime values to ISO strings so a dict
    can be handed to asyncpg's jsonb codec (plain json.dumps, no datetime
    support) for a snapshot column -- see report_sessions.snapshot /
    price_entry_snapshot below."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _resolve_price_decision(row, entries_list, entries_by_id, override):
    """Plain flat-rate decision -- never the Statistik PV/battery split;
    reports must match what Bericht-review showed at generation time."""
    energy_kwh = _to_float(row["energy_kwh"])
    cost_openwb = _to_float(row["cost_openwb"])
    if override == "openwb":
        return decide_price(energy_kwh=energy_kwh, cost_openwb=cost_openwb, price_entry=None)
    if override is not None:
        entry = entries_by_id.get(int(override))
        if entry is None:
            raise HTTPException(status_code=400, detail=f"Unbekannter Preis-Override: {override}")
        return decide_price(energy_kwh=energy_kwh, cost_openwb=cost_openwb, price_entry=entry)
    return match_and_decide(
        entries_list,
        source_id=row["source_id"],
        vehicle_name=row["vehicle_name"],
        session_date=row["time_begin"].date(),
        energy_kwh=energy_kwh,
        cost_openwb=cost_openwb,
    )


async def _load_report_sessions(pool, session_ids: list[int], price_overrides: dict):
    """Loads the requested sessions (in the caller's own order, not DB
    order) plus every price entry, resolves each session's price decision
    (an override if given, else the normal auto-match), and returns both
    the report_build.py-ready dicts and the raw DB rows (the latter still
    needed by the caller for their own `id`/`source_id` when persisting)."""
    if not session_ids:
        raise HTTPException(status_code=400, detail="Keine Ladevorgänge ausgewählt")

    rows = await pool.fetch("SELECT * FROM sessions WHERE id = ANY($1::bigint[])", session_ids)
    rows_by_id = {r["id"]: r for r in rows}
    missing = [sid for sid in session_ids if sid not in rows_by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Ladevorgänge nicht gefunden: {missing}")
    ordered_rows = [rows_by_id[sid] for sid in session_ids]

    price_rows = await pool.fetch("SELECT * FROM price_entries")
    entries_list = [_price_entry_for_matching(r) for r in price_rows]
    entries_by_id = {e["id"]: e for e in entries_list}

    sessions = []
    for r in ordered_rows:
        override = price_overrides.get(r["id"]) if price_overrides else None
        decision = _resolve_price_decision(r, entries_list, entries_by_id, override)
        sessions.append({
            "id": r["id"],
            "time_begin": r["time_begin"],
            "time_end": r["time_end"],
            "time_charged_seconds": r["time_charged_seconds"],
            "vehicle_name": r["vehicle_name"],
            "odometer": _to_float(r["odometer"]),
            "chargepoint_name": r["chargepoint_name"],
            "chargepoint_serial_number": r["chargepoint_serial_number"],
            "energy_kwh": _to_float(r["energy_kwh"]),
            "energy_discharged_kwh": _to_float(r["energy_discharged_kwh"]),
            "range_charged_km": _to_float(r["range_charged_km"]),
            "meter_start_kwh": _to_float(r["meter_start_kwh"]),
            "meter_end_kwh": _to_float(r["meter_end_kwh"]),
            "cost_openwb": decision.cost_openwb,
            "cost_corrected": decision.cost_corrected,
            "cost_used": decision.cost_used,
            "price_entry": decision.price_entry,
            "delta_flagged": decision.delta_flagged,
        })
    return sessions, ordered_rows


# German label for report_build.COST_BASES, shown in "Bisherige Berichte"
# only -- not in the PDF itself (deliberate, see CLAUDE.md).
_COST_BASIS_LABELS = {"openwb": "openWB-Wert", "corrected": "Korrigiert"}


def _parse_review_selection(form) -> tuple[list[int], dict]:
    """Report-review's session table posts its full state as `all_ids`
    (every currently-loaded session, so unchecked ones aren't silently
    lost -- a checkbox absent from form data just means unchecked) plus
    per-row `selected_<id>`/`override_<id>` fields. Returns (checked ids
    in table order, {id: override}), override one of "auto"/"openwb"/a
    price_entry id string."""
    all_ids = [int(v) for v in form.getlist("all_ids")]
    checked_ids = [sid for sid in all_ids if f"selected_{sid}" in form]
    overrides = {sid: form.get(f"override_{sid}", "auto") for sid in all_ids}
    return checked_ids, overrides


async def _review_rows_response(
    request: Request, pool, *,
    source_id: str | None, vehicle: str | None, chargepoint: str | None,
    from_: str | None, to: str | None,
    checked_ids: list[int] | None = None, overrides: dict | None = None,
):
    """Renders the report-review session table + totals-grid + session
    count together (one fragment, three hx-swap-oob targets besides the
    primary tbody) -- an override changes that row's own displayed
    "Kosten (korrigiert)", not just the totals, so both re-render on every
    change regardless of which one actually triggered it.

    `checked_ids=None` means "everything checked" (a fresh filter load);
    `overrides=None` means every row defaults to "auto". Both are given
    explicitly when re-rendering after a checkbox/override change."""
    rows = await _fetch_session_rows(
        pool,
        int(source_id) if source_id else None,
        vehicle or None,
        chargepoint or None,
        date.fromisoformat(from_) if from_ else None,
        date.fromisoformat(to) if to else None,
    )
    price_rows = await pool.fetch("SELECT * FROM price_entries")
    entries_list = [_price_entry_for_matching(r) for r in price_rows]
    entries_by_id = {e["id"]: e for e in entries_list}

    display_rows = []
    totals = {
        "count": 0, "duration": 0, "energy": 0.0, "discharged": 0.0,
        "range": 0.0, "cost_openwb": 0.0, "cost_used": 0.0,
    }
    for r in rows:
        override = (overrides or {}).get(r["id"], "auto")
        decision = _resolve_price_decision(
            r, entries_list, entries_by_id, None if override == "auto" else override,
        )
        # Independent of the active override -- the "Automatisch (...)"
        # option always names what auto-match would actually use.
        auto_decision = match_and_decide(
            entries_list, source_id=r["source_id"], vehicle_name=r["vehicle_name"],
            session_date=r["time_begin"].date(),
            energy_kwh=_to_float(r["energy_kwh"]), cost_openwb=_to_float(r["cost_openwb"]),
        )
        checked = True if checked_ids is None else (r["id"] in checked_ids)
        flagged = override == "auto" and decision.delta_flagged
        display_rows.append({
            "id": r["id"],
            "checked": checked,
            "override": override,
            "time_begin_display": _fmt_dt_de(r["time_begin"]),
            "vehicle_name": r["vehicle_name"],
            "chargepoint_name": r["chargepoint_name"],
            "energy_display": _fmt_number(_to_float(r["energy_kwh"]), 2, " kWh"),
            "cost_openwb_display": _fmt_cost(decision.cost_openwb),
            "cost_used_display": _fmt_cost(decision.cost_used),
            "flagged": flagged,
            "auto_provider": auto_decision.price_entry["provider"] if auto_decision.price_entry else None,
        })
        if checked:
            totals["count"] += 1
            totals["duration"] += r["time_charged_seconds"] or 0
            totals["energy"] += _to_float(r["energy_kwh"]) or 0
            totals["discharged"] += _to_float(r["energy_discharged_kwh"]) or 0
            totals["range"] += _to_float(r["range_charged_km"]) or 0
            totals["cost_openwb"] += decision.cost_openwb or 0
            totals["cost_used"] += decision.cost_used or 0

    totals_display = {
        "count": totals["count"],
        "duration_display": _fmt_duration(totals["duration"]),
        "energy_display": _fmt_number(totals["energy"], 2, " kWh"),
        "discharged_display": _fmt_number(totals["discharged"], 2, " kWh"),
        "range_display": _fmt_number(totals["range"], 0, " km"),
        "cost_openwb_display": _fmt_cost(totals["cost_openwb"]),
        "cost_used_display": _fmt_cost(totals["cost_used"]),
    }
    return templates.TemplateResponse(
        "hx/report_review/sessions.html",
        {
            "request": request,
            "sessions": display_rows,
            "price_entries": entries_list,
            "totals": totals_display,
            "total_count": len(rows),
        },
    )


@router.get("/hx/report-review/sessions", response_class=HTMLResponse)
async def hx_report_review_sessions(
    request: Request,
    source_id: str | None = None, vehicle: str | None = None, chargepoint: str | None = None,
    from_: str | None = None, to: str | None = None,
):
    """Filter changed (or first load) -- always resets every row to
    checked+auto, same as the old loadSessions() did."""
    return await _review_rows_response(
        request, get_pool(),
        source_id=source_id, vehicle=vehicle, chargepoint=chargepoint, from_=from_, to=to,
    )


@router.post("/hx/report-review/totals", response_class=HTMLResponse)
async def hx_report_review_totals(request: Request):
    """A checkbox or override <select> changed -- re-derive the same
    session set from the (hidden, hx-include'd) filter fields and overlay
    the posted checked/override state, instead of trusting the client to
    have kept an accurate in-memory copy."""
    form = await request.form()
    checked_ids, overrides = _parse_review_selection(form)
    return await _review_rows_response(
        request, get_pool(),
        source_id=form.get("source_id") or None, vehicle=form.get("vehicle") or None,
        chargepoint=form.get("chargepoint") or None,
        from_=form.get("from_") or None, to=form.get("to") or None,
        checked_ids=checked_ids, overrides=overrides,
    )


async def _report_meta(
    pool, report_id: str, title: str, generated_at: datetime, rows, settings: dict,
) -> ReportMeta:
    source_rows = await pool.fetch("SELECT id, name FROM sources")
    sources_by_id = {r["id"]: r["name"] for r in source_rows}
    vehicle_rows = await pool.fetch("SELECT vehicle_name, license_plate FROM vehicles")
    plates_by_vehicle = {
        r["vehicle_name"]: r["license_plate"] for r in vehicle_rows if r["license_plate"]
    }
    begins = [r["time_begin"] for r in rows]
    source_names = {sources_by_id.get(r["source_id"], f"#{r['source_id']}") for r in rows}
    vehicle_names = sorted({r["vehicle_name"] for r in rows if r["vehicle_name"]})
    vehicle_display = [
        f"{name} ({plates_by_vehicle[name]})" if plates_by_vehicle.get(name) else name
        for name in vehicle_names
    ]
    return ReportMeta(
        report_id=report_id,
        title=title,
        generated_at=generated_at,
        period_from=min(begins).strftime("%d.%m.%Y") if begins else None,
        period_to=max(begins).strftime("%d.%m.%Y") if begins else None,
        source_names=sorted(source_names),
        vehicle_names=vehicle_display,
        show_signature_line=settings["show_signature_line"],
        orientation=settings["orientation"],
    )


def _pdf_filename(title: str, created_at: datetime) -> str:
    """"20260904 Ladeprotokoll <title>.pdf" -- date prefix so files sort
    chronologically wherever they're saved, since the user-given title alone
    doesn't."""
    safe_title = re.sub(r'[\\/:"*?<>|]+', "-", title).strip() or "Bericht"
    return f"{created_at:%Y%m%d} Ladeprotokoll {safe_title}.pdf"


def _content_disposition(filename: str) -> str:
    """RFC 6266: a plain ASCII fallback filename plus an RFC 5987
    filename*=UTF-8'' extended parameter so umlauts in the title (routine in
    German vehicle/provider names) still show up correctly in browsers that
    honor it, without breaking the ones that only read the plain parameter."""
    ascii_fallback = (
        filename.encode("ascii", "ignore").decode("ascii").strip() or "ladeprotokoll.pdf"
    )
    return f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'


_REPORT_SUMMARY_SELECT = (
    "SELECT r.id, r.created_at, r.title, r.column_selection, r.total_duration_seconds, "
    "r.total_energy_kwh, r.total_energy_discharged_kwh, r.total_range_charged_km, "
    "r.total_cost_openwb, r.total_cost_corrected, r.cost_basis, "
    "(SELECT count(*) FROM report_sessions rs WHERE rs.report_id = r.id) AS session_count "
    "FROM reports r"
)


def _report_summary_row(r) -> dict:
    cost_basis = r["cost_basis"]
    total_cost = float(r["total_cost_openwb"] if cost_basis == "openwb" else r["total_cost_corrected"])
    return {
        "id": r["id"],
        "created_at": r["created_at"].isoformat(),
        "title": r["title"],
        "column_selection": r["column_selection"],
        "total_duration_seconds": r["total_duration_seconds"],
        "total_energy_kwh": float(r["total_energy_kwh"]),
        "total_energy_discharged_kwh": float(r["total_energy_discharged_kwh"]),
        "total_range_charged_km": float(r["total_range_charged_km"]),
        "total_cost_openwb": float(r["total_cost_openwb"]),
        "total_cost_corrected": float(r["total_cost_corrected"]),
        "cost_basis": cost_basis,
        "cost_basis_label": _COST_BASIS_LABELS[cost_basis],
        # The report's own actual headline total -- whichever of the two
        # raw totals above matches cost_basis -- so "Bisherige Berichte"
        # can show one "Kosten" column instead of two per row.
        "total_cost": total_cost,
        "session_count": r["session_count"],
    }


@router.post("/api/reports/preview", response_class=HTMLResponse)
async def api_report_preview(body: ReportBuildIn):
    """Runs the same build as api_create_report below, but renders straight
    to HTML and persists nothing -- for the review UI's live preview."""
    pool = get_pool()
    settings = await get_report_settings(pool)
    cost_basis = body.cost_basis or settings["cost_basis"]
    sessions, rows = await _load_report_sessions(pool, body.session_ids, body.price_overrides)
    try:
        data = build_report_data(sessions, body.columns or settings["default_columns"], cost_basis)
    except ReportBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    meta = await _report_meta(pool, "Vorschau", "Vorschau", datetime.now(), rows, settings)
    return render_html(data, meta)


async def _generate_report(
    pool, title: str, session_ids: list[int], columns: list[str] | None, price_overrides: dict,
    cost_basis: str | None = None,
) -> dict:
    """Builds and persists an immutable report; shared by the HTTP route
    and the MCP generate_report tool. Insert-then-render-then-update
    because the PDF needs the row's id first. `cost_basis=None` uses
    report_settings' default. Raises ReportBuildError on failure."""
    settings = await get_report_settings(pool)
    resolved_cost_basis = cost_basis or settings["cost_basis"]
    sessions, rows = await _load_report_sessions(pool, session_ids, price_overrides)
    data = build_report_data(
        sessions, columns or settings["default_columns"], resolved_cost_basis
    )

    async with pool.acquire() as conn, conn.transaction():
        report_row = await conn.fetchrow(
            "INSERT INTO reports (title, column_selection, total_duration_seconds, "
            "total_energy_kwh, total_energy_discharged_kwh, total_range_charged_km, "
            "total_cost_openwb, total_cost_corrected, cost_basis, pdf_data) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) RETURNING id, created_at",
            title, data.columns, data.totals.duration_seconds,
            data.totals.energy_kwh, data.totals.energy_discharged_kwh,
            data.totals.range_charged_km, data.totals.cost_openwb,
            data.totals.cost_corrected, resolved_cost_basis, b"",
        )
        report_id = report_row["id"]

        meta = await _report_meta(
            pool, str(report_id), title, report_row["created_at"], rows, settings
        )
        pdf_bytes = render_pdf(data, meta)
        await conn.execute(
            "UPDATE reports SET pdf_data = $2 WHERE id = $1", report_id, pdf_bytes
        )

        for s, r in zip(sessions, rows):
            snapshot = _jsonable({k: v for k, v in s.items() if k != "price_entry"})
            price_entry = s.get("price_entry")
            await conn.execute(
                "INSERT INTO report_sessions (report_id, session_id, snapshot, "
                "price_entry_snapshot, cost_openwb, cost_corrected, cost_used) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                report_id, r["id"], snapshot,
                _jsonable(price_entry) if price_entry else None,
                s.get("cost_openwb"), s.get("cost_corrected"), s.get("cost_used"),
            )

    row = await pool.fetchrow(f"{_REPORT_SUMMARY_SELECT} WHERE r.id = $1", report_id)
    return _report_summary_row(row)


@router.post("/api/reports")
async def api_create_report(body: ReportGenerateIn):
    pool = get_pool()
    try:
        return await _generate_report(
            pool, body.title, body.session_ids, body.columns, body.price_overrides,
            body.cost_basis,
        )
    except ReportBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/reports")
async def api_list_reports():
    pool = get_pool()
    rows = await pool.fetch(f"{_REPORT_SUMMARY_SELECT} ORDER BY r.created_at DESC")
    return {"reports": [_report_summary_row(r) for r in rows]}


@router.get("/reports/{report_id}")
async def api_get_report(report_id: int):
    pool = get_pool()
    row = await pool.fetchrow(f"{_REPORT_SUMMARY_SELECT} WHERE r.id = $1", report_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bericht nicht gefunden")
    return _report_summary_row(row)


@router.get("/reports/{report_id}/pdf")
async def api_get_report_pdf(report_id: int):
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT pdf_data, title, created_at FROM reports WHERE id = $1", report_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Bericht nicht gefunden")
    filename = _pdf_filename(row["title"], row["created_at"])
    return Response(
        content=bytes(row["pdf_data"]),
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(filename)},
    )


@router.delete("/reports/{report_id}")
async def api_delete_report(report_id: int):
    pool = get_pool()
    result = await pool.execute("DELETE FROM reports WHERE id = $1", report_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Bericht nicht gefunden")
    return {"ok": True}


async def _reports_list_response(
    request: Request, pool, error: str | None = None, created_report_id: int | None = None,
):
    rows = await pool.fetch(f"{_REPORT_SUMMARY_SELECT} ORDER BY r.created_at DESC")
    reports = []
    for r in rows:
        summary = _report_summary_row(r)
        summary["created_at_display"] = _fmt_dt_de(r["created_at"])
        summary["total_cost_display"] = _fmt_cost(summary["total_cost"])
        reports.append(summary)
    return templates.TemplateResponse(
        "hx/report_review/reports.html",
        {
            "request": request,
            "reports": reports,
            "error": error,
            "created_report_id": created_report_id,
        },
    )


@router.get("/hx/reports", response_class=HTMLResponse)
async def hx_reports(request: Request):
    return await _reports_list_response(request, get_pool())


@router.delete("/hx/reports/{report_id}", response_class=HTMLResponse)
async def hx_delete_report(request: Request, report_id: int):
    pool = get_pool()
    await pool.execute("DELETE FROM reports WHERE id = $1", report_id)
    return await _reports_list_response(request, pool)


@router.post("/hx/reports", response_class=HTMLResponse)
async def hx_create_report(request: Request):
    pool = get_pool()
    form = await request.form()
    checked_ids, overrides = _parse_review_selection(form)
    if not checked_ids:
        return await _reports_list_response(request, pool, error="Keine Ladevorgänge ausgewählt")
    title = form.get("title", "").strip()
    if not title:
        return await _reports_list_response(request, pool, error="Bitte einen Titel eingeben")
    price_overrides: dict = {}
    for sid in checked_ids:
        override = overrides.get(sid, "auto")
        if override == "openwb":
            price_overrides[sid] = "openwb"
        elif override != "auto":
            price_overrides[sid] = int(override)
    cost_basis = form.get("cost_basis") or None
    try:
        report = await _generate_report(pool, title, checked_ids, None, price_overrides, cost_basis)
    except ReportBuildError as exc:
        return await _reports_list_response(request, pool, error=str(exc))
    return await _reports_list_response(request, pool, created_report_id=report["id"])


@router.get("/api/update/version")
def api_update_version():
    return {"current_commit": get_current_version(), "available": self_update_available()}


@router.get("/api/update/check")
def api_update_check():
    return check_for_update()


@router.post("/api/update")
def api_update(background_tasks: BackgroundTasks):
    return run_update(background_tasks)


def _update_panel_context(request: Request, *, state: str = "idle", msg: str | None = None) -> dict:
    return {
        "request": request,
        "state": state,
        "current_commit": get_current_version(),
        "available": self_update_available(),
        "msg": msg,
    }


@router.get("/hx/update", response_class=HTMLResponse)
def hx_update(request: Request):
    return templates.TemplateResponse("hx/update/panel.html", _update_panel_context(request))


@router.post("/hx/update/check", response_class=HTMLResponse)
def hx_update_check(request: Request):
    data = check_for_update()
    if data["error"]:
        msg = "Prüfung fehlgeschlagen: " + data["error"]
    elif data["update_available"]:
        msg = f"Update verfügbar ({data['current']} → {data['latest']})"
    else:
        msg = f"Aktuell ({data['current']})"
    return templates.TemplateResponse(
        "hx/_msg.html", {"request": request, "msg": msg},
    )


@router.post("/hx/update/run", response_class=HTMLResponse)
def hx_update_run(request: Request, background_tasks: BackgroundTasks):
    result = run_update(background_tasks)
    if not result["ok"]:
        ctx = _update_panel_context(request, msg="Update fehlgeschlagen: " + result["message"])
    elif result["restarting"]:
        ctx = _update_panel_context(request, state="restarting", msg="Startet neu...")
    else:
        ctx = _update_panel_context(request, msg=result["message"])
    return templates.TemplateResponse("hx/update/panel.html", ctx)


@router.get("/hx/update/ping", response_class=HTMLResponse)
def hx_update_ping(request: Request):
    """Only reachable once the restarted process is actually back up --
    the response body itself is what tells the browser to reload."""
    return templates.TemplateResponse("hx/update/ping.html", {"request": request})
