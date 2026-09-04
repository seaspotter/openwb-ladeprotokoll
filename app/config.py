"""Infra-level configuration: how to reach the database, read once from
environment variables at import time.

Everything about a specific openWB installation -- its address, which
vehicles/chargepoints it has, electricity prices -- is deliberately NOT
here. Sources and prices are user data stored in the database, added and
edited from the web UI.

DATABASE_URL, if set, wins outright -- the escape hatch for anything that
deviates from this project's own docker-compose.yml (local dev against
localhost, a differently-named Postgres host, etc.). Otherwise,
POSTGRES_PASSWORD alone is enough: user/db/host/port are fixed values
matching docker-compose.yml's `postgres` service, not something a standard
deployment needs to vary, so a compose file only has to reference that one
variable for both services -- not also hand-assemble a
`postgresql://user:pass@host:port/db` string a second time.

The bind port (PORT) isn't here either: it's only ever needed by uvicorn's
own `--port` flag, handed to it directly by the container entrypoint (see
Dockerfile) -- there's no reason for application code to also know it.
"""
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
