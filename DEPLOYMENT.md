# Deployment

## Quick start

```bash
git clone https://github.com/seaspotter/openwb-ladeprotokoll.git
cd openwb-ladeprotokoll
cp .env.example .env
# edit .env: set a real POSTGRES_PASSWORD

docker compose up -d --build
```

Open http://localhost:8080 and add your openWB installation(s) from the
dashboard.

## Configuration

Almost nothing lives in `.env` — every openWB installation, vehicle, and
electricity price is user data added *inside the app* after first start,
stored in Postgres. `.env` is pure infra wiring.

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | — | Set a real password. The **same variable** is passed to both services — `postgres` reads it directly, and `app` builds its own connection string from it (`app/config.py`) — so there's only one place to set it. |
| `PORT` | `8080` | Web UI / API port |
| `TZ` | `Europe/Berlin` | Container timezone. Affects only app-generated timestamps (report generation date, "Letzter Abruf") — a session's own Beginn/Ende come straight from openWB and are unaffected. Override if you're not in that zone. |
| `DATABASE_URL` | — | Full Postgres connection string; wins outright over `POSTGRES_PASSWORD`. An escape hatch for anything that deviates from the standard two-service `docker-compose.yml` setup above. |

## State and backups

- The `postgres_data` named volume is the only state: sources, sessions,
  price entries, and every generated report (including its rendered PDF
  bytes) all live there. Back it up like any Postgres data directory if
  any of it matters to you (`pg_dump`/`pg_basebackup`, or snapshot the
  volume).
- The `app` container is stateless and can be freely restarted or
  recreated.

## Upgrading

```bash
git pull
docker compose up -d --build
```

Schema changes are additive and applied automatically at startup
(`CREATE TABLE IF NOT EXISTS` in `app/db.py`) — no separate migration
step.

### Self-update from the UI

Same mechanism as the sibling `openwb-logger` project: an "Update" button
runs `git pull --ff-only` against the repo checkout, then restarts the
process so it picks up the new code — works because `docker-compose.yml`
bind-mounts the whole repo onto the container's `WORKDIR` (`- .:/app`).
If a pull brings in a `requirements.txt` or `Dockerfile` change, the
endpoint deliberately does *not* restart and instead tells you to run
`docker compose up -d --build` — the new dependency isn't installed in the
running container yet.

**Security note**: the web UI has no authentication. If it's reachable
beyond your LAN, put it behind an authenticated reverse proxy.

## Running behind a reverse proxy

Plain HTTP app on one port, no WebSocket/SSE dependency — any standard
reverse-proxy config (Caddy, nginx, Traefik) that forwards to
`app:$PORT` works. Add basic auth or your usual SSO layer there, since
there's none built in.

## Troubleshooting

- **PDF generation fails at startup / in the container**: WeasyPrint
  needs system libraries (`libpango`, `libcairo`, `libgdk-pixbuf`, etc. —
  see the `apt-get install` list in `Dockerfile`) that aren't
  pip-installable. These are already baked into the published image; if
  you're building your own variant of the Dockerfile, don't drop that
  layer.
- **A source's fetch keeps failing**: check the source's status on the
  dashboard, and confirm `http://<that-openWB-IP>/openWB/data/charge_log/<yyyymm>.json`
  is actually reachable from *inside* the app container (not just your
  browser) — `docker compose exec app curl -i ...` is the quickest check.
