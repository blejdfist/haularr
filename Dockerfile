# ---- Stage 1: Build SvelteKit frontend ----
FROM node:22-slim AS frontend-build

WORKDIR /app/frontend

# Install pnpm
RUN npm install -g pnpm@12

# Copy package files
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy frontend source
COPY frontend/ ./

# Build static output
RUN pnpm run build

# ---- Stage 2: Build the wheel ----
FROM python:3.14-slim AS python-build

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never

# git provides the version; autocrlf keeps a Windows checkout from looking modified
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --global core.autocrlf true

# Locked dependency versions and hashes, for the runtime stage to install
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o requirements.txt

# The wheel carries the frontend as app/static. Sources are mounted, so neither
# they nor .git end up in a layer.
RUN --mount=type=bind,target=/app,rw \
    --mount=from=frontend-build,source=/app/frontend/build,target=/tmp/static \
    cp -r /tmp/static backend/app/static \
    && uv build --wheel --out-dir /dist

# ---- Stage 3: Python runtime ----
FROM python:3.14-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    7zip \
    unrar-free \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN --mount=from=python-build,source=/app/requirements.txt,target=/tmp/requirements.txt \
    pip install --no-cache-dir --root-user-action=ignore -r /tmp/requirements.txt

RUN --mount=from=python-build,source=/dist,target=/tmp/dist \
    pip install --no-cache-dir --root-user-action=ignore --no-deps /tmp/dist/*.whl

# Create config directory
RUN mkdir -p /config

# Default environment
ENV HAULARR_CONFIG_DIR=/config \
    HAULARR_HOST=0.0.0.0 \
    HAULARR_PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

# Run as non-root by default (can be overridden with --user or PUID/PGID)
# The entrypoint handles PUID/PGID if needed
ENTRYPOINT ["python", "-m", "app.main"]
