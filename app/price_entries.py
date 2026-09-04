"""Electricity price correction: match a price entry to a session and
compute the corrected cost from a session's actual energy mix, not one
flat rate over its total kWh.

Pure module -- no DB, no HTTP. web.py loads `price_entries` rows and hands
them here; report_build.py does the same for report generation, with a
per-row override replacing the auto-match when the user picks one in the
review UI.

A price entry is scoped per source (optional) and per vehicle name
(optional) -- both nullable as wildcards, covering a single-car setup
(everything wildcarded) and a fleet with different tariffs per person or
site (source and/or vehicle pinned). It only ever prices a session's
grid-sourced share, though -- see `corrected_cost` below for why the
PV-/battery-sourced share needs its own two rates.

Corrected cost always uses `energy_kwh` (the session's own per-row
"Energie" figure -- see chargelog_parse.py), never
`energy_since_plugged_kwh` (cumulative since plug-in): summing or pricing
the cumulative figure across a multi-segment session would overstate cost
the same way it would overstate energy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TypedDict

# abs(cost_corrected - cost_openwb) above this is flagged in the review UI
# as a meaningful divergence, not just floating-point/rounding noise.
DELTA_FLAG_THRESHOLD = 0.01


class PriceEntry(TypedDict):
    id: int
    source_id: int | None
    vehicle_name: str | None
    provider: str
    price_per_kwh: float
    valid_from: date
    valid_to: date | None
    notes: str | None
    created_at: datetime


@dataclass
class PriceDecision:
    price_entry: PriceEntry | None
    cost_openwb: float | None
    cost_corrected: float | None
    cost_used: float | None
    delta: float | None
    delta_flagged: bool


def _specificity(entry: PriceEntry) -> int:
    """Ranks a match: source+vehicle (3) > source-only (2) > vehicle-only
    (1) > wildcard (0). A pinned source or vehicle is worth one point each,
    so both pinned always outranks either alone, and either alone always
    outranks neither."""
    return (2 if entry["source_id"] is not None else 0) + (
        1 if entry["vehicle_name"] is not None else 0
    )


def _matches(
    entry: PriceEntry, *, source_id: int, vehicle_name: str | None, session_date: date
) -> bool:
    if entry["source_id"] is not None and entry["source_id"] != source_id:
        return False
    if entry["vehicle_name"] is not None and entry["vehicle_name"] != vehicle_name:
        return False
    if entry["valid_from"] > session_date:
        return False
    if entry["valid_to"] is not None and entry["valid_to"] < session_date:
        return False
    return True


def match_price_entry(
    entries: list[PriceEntry],
    *,
    source_id: int,
    vehicle_name: str | None,
    session_date: date,
) -> PriceEntry | None:
    """Picks the single best-matching entry for a session, or None if
    nothing applies -- the caller (decide_price, or the review UI showing
    a per-row override dropdown) is responsible for the "kein Preis
    hinterlegt" fallback to openWB's own cost."""
    candidates = [
        e
        for e in entries
        if _matches(e, source_id=source_id, vehicle_name=vehicle_name, session_date=session_date)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (_specificity(e), e["created_at"]))


def corrected_cost(
    *,
    energy_kwh: float | None,
    price_per_kwh: float,
    power_source_grid_pct: float | None = None,
    power_source_pv_pct: float | None = None,
    power_source_bat_pct: float | None = None,
    power_source_cp_pct: float | None = None,
    pv_price_per_kwh: float = 0.0,
    bat_price_per_kwh: float = 0.0,
) -> float | None:
    """Prices a session's actual energy mix rather than one flat rate over
    the whole session: the grid-sourced share uses `price_per_kwh` (the
    matched/overridden price_entries row's own rate -- a utility tariff
    only ever applies to energy actually drawn from the grid), the
    PV-sourced share uses `pv_price_per_kwh`, and the battery-sourced share
    uses `bat_price_per_kwh` -- both global rates from report_settings,
    since self-produced/stored energy isn't covered by any grid tariff and
    doesn't vary by source/vehicle/date the way price_entries does. The
    chargepoint's own share (power_source.cp -- rare, effectively always 0
    in every real record seen so far, see chargelog_parse.py) is folded
    into the battery rate: it represents energy from local storage rather
    than the grid, same as power_source.bat.

    When every power_source_*_pct is None (a session predating this
    feature, or a data source that never populates the split), the whole
    session is treated as 100% grid -- the same flat-rate behavior this
    function had before the split existed, and the safest assumption when
    the actual mix is unknown (it doesn't invent a PV/battery discount
    that may not have applied)."""
    if energy_kwh is None:
        return None
    grid_pct = power_source_grid_pct if power_source_grid_pct is not None else 100.0
    pv_pct = power_source_pv_pct or 0.0
    bat_pct = (power_source_bat_pct or 0.0) + (power_source_cp_pct or 0.0)
    return energy_kwh * (
        (grid_pct / 100) * price_per_kwh
        + (pv_pct / 100) * pv_price_per_kwh
        + (bat_pct / 100) * bat_price_per_kwh
    )


def decide_price(
    *,
    energy_kwh: float | None,
    cost_openwb: float | None,
    price_entry: PriceEntry | None,
    power_source_grid_pct: float | None = None,
    power_source_pv_pct: float | None = None,
    power_source_bat_pct: float | None = None,
    power_source_cp_pct: float | None = None,
    pv_price_per_kwh: float = 0.0,
    bat_price_per_kwh: float = 0.0,
) -> PriceDecision:
    """Combines an (already matched or user-overridden) price entry with a
    session's own energy/cost figures into the decision the review UI and
    report_build.py need: the corrected cost (or None if no entry
    applies -- the grid rate is still needed even for a mixed session, so
    no entry means no correction at all, same as before this function
    started splitting by source), which cost to actually use on the report
    (corrected, falling back to openWB's own when there's no entry), and
    whether the two diverge enough to flag."""
    cost_corrected = (
        corrected_cost(
            energy_kwh=energy_kwh,
            price_per_kwh=price_entry["price_per_kwh"],
            power_source_grid_pct=power_source_grid_pct,
            power_source_pv_pct=power_source_pv_pct,
            power_source_bat_pct=power_source_bat_pct,
            power_source_cp_pct=power_source_cp_pct,
            pv_price_per_kwh=pv_price_per_kwh,
            bat_price_per_kwh=bat_price_per_kwh,
        )
        if price_entry else None
    )
    cost_used = cost_corrected if cost_corrected is not None else cost_openwb
    delta = (
        cost_corrected - cost_openwb
        if cost_corrected is not None and cost_openwb is not None
        else None
    )
    delta_flagged = delta is not None and abs(delta) > DELTA_FLAG_THRESHOLD
    return PriceDecision(
        price_entry=price_entry,
        cost_openwb=cost_openwb,
        cost_corrected=cost_corrected,
        cost_used=cost_used,
        delta=delta,
        delta_flagged=delta_flagged,
    )


def match_and_decide(
    entries: list[PriceEntry],
    *,
    source_id: int,
    vehicle_name: str | None,
    session_date: date,
    energy_kwh: float | None,
    cost_openwb: float | None,
    power_source_grid_pct: float | None = None,
    power_source_pv_pct: float | None = None,
    power_source_bat_pct: float | None = None,
    power_source_cp_pct: float | None = None,
    pv_price_per_kwh: float = 0.0,
    bat_price_per_kwh: float = 0.0,
) -> PriceDecision:
    """Convenience wrapper for the common (no manual override) case: match,
    then decide."""
    entry = match_price_entry(
        entries, source_id=source_id, vehicle_name=vehicle_name, session_date=session_date
    )
    return decide_price(
        energy_kwh=energy_kwh,
        cost_openwb=cost_openwb,
        price_entry=entry,
        power_source_grid_pct=power_source_grid_pct,
        power_source_pv_pct=power_source_pv_pct,
        power_source_bat_pct=power_source_bat_pct,
        power_source_cp_pct=power_source_cp_pct,
        pv_price_per_kwh=pv_price_per_kwh,
        bat_price_per_kwh=bat_price_per_kwh,
    )
