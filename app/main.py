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
from mcp.server.transport_security import TransportSecuritySettings

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
app.mount("/mcp", mcp.streamable_http_app(
    # streamable_http_path="/" so this lands at exactly /mcp once mounted
    # above, not /mcp/mcp (streamable_http_app()'s own default path is
    # already "/mcp", meant for when it's the *only* app being served
    # standalone, unmounted).
    streamable_http_path="/",
    # Disables MCPServer's DNS-rebinding Host-header check -- confirmed
    # live as a real bug once already (see mcp_server.py's module
    # docstring): it auto-enables whenever transport_security isn't given
    # and the (unused-here) `host` param defaults to "127.0.0.1",
    # rejecting every real LAN Host header with a 421. That default
    # assumes this runs its own standalone server bound to loopback; this
    # one is mounted inside the main FastAPI app instead and reached the
    # same way as the rest of it -- explicitly no-auth-by-default,
    # LAN-trust -- so the Host-based allowlist doesn't fit here any more
    # than on any other route.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
))
# Vendored, not CDN-loaded -- this app has no external network dependency
# anywhere else (every icon is inline SVG), and the statistik page's
# Chart.js should keep working on a fully offline LAN. See DEPLOYMENT.md.
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
