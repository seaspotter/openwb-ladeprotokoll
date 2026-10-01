"""Electricity price correction: match a price entry to a session and
compute the corrected cost from its actual energy mix, not one flat rate.

Pure module -- no DB, no HTTP. web.py and report_build.py both call in
here with a session's own data plus a matched (or user-overridden) entry.
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
class CostBreakdown:
    grid: float
    pv: float
    bat: float

    @property
    def total(self) -> float:
        return self.grid + self.pv + self.bat


@dataclass
class PriceDecision:
    price_entry: PriceEntry | None
    cost_openwb: float | None
    cost_corrected: float | None
    cost_used: float | None
    delta: float | None
    delta_flagged: bool
    cost_breakdown: CostBreakdown | None = None


def _specificity(entry: PriceEntry) -> int:
    """source+vehicle (3) > source-only (2) > vehicle-only (1) > wildcard (0)."""
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
    return not (entry["valid_to"] is not None and entry["valid_to"] < session_date)


def match_price_entry(
    entries: list[PriceEntry],
    *,
    source_id: int,
    vehicle_name: str | None,
    session_date: date,
) -> PriceEntry | None:
    """Best-matching entry for a session, or None -- the caller handles the
    "kein Preis hinterlegt" fallback to openWB's own cost."""
    candidates = [
        e
        for e in entries
        if _matches(e, source_id=source_id, vehicle_name=vehicle_name, session_date=session_date)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda e: (_specificity(e), e["created_at"]))


def corrected_cost_breakdown(
    *,
    energy_kwh: float | None,
    price_per_kwh: float,
    power_source_grid_pct: float | None = None,
    power_source_pv_pct: float | None = None,
    power_source_bat_pct: float | None = None,
    power_source_cp_pct: float | None = None,
    pv_price_per_kwh: float = 0.0,
    bat_price_per_kwh: float = 0.0,
) -> CostBreakdown | None:
    """Prices a session's actual grid/PV/battery energy mix instead of one
    flat rate over the total: `price_per_kwh` (the matched price_entries
    rate) only ever prices the grid share; PV/battery each get their own
    global rate from report_settings, since self-produced energy isn't
    covered by a grid tariff. Chargepoint share (power_source.cp, rare) is
    folded into the battery bucket -- it's local storage, not a grid draw.

    power_source_*_pct all None (older session, or a source that never
    populates the split) defaults to 100% grid, the same flat-rate result
    this had before the split existed -- never invents a PV/battery
    discount that may not have applied."""
    if energy_kwh is None:
        return None
    grid_pct = power_source_grid_pct if power_source_grid_pct is not None else 100.0
    pv_pct = power_source_pv_pct or 0.0
    bat_pct = (power_source_bat_pct or 0.0) + (power_source_cp_pct or 0.0)
    return CostBreakdown(
        grid=energy_kwh * (grid_pct / 100) * price_per_kwh,
        pv=energy_kwh * (pv_pct / 100) * pv_price_per_kwh,
        bat=energy_kwh * (bat_pct / 100) * bat_price_per_kwh,
    )


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
    """`corrected_cost_breakdown`'s total -- see that function for the logic."""
    breakdown = corrected_cost_breakdown(
        energy_kwh=energy_kwh,
        price_per_kwh=price_per_kwh,
        power_source_grid_pct=power_source_grid_pct,
        power_source_pv_pct=power_source_pv_pct,
        power_source_bat_pct=power_source_bat_pct,
        power_source_cp_pct=power_source_cp_pct,
        pv_price_per_kwh=pv_price_per_kwh,
        bat_price_per_kwh=bat_price_per_kwh,
    )
    return breakdown.total if breakdown is not None else None


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
    """A matched (or overridden) entry + a session's own energy/cost -> the
    corrected cost (None if no entry applies), which cost to actually use
    (falls back to openWB's own), and whether the two diverge enough to
    flag. `cost_breakdown` is computed once here and reused by callers that
    need the per-source split (e.g. statistics.py's Kosten chart), instead
    of recomputing it."""
    cost_breakdown = (
        corrected_cost_breakdown(
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
    cost_corrected = cost_breakdown.total if cost_breakdown is not None else None
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
        cost_breakdown=cost_breakdown,
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
    """Match, then decide -- the common no-override case."""
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
