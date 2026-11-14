"""Infra-level configuration: how to reach the database, read once from
environment variables at import time.

A specific openWB installation's address/vehicles/prices is deliberately
NOT here -- that's user data in the database, added/edited from the web
UI.

DATABASE_URL, if set, wins outright (the escape hatch for anything that
deviates from docker-compose.yml). Otherwise POSTGRES_PASSWORD alone is
enough -- user/db/host/port are fixed to match docker-compose.yml's
`postgres` service, so a compose file only needs that one variable.

PORT isn't here either: only uvicorn's own `--port` flag needs it, handed
to it directly by the container entrypoint (see Dockerfile)."""
from __future__ import annotations

import os


def _database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    if password := os.environ.get("POSTGRES_PASSWORD"):
        return f"postgresql://openwb_ladeprotokoll:{password}@postgres:5432/openwb_ladeprotokoll"
    return "postgresql://openwb_ladeprotokoll:openwb_ladeprotokoll@localhost:5432/openwb_ladeprotokoll"


class Settings:
    database_url: str = _database_url()


settings = Settings()
