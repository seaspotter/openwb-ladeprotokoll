"""Single-row app_settings table: whether the daily background fetch
scheduler (scheduler.py) runs at all, and at what wall-clock time. Read by
both web.py's GET/PUT /api/app-settings and scheduler.py's own loop, hence
its own tiny module -- mirrors report_settings.py's pure validate() +
upsert-on-first-read pattern, so there's no separate seeding step.
"""
from __future__ import annotations

import re

import asyncpg

DEFAULT_AUTO_FETCH_ENABLED = True
# Shortly past midnight by default: late enough that the day just ending
# has fully landed in openWB's own charge-log file, early enough that
# someone checking first thing in the morning already sees yesterday's
# sessions.
DEFAULT_AUTO_FETCH_TIME = "00:05"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class AppSettingsError(ValueError):
    pass


def validate(patch: dict) -> dict:
    """Validates only the keys present in patch (a partial update), raising
    AppSettingsError on the first problem found. Unknown keys are ignored,
    same as report_settings.validate()."""
    result: dict = {}
    if "auto_fetch_enabled" in patch:
        value = patch["auto_fetch_enabled"]
        if not isinstance(value, bool):
            raise AppSettingsError("auto_fetch_enabled muss ein Bool sein")
        result["auto_fetch_enabled"] = value
    if "auto_fetch_time" in patch:
        value = patch["auto_fetch_time"]
        if not isinstance(value, str) or not _TIME_RE.match(value):
            raise AppSettingsError(
                f"Ungültige Uhrzeit: {value!r} (erwartet HH:MM, 24h-Format)"
            )
        result["auto_fetch_time"] = value
    return result


async def get_settings(pool: asyncpg.Pool) -> dict:
    row = await pool.fetchrow(
        "SELECT auto_fetch_enabled, auto_fetch_time FROM app_settings WHERE id = 1"
    )
    if row is None:
        row = await pool.fetchrow(
            "INSERT INTO app_settings (id) VALUES (1) "
            "ON CONFLICT (id) DO UPDATE SET id = app_settings.id "
            "RETURNING auto_fetch_enabled, auto_fetch_time"
        )
    return dict(row)


async def update_settings(pool: asyncpg.Pool, patch: dict) -> dict:
    validated = validate(patch)
    current = await get_settings(pool)
    merged = {**current, **validated}
    row = await pool.fetchrow(
        "INSERT INTO app_settings (id, auto_fetch_enabled, auto_fetch_time) "
        "VALUES (1, $1, $2) "
        "ON CONFLICT (id) DO UPDATE SET "
        "auto_fetch_enabled = $1, auto_fetch_time = $2 "
        "RETURNING auto_fetch_enabled, auto_fetch_time",
        merged["auto_fetch_enabled"], merged["auto_fetch_time"],
    )
    return dict(row)
