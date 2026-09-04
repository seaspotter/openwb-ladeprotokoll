"""Pure: sessions (already enriched with a price decision, exactly the
shape web.py's _query_sessions returns) -> aggregated statistics for the
/statistik page -- either per-period (month/year, aggregate()) or
per-vehicle (aggregate_by_vehicle()).

The energy-source split (grid/PV/battery/chargepoint) is computed as
absolute kWh per bucket, not an averaged percentage -- averaging each
session's power_source_*_pct directly would misrepresent the actual
energy mix once sessions of very different sizes are mixed (a 2 kWh
top-up at 100% grid and a 40 kWh mostly-PV session shouldn't count
equally toward "average PV share"). Each session's own energy_kwh *
power_source_pv_pct/100 (etc.) is summed instead, matching how
report_build.py already treats energy_kwh as the one figure worth
summing across sessions -- see chargelog_parse.py's docstring for why.

The "cost" figure follows the same one-cost-column simplification
report_build.py uses (cost_basis="openwb"|"corrected", never both side by
side): callers pass sessions already carrying cost_openwb/cost_used from
_query_sessions, and both aggregate functions pick whichever cost_basis
says.
"""
from __future__ import annotations

from dataclasses import dataclass

GRANULARITIES = ("month", "year")
COST_BASES = ("openwb", "corrected")


class StatisticsError(ValueError):
    pass


@dataclass
class PeriodStats:
    period: str  # "2026-08" for month, "2026" for year
    session_count: int
    energy_kwh: float
    cost: float
    energy_grid_kwh: float
    energy_pv_kwh: float
    energy_bat_kwh: float
    energy_cp_kwh: float


@dataclass
class VehicleStats:
    vehicle_name: str
    session_count: int
    energy_kwh: float
    cost: float
    energy_grid_kwh: float
    energy_pv_kwh: float
    energy_bat_kwh: float
    energy_cp_kwh: float


def _period_key(time_begin: str, granularity: str) -> str:
    # time_begin is an ISO string ("2026-08-01T10:00:00+00:00", as
    # _query_sessions already formats it) -- a plain slice is enough for
    # both granularities without parsing a datetime.
    return time_begin[:4] if granularity == "year" else time_begin[:7]


def _resolve_cost(session: dict, cost_basis: str) -> float:
    if cost_basis == "openwb":
        return session.get("cost_openwb") or 0.0
    return session.get("cost_used") or 0.0


def _empty_bucket() -> dict:
    return {
        "session_count": 0, "energy_kwh": 0.0, "cost": 0.0,
        "energy_grid_kwh": 0.0, "energy_pv_kwh": 0.0,
        "energy_bat_kwh": 0.0, "energy_cp_kwh": 0.0,
    }


def _accumulate(bucket: dict, session: dict, cost_basis: str) -> None:
    energy = session.get("energy_kwh") or 0.0
    bucket["session_count"] += 1
    bucket["energy_kwh"] += energy
    bucket["cost"] += _resolve_cost(session, cost_basis)
    for pct_key, energy_key in (
        ("power_source_grid_pct", "energy_grid_kwh"),
        ("power_source_pv_pct", "energy_pv_kwh"),
        ("power_source_bat_pct", "energy_bat_kwh"),
        ("power_source_cp_pct", "energy_cp_kwh"),
    ):
        pct = session.get(pct_key)
        if pct is not None:
            bucket[energy_key] += energy * float(pct) / 100.0


def aggregate(
    sessions: list[dict], granularity: str = "month", cost_basis: str = "corrected"
) -> list[PeriodStats]:
    if granularity not in GRANULARITIES:
        raise StatisticsError(f"Unbekannte Granularität: {granularity!r}")
    if cost_basis not in COST_BASES:
        raise StatisticsError(f"Unbekannte cost_basis: {cost_basis!r}")

    buckets: dict[str, dict] = {}
    for s in sessions:
        if not s.get("time_begin"):
            continue
        key = _period_key(s["time_begin"], granularity)
        _accumulate(buckets.setdefault(key, _empty_bucket()), s, cost_basis)

    return [PeriodStats(period=key, **vals) for key, vals in sorted(buckets.items())]


def aggregate_by_vehicle(
    sessions: list[dict], cost_basis: str = "corrected"
) -> list[VehicleStats]:
    """Same accumulation as aggregate(), grouped by vehicle_name instead
    of time period -- for comparing vehicles against each other rather
    than a single vehicle/fleet over time. Sessions with no vehicle_name
    (shouldn't normally happen, but chargelog_parse.py doesn't guarantee
    one) are grouped under "Unbekannt" rather than silently dropped."""
    if cost_basis not in COST_BASES:
        raise StatisticsError(f"Unbekannte cost_basis: {cost_basis!r}")

    buckets: dict[str, dict] = {}
    for s in sessions:
        name = s.get("vehicle_name") or "Unbekannt"
        _accumulate(buckets.setdefault(name, _empty_bucket()), s, cost_basis)

    # Sorted by energy descending -- the vehicle that charged the most is
    # the one worth seeing first, not alphabetical.
    return [
        VehicleStats(vehicle_name=name, **vals)
        for name, vals in sorted(buckets.items(), key=lambda kv: -kv[1]["energy_kwh"])
    ]
