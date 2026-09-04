"""asyncpg connection pool and idempotent schema bootstrap.

No ORM, no migration tool: the schema is small and stable enough that a
single idempotent bootstrap script -- CREATE ... IF NOT EXISTS plus additive
ALTER ... ADD COLUMN IF NOT EXISTS for later changes -- is simpler to reason
about than adding Alembic. If the schema grows meaningfully, revisit that.
"""
from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings

logger = logging.getLogger("openwb_ladeprotokoll.db")

_pool: asyncpg.Pool | None = None

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS sources (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        base_url TEXT NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        last_fetch_at TIMESTAMPTZ,
        last_fetch_status TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    # Natural key (source_id, chargepoint_serial_number, time_begin): a
    # chargepoint can only run one session at a time, so its own start
    # timestamp is a stable identity across refetches -- serial number is
    # hardware-fixed, more durable than openWB's internal chargepoint id
    # (which can be reassigned on reconfiguration). ON CONFLICT DO UPDATE
    # (see fetch_service.py) overwrites every other column on refetch, which
    # is what lets a still-charging session (time_end NULL on first fetch)
    # get completed by the next day's fetch, and absorbs any correction
    # openWB itself makes to the record in place.
    #
    # Known risk, not engineered around: two sessions on the same
    # chargepoint starting in the same second would collide -- acceptable
    # given openWB's own second-resolution timestamps.
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id BIGSERIAL PRIMARY KEY,
        source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
        chargepoint_id TEXT,
        chargepoint_name TEXT,
        chargepoint_serial_number TEXT NOT NULL,
        vehicle_id TEXT,
        vehicle_name TEXT,
        vehicle_chargemode TEXT,
        vehicle_prio TEXT,
        vehicle_rfid TEXT,
        soc_at_start NUMERIC,
        soc_at_end NUMERIC,
        range_at_start NUMERIC,
        range_at_end NUMERIC,
        odometer NUMERIC,
        time_begin TIMESTAMPTZ NOT NULL,
        time_end TIMESTAMPTZ,
        time_charged_seconds INTEGER,
        cost_openwb NUMERIC(10, 2),
        -- "Energieanteil Netz/Ladepunkte/Speicher/PV" in the openWB UI:
        -- percentage (0-100) share of this row's own energy_kwh. Raw JSON
        -- stores these as fractions (0.0-1.0); chargelog_parse.py converts
        -- to 0-100 on the way in. The four don't reliably sum to exactly
        -- 100 (rounding) -- confirmed against both a real CSV export and a
        -- real charge_log/*.json file.
        power_source_grid_pct NUMERIC,
        power_source_cp_pct NUMERIC,
        power_source_bat_pct NUMERIC,
        power_source_pv_pct NUMERIC,
        -- "Energie" in the openWB UI (data.imported_since_mode_switch,
        -- stored raw in Wh -- chargelog_parse.py divides by 1000): the
        -- per-row kWh figure -- sum *this* one for a report total, never
        -- energy_since_plugged_kwh (see below).
        energy_kwh NUMERIC,
        -- "Energie seit Anstecken" (data.imported_since_plugged, also raw
        -- Wh): cumulative kWh since this plug-in event started, across
        -- every charge-mode switch that split it into multiple rows. Kept
        -- for reference/audit only -- summing it across a plug-in's rows
        -- double-counts energy, since each row already carries the
        -- running total.
        energy_since_plugged_kwh NUMERIC,
        -- "Entladene Energie" (V2H/V2G): data.exported_since_mode_switch,
        -- raw Wh. The field exists in every real record seen so far but
        -- has always been 0 (none of the sample vehicles use V2H) -- still
        -- unconfirmed for an actual nonzero value.
        energy_discharged_kwh NUMERIC,
        range_charged_km NUMERIC,
        -- "Zähler Laden Beginn"/"Zähler Laden Ende": the chargepoint meter's
        -- own cumulative reading (data.imported_at_start/end, raw Wh --
        -- chargelog_parse.py divides by 1000), not the session's energy
        -- delta.
        meter_start_kwh NUMERIC,
        meter_end_kwh NUMERIC,
        raw_json JSONB NOT NULL,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (source_id, chargepoint_serial_number, time_begin)
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_source_time "
    "ON sessions (source_id, time_begin DESC);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_vehicle ON sessions (vehicle_name);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_chargepoint ON sessions (chargepoint_name);",
    # source_id/vehicle_name NULL = wildcard (any source / any vehicle) --
    # see price_entries.py for the match/precedence algorithm.
    """
    CREATE TABLE IF NOT EXISTS price_entries (
        id SERIAL PRIMARY KEY,
        source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
        vehicle_name TEXT,
        provider TEXT NOT NULL,
        price_per_kwh NUMERIC(10, 4) NOT NULL,
        valid_from DATE NOT NULL,
        valid_to DATE,
        notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_price_entries_lookup "
    "ON price_entries (source_id, vehicle_name, valid_from);",
    # Reports are immutable once generated -- "regenerate" always inserts a
    # new row. pdf_data holds the actual rendered bytes, not just enough to
    # re-render, since a later template change could render an identical
    # snapshot differently -- see report_build.py / pdf_render.py.
    """
    CREATE TABLE IF NOT EXISTS reports (
        id SERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        title TEXT NOT NULL,
        column_selection JSONB NOT NULL,
        total_duration_seconds INTEGER NOT NULL,
        total_energy_kwh NUMERIC NOT NULL,
        total_energy_discharged_kwh NUMERIC NOT NULL,
        total_range_charged_km NUMERIC NOT NULL,
        total_cost_openwb NUMERIC NOT NULL,
        total_cost_corrected NUMERIC NOT NULL,
        -- Which of the two totals above this report's own "Kosten"
        -- actually used -- report_build.COST_BASES ("openwb"/"corrected").
        -- Default matches report_settings.DEFAULT_COST_BASIS, the
        -- effective value for every report generated before this column
        -- existed.
        cost_basis TEXT NOT NULL DEFAULT 'corrected',
        pdf_data BYTEA NOT NULL
    );
    """,
    # Added after reports already existed on some deployments (this
    # project's own live deployment included) -- CREATE TABLE IF NOT
    # EXISTS above is a no-op there, so this column has to be added
    # explicitly. The DEFAULT backfills any existing row.
    "ALTER TABLE reports ADD COLUMN IF NOT EXISTS cost_basis TEXT NOT NULL DEFAULT 'corrected';",
    # session_id ON DELETE SET NULL, not CASCADE: a report must stay
    # readable/reproducible via its own frozen `snapshot` even if the
    # underlying cached session row is later deleted or refetched away --
    # that's the whole point of the audit snapshot.
    """
    CREATE TABLE IF NOT EXISTS report_sessions (
        id BIGSERIAL PRIMARY KEY,
        report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
        session_id BIGINT REFERENCES sessions(id) ON DELETE SET NULL,
        snapshot JSONB NOT NULL,
        price_entry_snapshot JSONB,
        cost_openwb NUMERIC,
        cost_corrected NUMERIC,
        cost_used NUMERIC NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_report_sessions_report ON report_sessions (report_id);",
    # Single-row app-wide settings for report generation (default PDF
    # columns, which cost figure to display, whether the signature line
    # appears) -- see report_settings.py. The CHECK pins it to exactly one
    # row (id = 1); get_settings()/update_settings() insert that row with
    # hardcoded defaults on first use rather than seeding it here, so the
    # defaults live in one place (report_settings.py), not duplicated into
    # SQL too.
    """
    CREATE TABLE IF NOT EXISTS report_settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        default_columns JSONB NOT NULL,
        cost_basis TEXT NOT NULL,
        show_signature_line BOOLEAN NOT NULL,
        orientation TEXT NOT NULL DEFAULT 'portrait',
        -- Global EUR/kWh rates for PV- and battery-sourced energy, used by
        -- price_entries.corrected_cost alongside a session's matched (or
        -- overridden) price_entries row, which only ever covers the
        -- grid-sourced share -- see price_entries.py's module docstring.
        -- Not scoped by source/vehicle/date like price_entries, since a
        -- self-produced kWh's cost doesn't vary by tariff period.
        pv_price_per_kwh NUMERIC NOT NULL DEFAULT 0,
        bat_price_per_kwh NUMERIC NOT NULL DEFAULT 0,
        CHECK (id = 1)
    );
    """,
    # Added after report_settings already existed on some deployments (this
    # project's own test container included) -- CREATE TABLE IF NOT EXISTS
    # above is a no-op there, so the column has to be added explicitly. The
    # DEFAULT backfills any existing row.
    "ALTER TABLE report_settings ADD COLUMN IF NOT EXISTS orientation TEXT "
    "NOT NULL DEFAULT 'portrait';",
    "ALTER TABLE report_settings ADD COLUMN IF NOT EXISTS pv_price_per_kwh "
    "NUMERIC NOT NULL DEFAULT 0;",
    "ALTER TABLE report_settings ADD COLUMN IF NOT EXISTS bat_price_per_kwh "
    "NUMERIC NOT NULL DEFAULT 0;",
    # User-entered metadata keyed by vehicle_name, the only vehicle identity
    # this app has (openWB's own charge-log JSON has no license-plate field
    # at all) -- purely for documenting the Kennzeichen on generated reports,
    # not fetched or validated against anything.
    """
    CREATE TABLE IF NOT EXISTS vehicles (
        vehicle_name TEXT PRIMARY KEY,
        license_plate TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    # Single-row app-wide settings unrelated to report generation (see
    # report_settings.py for that) -- currently whether the daily
    # background fetch scheduler runs at all, and at what wall-clock time,
    # see app_settings.py.
    """
    CREATE TABLE IF NOT EXISTS app_settings (
        id INTEGER PRIMARY KEY DEFAULT 1,
        auto_fetch_enabled BOOLEAN NOT NULL DEFAULT TRUE,
        auto_fetch_time TEXT NOT NULL DEFAULT '00:05',
        CHECK (id = 1)
    );
    """,
]


async def _init_connection(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def init_pool() -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=5, init=_init_connection
    )
    async with _pool.acquire() as conn:
        for stmt in _SCHEMA_STATEMENTS:
            await conn.execute(stmt)
    logger.info("Database ready")
    return _pool


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialised; call init_pool() first")
    return _pool
