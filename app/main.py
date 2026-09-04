"""openwb-ladeprotokoll
--------------------------------
Pulls openWB charge-log data into Postgres and turns it into audit-safe
PDF charging-cost reports.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .db import close_pool, init_pool
from .scheduler import run_scheduler
from .web import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("openwb_ladeprotokoll")


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = await init_pool()
    logger.info("Starting openwb-ladeprotokoll")
    task = asyncio.create_task(run_scheduler(pool))
    yield
    task.cancel()
    await close_pool()


app = FastAPI(title="openwb-ladeprotokoll", lifespan=lifespan)
app.include_router(router)
