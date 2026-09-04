"""MCP server exposing charge-log sessions and report generation to AI
assistants -- mirrors the web UI's own session search and report
generation, mounted on the same FastAPI app (same port, same DB pool,
same trust model) via MCP's Streamable HTTP transport at /mcp. See
app/main.py for how this gets wired into the app's lifespan (mounting
disables FastMCP's own lifespan; the host app's lifespan has to enter
`mcp.session_manager.run()` instead, or the first request fails).

No new authentication here -- this reaches exactly the same data as the
existing web UI/API, under the same no-auth-by-default, LAN-trust model
documented in DEPLOYMENT.md. Put it behind a reverse proxy along with
everything else if that's ever not enough.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP

from .db import get_pool
from .report_build import COLUMN_LABELS, ReportBuildError
from .web import _generate_report, _query_sessions

# streamable_http_path="/" so mounting this server's ASGI app at "/mcp" on
# the main FastAPI app (see main.py) puts the actual endpoint at exactly
# /mcp, not /mcp/mcp (FastMCP's own default streamable_http_path is
# already "/mcp", meant for when it's the *only* app being served).
mcp = FastMCP("openwb-ladeprotokoll", streamable_http_path="/")

# Modest default, unlike the web UI's own /api/sessions (no cap at all --
# sized for what a browser can render/filter): responses here flow into an
# LLM's context window, which has a much tighter, more expensive budget.
SEARCH_DEFAULT_LIMIT = 200
SEARCH_MAX_LIMIT = 2000


@mcp.tool()
async def search_sessions(
    source_id: int | None = None,
    vehicle: str | None = None,
    chargepoint: str | None = None,
    from_: date | None = None,
    to: date | None = None,
    limit: int = SEARCH_DEFAULT_LIMIT,
) -> list[dict]:
    """Search charging sessions fetched from openWB. Filter by source id
    (see the openwb://sources resource for valid ids), vehicle name,
    chargepoint name, and/or a from/to date range (inclusive, matched
    against the session's own begin date). Returns matching sessions --
    including each one's matched electricity price decision (provider,
    corrected cost, delta vs. openWB's own value) -- newest first, capped
    at `limit` (default 200, max 2000). Each session's `id` is what
    generate_report's `session_ids` expects."""
    pool = get_pool()
    sessions = await _query_sessions(pool, source_id, vehicle, chargepoint, from_, to)
    return sessions[: min(limit, SEARCH_MAX_LIMIT)]


@mcp.tool()
async def generate_report(
    session_ids: list[int], title: str, columns: list[str] | None = None,
    cost_basis: str | None = None,
) -> dict:
    """Generates and permanently stores an audit-safe PDF charging-cost
    report from the given session ids (see search_sessions), immutable
    once created. `title` becomes both the document's heading and (with a
    date prefix) its filename. `columns` optionally overrides which of the
    report's columns appear (see the openwb://report-columns resource for
    valid keys) -- omit it to use the configured default from Berichts-
    Einstellungen. `cost_basis` optionally overrides which "Kosten" figure
    the report uses -- "openwb" (openWB's own value), "corrected" (this
    app's price-entry correction against the session's total energy), or
    "corrected_grid_only" (the same correction, but only against the
    grid-imported share of energy -- for a reimbursement scenario where
    self-generated PV/battery energy shouldn't count at the configured
    €/kWh rate); omit it to use the configured default. Every session is
    priced automatically (the same matching search_sessions already
    shows); there's no per-session price override here, unlike the review
    UI -- use that UI first if a specific session needs a manual price
    override before generating the report. Returns the report's summary
    (id, title, totals, cost_basis, session count) -- the rendered PDF
    itself is downloadable at GET /reports/{id}/pdf on this same host, not
    returned inline here."""
    pool = get_pool()
    try:
        return await _generate_report(pool, title, session_ids, columns, {}, cost_basis)
    except ReportBuildError as exc:
        raise ValueError(str(exc)) from exc
    except HTTPException as exc:
        # _load_report_sessions (called by _generate_report) raises this
        # directly rather than ReportBuildError for a missing/unknown
        # session id -- unwrap to a plain message instead of leaking a
        # FastAPI-specific exception (with its "404: " prefix) through
        # the MCP boundary.
        raise ValueError(str(exc.detail)) from exc


@mcp.resource("openwb://sources")
async def list_sources() -> list[dict]:
    """The configured openWB sources -- valid `source_id` values for
    search_sessions, along with each one's name, address, and enabled
    state."""
    pool = get_pool()
    rows = await pool.fetch("SELECT id, name, base_url, enabled FROM sources ORDER BY name")
    return [dict(r) for r in rows]


@mcp.resource("openwb://report-columns")
def list_report_columns() -> list[dict]:
    """Every column key generate_report's `columns` parameter accepts,
    with its German display label."""
    return [{"key": k, "label": v} for k, v in COLUMN_LABELS.items()]
