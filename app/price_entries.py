"""Electricity price correction: match a price entry to a session and
compute the corrected cost from kWh x price/kWh.

Pure module -- no DB, no HTTP. web.py loads `price_entries` rows and hands
them here; report_build.py (once it exists) will do the same for report
generation, with a per-row override replacing the auto-match when the user
picks one in the review UI.

A price entry is scoped per source (optional) and per vehicle name
(optional) -- both nullable as wildcards, covering a single-car setup
(everything wildcarded) and a fleet with different tariffs per person or
site (source and/or vehicle pinned).

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
    # Same price entry, but priced against only the grid-imported share of
    # energy_kwh (session's own power_source_grid_pct) instead of the full
    # amount -- for a reimbursement/accounting scenario where self-generated
    # PV/battery energy shouldn't count at the same €/kWh as grid draw.
    # Always computed alongside the total-energy figures above, not behind
    # a flag -- see decide_price's grid_pct docstring for the missing-data
    # fallback.
    cost_corrected_grid_only: float | None
    cost_used_grid_only: float | None
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


def corrected_cost(energy_kwh: float | None, price_per_kwh: float) -> float | None:
    if energy_kwh is None:
        return None
    return energy_kwh * price_per_kwh


def decide_price(
    *,
    energy_kwh: float | None,
    cost_openwb: float | None,
    price_entry: PriceEntry | None,
    grid_pct: float | None = None,
) -> PriceDecision:
    """Combines an (already matched or user-overridden) price entry with a
    session's own energy/cost figures into the decision the review UI and
    report_build.py need: the corrected cost (or None if no entry
    applies), which cost to actually use on the report (corrected, falling
    back to openWB's own when there's no entry), and whether the two
    diverge enough to flag.

    `grid_pct` is the session's own power_source_grid_pct (0-100, the
    share of this session's energy that came from the grid rather than
    PV/battery/the chargepoint's own buffer) -- used to compute the
    grid-only variant. Missing data (`grid_pct is None`, e.g. an older
    record) is treated as 100% grid rather than silently undercounting
    the correction."""
    cost_corrected = (
        corrected_cost(energy_kwh, price_entry["price_per_kwh"]) if price_entry else None
    )
    cost_used = cost_corrected if cost_corrected is not None else cost_openwb

    grid_share = (grid_pct if grid_pct is not None else 100.0) / 100.0
    grid_energy_kwh = energy_kwh * grid_share if energy_kwh is not None else None
    cost_corrected_grid_only = (
        corrected_cost(grid_energy_kwh, price_entry["price_per_kwh"]) if price_entry else None
    )
    cost_used_grid_only = (
        cost_corrected_grid_only if cost_corrected_grid_only is not None else cost_openwb
    )

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
        cost_corrected_grid_only=cost_corrected_grid_only,
        cost_used_grid_only=cost_used_grid_only,
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
    grid_pct: float | None = None,
) -> PriceDecision:
    """Convenience wrapper for the common (no manual override) case: match,
    then decide."""
    entry = match_price_entry(
        entries, source_id=source_id, vehicle_name=vehicle_name, session_date=session_date
    )
    return decide_price(
        energy_kwh=energy_kwh, cost_openwb=cost_openwb, price_entry=entry, grid_pct=grid_pct
    )
