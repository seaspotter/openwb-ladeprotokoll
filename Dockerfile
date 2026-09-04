FROM python:3.12-slim

WORKDIR /app

# git: needed by app/updater.py's `git pull` against the repo checkout that
# docker-compose.yml bind-mounts onto this same WORKDIR for self-update.
# tzdata: without it, setting TZ (see docker-compose.yml) has nothing to
# resolve against, and datetime.now() (report generation timestamps) stays
# on the container's default UTC regardless of TZ.
# libpango/libcairo/libgdk-pixbuf/fonts-liberation/shared-mime-info: WeasyPrint's
# own system dependencies for HTML->PDF rendering (app/pdf_render.py) -- these
# aren't pip-installable, unlike the rest of requirements.txt.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git tzdata \
    libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0 \
    libgdk-pixbuf2.0-0 libcairo2 fonts-liberation shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# All our Python dependencies have prebuilt wheels for amd64 and arm64 -- the
# two platforms this image targets (see .github/workflows/docker-publish.yml)
# -- so no compiler/build stage is needed here.
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt
ENV PATH=/root/.local/bin:$PATH

COPY app ./app

# The bind-mounted repo checkout (see docker-compose.yml) is owned by
# whatever UID/GID it has on the Docker host, not root (which this
# container runs as) -- without this, git refuses every command against it
# ("detected dubious ownership in repository at '/app'"), which would make
# the version display silently show "unknown" instead of a real git describe.
RUN git config --system --add safe.directory /app

# Baked-in fallback for the settings panel's version display when there's no
# live git checkout at /app to read a commit from -- e.g. a plain `docker
# run`/registry-image deployment without docker-compose.yml's repo bind-mount.
# Set from CI, see .github/workflows/docker-publish.yml.
ARG VERSION=unknown
ENV OPENWB_LADEPROTOKOLL_IMAGE_VERSION=$VERSION

# Runs as root: the bind-mounted repo checkout (see docker-compose.yml) is
# owned by whatever UID/GID it has on the Docker host, and self-update's
# `git pull` needs to write to it. No Docker socket is involved.

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
