# ---- Stage 1: Build SvelteKit frontend ----
FROM node:22-slim AS frontend-build

WORKDIR /app/frontend

# Install pnpm
RUN npm install -g pnpm

# Copy package files
COPY frontend/package.json frontend/pnpm-lock.yaml* ./

# Install dependencies
RUN pnpm install --frozen-lockfile || pnpm install

# Copy frontend source
COPY frontend/ ./

# Build static output
RUN pnpm run build

# ---- Stage 2: Python runtime ----
FROM python:3.13-slim AS runtime

# Install system dependencies
# libcurl for PyCURL, libarchive for archive extraction, sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev \
    libssl-dev \
    libarchive-tools \
    p7zip-full \
    unrar-free \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml uv.lock* ./
RUN pip install uv && \
    uv sync --no-dev --no-install-project

# Copy backend source
COPY backend/ ./backend/
COPY alembic.ini ./
COPY main.py ./

# Copy built frontend
COPY --from=frontend-build /app/frontend/build ./frontend/build

# Create config directory
RUN mkdir -p /config

# Default environment
ENV HAULARR_CONFIG_DIR=/config \
    HAULARR_HOST=0.0.0.0 \
    HAULARR_PORT=8080 \
    HAULARR_STATIC_DIR=/app/frontend/build \
    PYTHONPATH=/app

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/api/v1/health')" || exit 1

# Run as non-root by default (can be overridden with --user or PUID/PGID)
# The entrypoint handles PUID/PGID if needed
ENTRYPOINT ["python", "-m", "app.main"]
