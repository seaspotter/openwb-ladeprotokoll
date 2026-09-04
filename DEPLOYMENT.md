# Deployment

## Quick start

```bash
git clone https://github.com/seaspotter/openwb-ladeprotokoll.git
cd openwb-ladeprotokoll
cp .env.example .env
# edit .env: set a real POSTGRES_PASSWORD

docker compose up -d --build
```

This starts two services: `postgres` (data in the `postgres_data` named
volume) and `app` (this tool, port 8080). Open http://localhost:8080, go
to "Einstellungen" and add your openWB installation(s) from there.

`build: .` (building locally) is the documented, primary path — it's what
the in-app self-update button assumes (see below). A prebuilt multi-arch
image (amd64/arm64) is also published to
`ghcr.io/seaspotter/openwb-ladeprotokoll` on every push to `main`, mainly
useful for a quick test or a host where building locally is slow; if you
use it instead of `build: .`, self-update won't have anything to update in
place (no bind-mounted git checkout) and you'd `docker compose pull` for
new versions instead.

## Running on Proxmox (Ubuntu Server)

Two options for the container itself; everything after that is identical
to any other Ubuntu host.

**LXC** (lighter, needs one tweak): create an unprivileged Ubuntu Server
22.04/24.04 LXC — 1-2 vCPU, 1-2 GB RAM, 10 GB disk is comfortable for this
workload (a handful of sources, PDF bytes stored per report, nothing like
the volume TimescaleDB-based sibling projects need). Docker needs kernel
features LXC blocks by default, so before first boot: **Resources →
Options → Features**, enable **Nesting** and **keyctl**. Without this,
`docker compose up` fails or the containers won't start.

**VM** (simpler, no caveats): a normal Ubuntu Server VM (ISO or
cloud-init), same sizing. Docker just works.

Either way:

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/seaspotter/openwb-ladeprotokoll.git
cd openwb-ladeprotokoll
cp .env.example .env
nano .env   # set a real POSTGRES_PASSWORD
docker compose up -d --build
```

Then open `http://<container-ip>:8080` and add a source from
Einstellungen. The container needs to be on a network/VLAN that can
actually reach the openWB device(s) — the same bridge as your LAN, not an
isolated Proxmox-internal network — or every source just shows a fetch
error in the settings panel. If you're assigning a static IP by hand,
double-check nothing else on the LAN already answers to it first (see
"IP address already in use" under Troubleshooting below — this bit a real
deployment during development).

## Running via Portainer (NAS, etc.)

Use the prebuilt image rather than `build: .` here — a Portainer stack
doesn't have (and doesn't need) a git checkout of this repo on the host,
just the compose file itself:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: openwb_ladeprotokoll
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: openwb_ladeprotokoll
    volumes:
      - /path/to/your/data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U openwb_ladeprotokoll"]
      interval: 5s
      timeout: 5s
      retries: 10

  app:
    image: ghcr.io/seaspotter/openwb-ladeprotokoll:latest
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      PORT: 8080
      TZ: Europe/Berlin
    ports:
      - "8080:8080"
```

Replace `/path/to/your/data/postgres` with wherever you want the database
files to actually live — a bind mount to a real path (rather than a
Docker-managed named volume) is usually the more convenient choice on a
NAS, since it's then visible/backupable through the NAS's own file
manager. Set `POSTGRES_PASSWORD` once, either via Portainer's own
"Environment variables" field on the stack (not the YAML text — this
avoids ever needing to type the same secret twice) or, if you'd rather
keep everything in the compose text itself, replace both
`${POSTGRES_PASSWORD}` occurrences with the same literal value — but
exactly the same value in both places, since a mismatch fails Postgres
authentication outright rather than falling back to anything.

No self-update here (see below) — no bind-mounted git checkout to `git
pull` against, since you're running the published image. Update by
re-pulling the image and redeploying the stack from Portainer instead.

## Configuration

Almost nothing lives in `.env` — every openWB installation, vehicle, price
entry, and report setting is user data added *inside the app* after first
start, stored in Postgres. `.env` is pure infra wiring.

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_PASSWORD` | — | Set a real password. The **same variable** is passed to both services — `postgres` reads it directly, and `app` builds its own connection string from it (`app/config.py`) — so there's only one place to set it. |
| `PORT` | `8080` | Web UI / API port |
| `TZ` | `Europe/Berlin` | Container timezone. Affects app-generated timestamps (report generation date, "Letzter Abruf", and the automatic-fetch time set in Einstellungen → Quellen) — a session's own Beginn/Ende come straight from openWB and are unaffected. Override if you're not in that zone. |
| `DATABASE_URL` | — | Full Postgres connection string; wins outright over `POSTGRES_PASSWORD`. An escape hatch for anything that deviates from the standard two-service `docker-compose.yml` setup above. |

On first start, automatic fetch defaults to **on**, at **00:05** daily —
adjustable (or off entirely) from the "Automatischer Abruf" checkbox in
Einstellungen → Quellen, no env var or restart needed.

## State and backups

- The `postgres_data` named volume is the only state: sources, sessions,
  price entries, vehicle Kennzeichen, and every generated report
  (including its rendered PDF bytes) all live there. Back it up like any
  Postgres data directory if any of it matters to you
  (`pg_dump`/`pg_basebackup`, or snapshot the volume).
- The `app` container is stateless and can be freely restarted or
  recreated.

## Upgrading

```bash
git pull
docker compose up -d --build
```

Schema changes are additive and applied automatically at startup
(`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ... ADD COLUMN IF NOT
EXISTS` in `app/db.py`) — no separate migration step.

### Self-update from the UI

An "Update" button in Einstellungen runs `git pull --ff-only` against the
repo checkout, then restarts the process so it picks up the new code — no
Docker socket, no image rebuild, no separate container involved. This
works because `docker-compose.yml` bind-mounts the whole repo onto the
container's `WORKDIR` (`- .:/app`), so the files the running process reads
*are* the git checkout; `git pull` updates them in place, and
`docker-compose`'s `restart: unless-stopped` brings the process back up
immediately after it exits (see `app/updater.py`). If you commented out
that bind mount for a fully immutable deployment, the Update button and
`/api/update/*` endpoints just report `self_update_available: false`
rather than showing a confusing git error.

**This only covers pure code/template changes.** If a pull brings in a
`requirements.txt` or `Dockerfile` change, the endpoint deliberately does
*not* restart — the new dependency isn't installed in the running
container yet — and instead tells you to run:
```bash
docker compose up -d --build
```
Check `CHANGELOG.md` after an update if you're unsure whether that
applies.

**Security note**: the web UI has no authentication (see below). Since
self-update no longer needs the Docker socket, the worst a compromised
request can do here is pull whatever's on the configured git
remote/branch and restart the process — not take over the host. Still, if
the UI is reachable beyond your LAN, put it behind an authenticated
reverse proxy.

## Running behind a reverse proxy

Plain HTTP app on one port, no WebSocket/SSE dependency — any standard
reverse-proxy config (Caddy, nginx, Traefik) that forwards to
`app:$PORT` works. The web UI has **no authentication**, deliberately —
this is designed for a trusted home network, not built as an in-app
feature. If it needs to be reachable beyond your LAN, put it behind a
reverse proxy with auth in front of it (e.g.
[Authelia](https://www.authelia.com/), the same approach used for
`knxpilot`) rather than exposing port 8080 directly.

## Troubleshooting

- **PDF generation fails at startup / in the container**: WeasyPrint needs
  Pango (`libpango-1.0-0`, `libpangoft2-1.0-0`) and some usable fonts
  (`fonts-liberation`) — see the `apt-get install` list in `Dockerfile`,
  and its comment for why *not* `libcairo2`/`libgdk-pixbuf2.0-0` despite
  older WeasyPrint install guides mentioning them (WeasyPrint 53+ dropped
  that dependency; including them broke a CI build outright once Debian
  trixie renamed/dropped `libgdk-pixbuf2.0-0` with no direct replacement).
  These are already baked into the published image; if you're building
  your own variant of the Dockerfile, don't drop that layer.
- **A source's fetch keeps failing**: check the source's status in
  Einstellungen, and confirm
  `http://<that-openWB-IP>/openWB/data/charge_log/<yyyymm>.json` is
  actually reachable from *inside* the app container (not just your
  browser) — `docker compose exec app curl -i ...` is the quickest check.
  Use "Jetzt abrufen" on that one source to retry immediately rather than
  waiting for the next scheduled fetch.
- **IP address already in use / "connection refused" from the LAN, but
  the app answers fine from inside the container itself**
  (`docker compose exec app curl -s localhost:8080` works,
  `curl http://<host-ip>:8080` from another machine doesn't): this can be
  an IP conflict with an unrelated device on the LAN rather than anything
  wrong with this app's Docker setup — confirmed once during development,
  root-caused via `arping <ip>` showing *two different MAC addresses*
  answering for the same address (Docker's own containers use a
  `02:42:xx:xx:xx:xx` MAC convention, which made the collision visible).
  If `arping` shows more than one reply, reassign the host/LXC to a free
  IP rather than debugging firewall rules first.
- **Update button is missing/disabled**: `docker-compose.yml`'s `- .:/app`
  bind mount is commented out, or `/app/.git` doesn't exist for some other
  reason (e.g. deployed from a tarball rather than `git clone`) — see
  "Self-update from the UI" above.
- **`git pull` fails inside the container with a permission or "dubious
  ownership" error**: the container runs as root (see `Dockerfile`), so
  ownership mismatches are usually not the issue — more likely the repo
  has local modifications or diverged history. `git -C . status` on the
  host (same directory) will show what's blocking the fast-forward.
