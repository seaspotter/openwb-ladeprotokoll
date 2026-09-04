"""HTTP client for one openWB installation's charge log JSON files.

`data/charge_log/<yyyymm>.json` is served anonymously by openWB's own
Apache (whole repo as web root, `Require all granted`, no auth) -- no core
changes, no credentials, confirmed against a live instance. A month with no
sessions yet simply isn't there (404), which is normal, not an error.
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("openwb_ladeprotokoll.openwb_client")

HTTP_TIMEOUT_SECONDS = 15


class OpenwbClientError(Exception):
    pass


async def fetch_month(client: httpx.AsyncClient, base_url: str, yyyymm: str) -> list[dict]:
    """Returns the list of raw charge-log records for one month, or an
    empty list if openWB has none yet (404). Any other failure (timeout,
    connection refused, 5xx, malformed JSON) raises OpenwbClientError --
    fetch_service.py decides how that should affect the source's overall
    fetch status."""
    url = f"{base_url}/openWB/data/charge_log/{yyyymm}.json"
    try:
        resp = await client.get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise OpenwbClientError(f"Could not reach {url}: {exc}") from exc

    if resp.status_code == 404:
        return []
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise OpenwbClientError(f"{url} returned {resp.status_code}") from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise OpenwbClientError(f"{url} did not return valid JSON: {exc}") from exc

    if isinstance(payload, dict):
        # openWB's charge_log files are known to sometimes key records by
        # id/timestamp rather than being a bare list -- accept either shape
        # rather than assuming one.
        return list(payload.values())
    if isinstance(payload, list):
        return payload
    raise OpenwbClientError(f"{url} returned unexpected JSON shape: {type(payload).__name__}")
