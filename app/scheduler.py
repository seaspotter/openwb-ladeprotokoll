"""Daily background fetch: refetches the current month for every enabled
source, so no manual "Jetzt abrufen" click is needed to catch up on
today's charging sessions.

Runs once immediately at app startup (so a freshly deployed instance isn't
empty until the first scheduled tick), then daily at a configurable
wall-clock time (app_settings.auto_fetch_time, default shortly after
midnight) -- computed fresh from the current setting each cycle via
`_next_run_at`, so a time changed while the loop is sleeping takes effect
from the next wake, not instantly (same "applies from the next cycle"
tradeoff already accepted for the enabled flag below). The per-source lock
inside fetch_service.py already stops this from racing a concurrent manual
fetch-now/backfill on the same source.

Can be turned off entirely via the "Automatischer Abruf" checkbox
(Einstellungen -> Quellen, app_settings.auto_fetch_enabled) -- the loop
below keeps running either way, just skipping the actual fetch (including
the startup one) while disabled, so re-enabling it later doesn't need a
restart.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dt_time, timedelta

from .app_settings import get_settings as get_app_settings
from .fetch_service import current_month, fetch_service

logger = logging.getLogger("openwb_ladeprotokoll.scheduler")

# Fallback only -- used if reading app_settings itself fails, so the loop
# still retries at some point rather than spinning or dying.
FETCH_INTERVAL_SECONDS = 24 * 60 * 60


async def fetch_all_enabled(pool) -> None:
    sources = await pool.fetch("SELECT * FROM sources WHERE enabled")
    months = [current_month()]
    for source in sources:
        result = await fetch_service.fetch_source(pool, source, months=months)
        if not result.ok:
            logger.warning(
                "[source %s] scheduled fetch failed: %s", source["id"], result.error
            )


def _parse_time(value: str) -> dt_time:
    hour, minute = value.split(":")
    return dt_time(int(hour), int(minute))


def _next_run_at(target: dt_time, now: datetime) -> datetime:
    candidate = datetime.combine(now.date(), target)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def _run_fetch_cycle(pool) -> None:
    settings = await get_app_settings(pool)
    if settings["auto_fetch_enabled"]:
        await fetch_all_enabled(pool)
    else:
        logger.info("Automatic fetch is disabled, skipping this cycle")


async def run_scheduler(pool) -> None:
    try:
        await _run_fetch_cycle(pool)
    except Exception:  # keep the background loop alive no matter what
        logger.exception("Unexpected error during startup fetch")

    while True:
        try:
            settings = await get_app_settings(pool)
            target = _parse_time(settings["auto_fetch_time"])
            now = datetime.now()
            sleep_seconds = max(1.0, (_next_run_at(target, now) - now).total_seconds())
        except Exception:
            logger.exception("Unexpected error computing next scheduled fetch time")
            sleep_seconds = FETCH_INTERVAL_SECONDS
        await asyncio.sleep(sleep_seconds)
        try:
            await _run_fetch_cycle(pool)
        except Exception:
            logger.exception("Unexpected error during scheduled fetch")
