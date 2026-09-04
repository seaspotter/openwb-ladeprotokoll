"""Pure: sessions + selected columns + price decisions -> the rows/totals
structure the PDF/HTML template (pdf_render.py) renders, and that gets
frozen into `report_sessions.snapshot` for the audit trail.

Doesn't touch the DB or render anything -- callers (web.py's report
routes) load sessions and resolve each one's price decision (auto-matched
via price_entries.match_and_decide, or a user override), then hand this
module plain dicts. That keeps exactly one place deciding what a report
total means and how a session row displays, used identically by the
preview endpoint (nothing persisted) and the generate endpoint (the same
build feeds both the stored snapshot and the rendered PDF).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

# Ordered so the rendered table's column order is always this one,
# regardless of what order the caller's `columns` list arrives in (e.g. a
# JS Set or a hand-built request body). "cost" is a single column whose
# *value* depends on the cost_basis passed to build() -- report_settings.py
# owns the openWB-vs-corrected choice; this module just renders whichever
# one it's told, never both at once (per user feedback: showing both
# "Kosten (openWB)" and "Kosten (korrigiert)" side by side was confusing).
COLUMN_LABELS: dict[str, str] = {
    "begin": "Beginn",
    "end": "Ende",
    "duration": "Dauer",
    "vehicle": "Fahrzeug",
    "odometer": "Kilometerstand",
    "chargepoint": "Ladepunkt",
    "serial_number": "Seriennummer",
    "energy": "Energie",
    "range_charged": "Reichweite",
    "meter_start": "Zähler Beginn",
    "meter_end": "Zähler Ende",
    "cost": "Kosten",
    "price_basis": "Preisbasis",
}

DEFAULT_COLUMNS: list[str] = list(COLUMN_LABELS)

COST_BASES = ("openwb", "corrected")


class ReportBuildError(ValueError):
    pass


@dataclass
class SessionRow:
    session_id: int
    cells: dict[str, str]  # column key -> formatted display string, for the selected columns only
    cost_openwb: float | None
    cost_corrected: float | None
    cost_used: float | None
    cost: float | None  # whichever of the above matches this build's cost_basis
    energy_kwh: float | None
    energy_discharged_kwh: float | None
    range_charged_km: float | None
    time_charged_seconds: int | None
    price_entry: dict | None  # {id, provider, price_per_kwh, valid_from, valid_to, ...} or None
    delta_flagged: bool


@dataclass
class PriceBasisEntry:
    provider: str
    price_per_kwh: float
    valid_from: str
    valid_to: str | None
    session_count: int


@dataclass
class ReportTotals:
    duration_seconds: int
    energy_kwh: float
    energy_discharged_kwh: float
    range_charged_km: float
    # Both raw totals are always computed and stored (audit trail, and the
    # `reports` table's own NOT NULL columns) even though only one of them
    # -- `cost`/`cost_display`, matching this build's cost_basis -- is what
    # the template actually prints.
    cost_openwb: float
    cost_corrected: float
    cost: float
    duration_display: str
    energy_display: str
    energy_discharged_display: str
    range_display: str
    cost_openwb_display: str
    cost_corrected_display: str
    cost_display: str


@dataclass
class ReportData:
    columns: list[str]
    column_labels: list[str]
    rows: list[SessionRow]
    totals: ReportTotals
    price_basis: list[PriceBasisEntry]


def _fmt_datetime(dt: datetime | None) -> str:
    return dt.strftime("%d.%m.%Y %H:%M") if dt else "–"


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else "–"


def _fmt_duration(seconds: int | None) -> str:
    """"H:MM" -- matches openWB's own Ladeprotokoll "Dauer" display, see
    chargelog_parse.py."""
    if seconds is None:
        return "–"
    hours, remainder = divmod(int(seconds), 3600)
    minutes = remainder // 60
    return f"{hours}:{minutes:02d}"


def _fmt_number(value: float | None, decimals: int, suffix: str = "") -> str:
    if value is None:
        return "–"
    # German decimal comma, matching the openWB UI and the target
    # accounting document's locale.
    return f"{value:.{decimals}f}{suffix}".replace(".", ",")


def _fmt_cost(value: float | None) -> str:
    if value is None:
        return "–"
    return _fmt_number(value, 2, " €")


def _validate_columns(columns: list[str] | None) -> list[str]:
    if columns is None:
        return list(DEFAULT_COLUMNS)
    if not columns:
        raise ReportBuildError("Mindestens eine Spalte muss ausgewählt sein")
    unknown = [c for c in columns if c not in COLUMN_LABELS]
    if unknown:
        raise ReportBuildError(f"Unbekannte Spalte(n): {unknown}")
    return [c for c in DEFAULT_COLUMNS if c in columns]


def _resolve_cost(session: dict, cost_basis: str) -> float | None:
    if cost_basis == "openwb":
        return session.get("cost_openwb")
    # "corrected": cost_used already carries decide_price's own fallback to
    # openWB's value when no price entry applies, so this is always a
    # complete figure, never silently blank for an unpriced session.
    return session.get("cost_used")


def _build_cells(session: dict, columns: list[str], cost: float | None) -> dict[str, str]:
    price_entry = session.get("price_entry")
    values = {
        "begin": _fmt_datetime(session.get("time_begin")),
        "end": _fmt_datetime(session.get("time_end")),
        "duration": _fmt_duration(session.get("time_charged_seconds")),
        "vehicle": session.get("vehicle_name") or "–",
        "odometer": _fmt_number(session.get("odometer"), 0, " km"),
        "chargepoint": session.get("chargepoint_name") or "–",
        "serial_number": session.get("chargepoint_serial_number") or "–",
        "energy": _fmt_number(session.get("energy_kwh"), 2, " kWh"),
        "range_charged": _fmt_number(session.get("range_charged_km"), 0, " km"),
        "meter_start": _fmt_number(session.get("meter_start_kwh"), 2, " kWh"),
        "meter_end": _fmt_number(session.get("meter_end_kwh"), 2, " kWh"),
        "cost": _fmt_cost(cost),
        "price_basis": price_entry["provider"] if price_entry else "kein Preis hinterlegt",
    }
    return {c: values[c] for c in columns}


def build(
    sessions: list[dict], columns: list[str] | None = None, cost_basis: str = "corrected"
) -> ReportData:
    """`sessions` is a list of dicts, each already carrying a session's own
    fields (id, time_begin, time_end, time_charged_seconds, vehicle_name,
    odometer, chargepoint_name, chargepoint_serial_number, energy_kwh,
    energy_discharged_kwh, range_charged_km, meter_start_kwh,
    meter_end_kwh, cost_openwb) plus its resolved price decision
    (cost_corrected, cost_used, price_entry -- as produced by
    price_entries.decide_price, price_entry being a PriceEntry dict or
    None).

    Rows are always sorted chronologically ascending (oldest first,
    latest at the bottom) regardless of the order `sessions` arrives in --
    a printed ledger reads that way, unlike the review UI's session list
    (newest first, better for "did today's fetch show up").
    """
    if cost_basis not in COST_BASES:
        raise ReportBuildError(f"Unbekannte cost_basis: {cost_basis!r}")
    cols = _validate_columns(columns)
    sessions = sorted(sessions, key=lambda s: s["time_begin"])

    rows: list[SessionRow] = []
    price_basis_by_key: dict[tuple, PriceBasisEntry] = {}

    total_duration = 0
    total_energy = 0.0
    total_energy_discharged = 0.0
    total_range = 0.0
    total_cost_openwb = 0.0
    total_cost_corrected = 0.0

    for s in sessions:
        price_entry = s.get("price_entry")
        if price_entry:
            key = (price_entry["provider"], price_entry["price_per_kwh"],
                   price_entry["valid_from"], price_entry["valid_to"])
            entry = price_basis_by_key.get(key)
            if entry is None:
                valid_to = price_entry["valid_to"]
                entry = PriceBasisEntry(
                    provider=price_entry["provider"],
                    price_per_kwh=price_entry["price_per_kwh"],
                    valid_from=_fmt_date(price_entry["valid_from"]),
                    valid_to=_fmt_date(valid_to) if valid_to else None,
                    session_count=0,
                )
                price_basis_by_key[key] = entry
            entry.session_count += 1

        cost = _resolve_cost(s, cost_basis)
        rows.append(SessionRow(
            session_id=s["id"],
            cells=_build_cells(s, cols, cost),
            cost_openwb=s.get("cost_openwb"),
            cost_corrected=s.get("cost_corrected"),
            cost_used=s.get("cost_used"),
            cost=cost,
            energy_kwh=s.get("energy_kwh"),
            energy_discharged_kwh=s.get("energy_discharged_kwh"),
            range_charged_km=s.get("range_charged_km"),
            time_charged_seconds=s.get("time_charged_seconds"),
            price_entry=price_entry,
            delta_flagged=bool(s.get("delta_flagged")),
        ))

        total_duration += s.get("time_charged_seconds") or 0
        total_energy += s.get("energy_kwh") or 0.0
        total_energy_discharged += s.get("energy_discharged_kwh") or 0.0
        total_range += s.get("range_charged_km") or 0.0
        total_cost_openwb += s.get("cost_openwb") or 0.0
        # cost_used already carries decide_price's own fallback (corrected,
        # or openWB's own value when no price entry applies) -- summing it
        # keeps this total always complete and comparable to
        # total_cost_openwb, rather than silently excluding unpriced rows.
        total_cost_corrected += s.get("cost_used") or 0.0

    total_cost = total_cost_openwb if cost_basis == "openwb" else total_cost_corrected

    totals = ReportTotals(
        duration_seconds=total_duration,
        energy_kwh=total_energy,
        energy_discharged_kwh=total_energy_discharged,
        range_charged_km=total_range,
        cost_openwb=total_cost_openwb,
        cost_corrected=total_cost_corrected,
        cost=total_cost,
        duration_display=_fmt_duration(total_duration),
        energy_display=_fmt_number(total_energy, 2, " kWh"),
        energy_discharged_display=_fmt_number(total_energy_discharged, 2, " kWh"),
        range_display=_fmt_number(total_range, 0, " km"),
        cost_openwb_display=_fmt_cost(total_cost_openwb),
        cost_corrected_display=_fmt_cost(total_cost_corrected),
        cost_display=_fmt_cost(total_cost),
    )

    return ReportData(
        columns=cols,
        column_labels=[COLUMN_LABELS[c] for c in cols],
        rows=rows,
        totals=totals,
        price_basis=sorted(price_basis_by_key.values(), key=lambda p: p.provider),
    )
