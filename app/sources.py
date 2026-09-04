"""Source configuration: what a user enters to point at one openWB
installation, and the pure normalization/validation of that input.

A source is otherwise plain user data stored in the `sources` table (see
db.py) -- there's no catalog of known installations the way log_catalog.py
has for openwb-logger, since every openWB IP is equally valid.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class SourceValidationError(ValueError):
    pass


@dataclass
class Source:
    id: int
    name: str
    base_url: str
    enabled: bool


def normalize_base_url(raw: str) -> str:
    """Accepts a bare IP/hostname ("192.168.1.10"), a host:port, or a full
    URL, and returns a base URL with no trailing slash -- openwb_client.py
    appends "/openWB/data/charge_log/<yyyymm>.json" directly onto this.
    Defaults to http:// (openWB's own web server doesn't offer TLS out of
    the box) when no scheme is given, rather than guessing based on the
    port or failing and forcing the user to type it out."""
    raw = raw.strip()
    if not raw:
        raise SourceValidationError("Adresse darf nicht leer sein")

    candidate = raw if "://" in raw else f"http://{raw}"
    parsed = urlparse(candidate)

    if parsed.scheme not in ("http", "https"):
        raise SourceValidationError(f"Nicht unterstütztes Schema: {parsed.scheme}")
    if not parsed.hostname:
        raise SourceValidationError(f"Ungültige Adresse: {raw!r}")

    netloc = parsed.hostname
    if parsed.port:
        netloc += f":{parsed.port}"
    return f"{parsed.scheme}://{netloc}"


def validate_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise SourceValidationError("Name darf nicht leer sein")
    return name
