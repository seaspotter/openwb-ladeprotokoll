"""Orchestrates one fetch run for a source: month list -> HTTP (openwb_client)
-> parse (chargelog_parse) -> idempotent upsert into `sessions`.

Single code path for every trigger (manual "fetch now", the daily
scheduler, on-demand backfill) -- they differ only in which months they
pass in. A per-source asyncio.Lock stops a manual trigger and the daily
run from racing on the same source's upsert.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from .chargelog_parse import ChargeLogParseError, parse_record
from .openwb_client import fetch_month

logger = logging.getLogger("openwb_ladeprotokoll.fetch_service")

_UPSERT_SQL = """
INSERT INTO sessions (
    source_id, chargepoint_id, chargepoint_name, chargepoint_serial_number,
    vehicle_id, vehicle_name, vehicle_chargemode, vehicle_prio, vehicle_rfid,
    soc_at_start, soc_at_end, range_at_start, range_at_end, odometer,
    time_begin, time_end, time_charged_seconds, cost_openwb,
    power_source_grid_pct, power_source_cp_pct, power_source_bat_pct, power_source_pv_pct,
    energy_kwh, energy_since_plugged_kwh, energy_discharged_kwh, range_charged_km,
    meter_start_kwh, meter_end_kwh, raw_json, updated_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18,
    $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29, now()
)
ON CONFLICT (source_id, chargepoint_serial_number, time_begin) DO UPDATE SET
    chargepoint_id = EXCLUDED.chargepoint_id,
    chargepoint_name = EXCLUDED.chargepoint_name,
    vehicle_id = EXCLUDED.vehicle_id,
    vehicle_name = EXCLUDED.vehicle_name,
    vehicle_chargemode = EXCLUDED.vehicle_chargemode,
    vehicle_prio = EXCLUDED.vehicle_prio,
    vehicle_rfid = EXCLUDED.vehicle_rfid,
    soc_at_start = EXCLUDED.soc_at_start,
    soc_at_end = EXCLUDED.soc_at_end,
    range_at_start = EXCLUDED.range_at_start,
    range_at_end = EXCLUDED.range_at_end,
    odometer = EXCLUDED.odometer,
    time_end = EXCLUDED.time_end,
    time_charged_seconds = EXCLUDED.time_charged_seconds,
    cost_openwb = EXCLUDED.cost_openwb,
    power_source_grid_pct = EXCLUDED.power_source_grid_pct,
    power_source_cp_pct = EXCLUDED.power_source_cp_pct,
    power_source_bat_pct = EXCLUDED.power_source_bat_pct,
    power_source_pv_pct = EXCLUDED.power_source_pv_pct,
    energy_kwh = EXCLUDED.energy_kwh,
    energy_since_plugged_kwh = EXCLUDED.energy_since_plugged_kwh,
    energy_discharged_kwh = EXCLUDED.energy_discharged_kwh,
    range_charged_km = EXCLUDED.range_charged_km,
    meter_start_kwh = EXCLUDED.meter_start_kwh,
    meter_end_kwh = EXCLUDED.meter_end_kwh,
    raw_json = EXCLUDED.raw_json,
    updated_at = now()
"""


def current_month() -> str:
    return datetime.now().strftime("%Y%m")


def month_range(from_month: str, to_month: str) -> list[str]:
    """Inclusive list of "YYYYMM" strings from from_month to to_month."""
    start = date(int(from_month[:4]), int(from_month[4:]), 1)
    end = date(int(to_month[:4]), int(to_month[4:]), 1)
    if end < start:
        raise ValueError(f"to_month {to_month!r} is before from_month {from_month!r}")
    months = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


@dataclass
class FetchResult:
    ok: bool
    sessions_upserted: int = 0
    error: str | None = None


class FetchService:
    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, source_id: int) -> asyncio.Lock:
        return self._locks.setdefault(source_id, asyncio.Lock())

    async def fetch_source(self, pool, source, months: list[str]) -> FetchResult:
        """`source` is a mapping with at least "id" and "base_url" (an
        asyncpg Record or plain dict both work)."""
        async with self._lock_for(source["id"]):
            try:
                rows = []
                async with httpx.AsyncClient() as client:
                    for yyyymm in months:
                        records = await fetch_month(client, source["base_url"], yyyymm)
                        for record in records:
                            try:
                                rows.append(parse_record(record))
                            except ChargeLogParseError as exc:
                                logger.warning(
                                    "[source %s] skipping unparseable record in %s: %s",
                                    source["id"], yyyymm, exc,
                                )

                async with pool.acquire() as conn:
                    async with conn.transaction():
                        for row in rows:
                            await conn.execute(
                                _UPSERT_SQL,
                                source["id"],
                                row["chargepoint_id"],
                                row["chargepoint_name"],
                                row["chargepoint_serial_number"],
                                row["vehicle_id"],
                                row["vehicle_name"],
                                row["vehicle_chargemode"],
                                row["vehicle_prio"],
                                row["vehicle_rfid"],
                                row["soc_at_start"],
                                row["soc_at_end"],
                                row["range_at_start"],
                                row["range_at_end"],
                                row["odometer"],
                                row["time_begin"],
                                row["time_end"],
                                row["time_charged_seconds"],
                                row["cost_openwb"],
                                row["power_source_grid_pct"],
                                row["power_source_cp_pct"],
                                row["power_source_bat_pct"],
                                row["power_source_pv_pct"],
                                row["energy_kwh"],
                                row["energy_since_plugged_kwh"],
                                row["energy_discharged_kwh"],
                                row["range_charged_km"],
                                row["meter_start_kwh"],
                                row["meter_end_kwh"],
                                row["raw_json"],
                            )
                    await conn.execute(
                        "UPDATE sources SET last_fetch_at = now(), last_fetch_status = $2 "
                        "WHERE id = $1",
                        source["id"], "ok",
                    )
                return FetchResult(ok=True, sessions_upserted=len(rows))
            except Exception as exc:  # keep callers/scheduler alive no matter what
                logger.exception("[source %s] fetch failed", source["id"])
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE sources SET last_fetch_at = now(), last_fetch_status = $2 "
                        "WHERE id = $1",
                        source["id"], f"error: {exc}",
                    )
                return FetchResult(ok=False, error=str(exc))


fetch_service = FetchService()
