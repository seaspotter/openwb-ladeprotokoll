"""openwb-ladeprotokoll
--------------------------------
Pulls openWB charge-log data into Postgres and turns it into audit-safe
PDF charging-cost reports.

Copyright (C) 2026 the project author(s).
Licensed under the GNU Affero General Public License v3.0 or later.
See the LICENSE file in the repository root for the full text.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import close_pool, init_pool
from .mcp_server import mcp
from .scheduler import run_scheduler
from .web import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("openwb_ladeprotokoll")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        pool = await init_pool()
        logger.info("Starting openwb-ladeprotokoll")
        task = asyncio.create_task(run_scheduler(pool))
        # Mounting the MCP server (see below) disables its own built-in
        # lifespan, so its session manager has to be entered here instead
        # -- otherwise its first request fails.
        await stack.enter_async_context(mcp.session_manager.run())
        yield
        task.cancel()
        await close_pool()


app = FastAPI(title="openwb-ladeprotokoll", lifespan=lifespan)
app.include_router(router)
app.mount("/mcp", mcp.streamable_http_app())
# Vendored, not CDN-loaded -- this app has no external network dependency
# anywhere else (every icon is inline SVG), and the statistik page's
# Chart.js should keep working on a fully offline LAN. See DEPLOYMENT.md.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
