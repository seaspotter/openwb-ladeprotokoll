"""FastAPI routes: source CRUD, fetch triggers, session listing, price
entry CRUD, and report preview/generate/list/pdf. All reads/writes are
plain parameterized SQL via asyncpg -- no ORM."""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from .db import get_pool
from .fetch_service import current_month, fetch_service, month_range
from .pdf_render import ReportMeta, render_html, render_pdf
from .price_entries import PriceEntry, decide_price, match_and_decide
from .report_build import COLUMN_LABELS, ReportBuildError
from .report_build import build as build_report_data
from .report_settings import ReportSettingsError
from .report_settings import get_settings as get_report_settings
from .report_settings import update_settings as update_report_settings
from .sources import SourceValidationError, normalize_base_url, validate_name
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


class ReportGenerateIn(ReportBuildIn):
    title: str


class VehicleIn(BaseModel):
    license_plate: str | None = None


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
    rows = await pool.fetch("SELECT * FROM price_entries ORDER BY created_at DESC")
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


@router.get("/api/sessions")
async def api_sessions(
    source_id: int | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: date | None = None,
    to: date | None = None,
):
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

    pool = get_pool()
    rows = await pool.fetch(
        f"SELECT * FROM sessions {where} ORDER BY time_begin DESC", *params
    )
    # Loaded once per request, not per session -- price_entries is a small
    # table (a handful of rows per fleet/tariff), so this stays cheap even
    # for a large session list.
    price_rows = await pool.fetch("SELECT * FROM price_entries")
    entries = [_price_entry_for_matching(r) for r in price_rows]

    sessions = []
    for r in rows:
        d = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()
             if k != "raw_json"}
        energy_kwh = float(r["energy_kwh"]) if r["energy_kwh"] is not None else None
        cost_openwb = float(r["cost_openwb"]) if r["cost_openwb"] is not None else None
        decision = match_and_decide(
            entries,
            source_id=r["source_id"],
            vehicle_name=r["vehicle_name"],
            session_date=r["time_begin"].date(),
            energy_kwh=energy_kwh,
            cost_openwb=cost_openwb,
        )
        d["price_entry_id"] = decision.price_entry["id"] if decision.price_entry else None
        d["price_provider"] = decision.price_entry["provider"] if decision.price_entry else None
        d["cost_corrected"] = decision.cost_corrected
        d["cost_used"] = decision.cost_used
        d["cost_delta"] = decision.delta
        d["cost_delta_flagged"] = decision.delta_flagged
        sessions.append(d)
    return {"sessions": sessions}


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


async def _report_meta(
    pool, report_id: str, title: str, generated_at: datetime, rows, settings: dict
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
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").strip() or "ladeprotokoll.pdf"
    return f'inline; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'


_REPORT_SUMMARY_SELECT = (
    "SELECT r.id, r.created_at, r.title, r.column_selection, r.total_duration_seconds, "
    "r.total_energy_kwh, r.total_energy_discharged_kwh, r.total_range_charged_km, "
    "r.total_cost_openwb, r.total_cost_corrected, "
    "(SELECT count(*) FROM report_sessions rs WHERE rs.report_id = r.id) AS session_count "
    "FROM reports r"
)


def _report_summary_row(r) -> dict:
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
        "session_count": r["session_count"],
    }


@router.post("/api/reports/preview", response_class=HTMLResponse)
async def api_report_preview(body: ReportBuildIn):
    """Runs the same build as api_create_report below, but renders straight
    to HTML and persists nothing -- for the review UI's live preview."""
    pool = get_pool()
    settings = await get_report_settings(pool)
    sessions, rows = await _load_report_sessions(pool, body.session_ids, body.price_overrides)
    try:
        data = build_report_data(
            sessions, body.columns or settings["default_columns"], settings["cost_basis"]
        )
    except ReportBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    meta = await _report_meta(pool, "Vorschau", "Vorschau", datetime.now(), rows, settings)
    return render_html(data, meta)


@router.post("/api/reports")
async def api_create_report(body: ReportGenerateIn):
    """Reports are immutable once created -- "regenerate" always inserts a
    new row rather than updating an existing one. Insert happens in two
    steps because the PDF's own header/footer displays the report's id,
    which only exists once the row is inserted."""
    pool = get_pool()
    settings = await get_report_settings(pool)
    sessions, rows = await _load_report_sessions(pool, body.session_ids, body.price_overrides)
    try:
        data = build_report_data(
            sessions, body.columns or settings["default_columns"], settings["cost_basis"]
        )
    except ReportBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    async with pool.acquire() as conn:
        async with conn.transaction():
            report_row = await conn.fetchrow(
                "INSERT INTO reports (title, column_selection, total_duration_seconds, "
                "total_energy_kwh, total_energy_discharged_kwh, total_range_charged_km, "
                "total_cost_openwb, total_cost_corrected, pdf_data) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id, created_at",
                body.title, data.columns, data.totals.duration_seconds,
                data.totals.energy_kwh, data.totals.energy_discharged_kwh,
                data.totals.range_charged_km, data.totals.cost_openwb,
                data.totals.cost_corrected, b"",
            )
            report_id = report_row["id"]

            meta = await _report_meta(
                pool, str(report_id), body.title, report_row["created_at"], rows, settings
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


@router.get("/api/update/version")
def api_update_version():
    return {"current_commit": get_current_version(), "available": self_update_available()}


@router.get("/api/update/check")
def api_update_check():
    return check_for_update()


@router.post("/api/update")
def api_update(background_tasks: BackgroundTasks):
    return run_update(background_tasks)
