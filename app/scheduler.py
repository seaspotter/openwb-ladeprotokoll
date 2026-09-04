"""Daily background fetch: refetches the current month for every enabled
source, so no manual "Jetzt abrufen" click is needed to catch up on
today's charging sessions.

Runs once immediately at app startup (so a freshly deployed instance isn't
empty until the first scheduled tick), then every 24h -- this only needs
to keep pace with a day's charging activity, not run near-real-time. The
per-source lock inside fetch_service.py already stops this from racing a
concurrent manual fetch-now/backfill on the same source.
"""
from __future__ import annotations

import asyncio
import logging

from .fetch_service import current_month, fetch_service

logger = logging.getLogger("openwb_ladeprotokoll.scheduler")

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


async def run_scheduler(pool) -> None:
    while True:
        try:
            await fetch_all_enabled(pool)
        except Exception:  # keep the background loop alive no matter what
            logger.exception("Unexpected error during scheduled fetch")
        await asyncio.sleep(FETCH_INTERVAL_SECONDS)
