"""In-memory ring buffer of recent application log records.

The application writes logs to stdout/stderr (see ``lifespan`` in ``app.main``).
This module adds a second, process-wide :class:`logging.Handler` attached to the
root logger that keeps the most recent records in memory so they can be served
to the UI via the ``/logs`` API endpoint.

The buffer is bounded (a ``deque`` with ``maxlen``) so memory stays constant
regardless of uptime. It is thread-safe; log records may originate from worker
threads (``asyncio.to_thread``) and uvicorn's access logs.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

DEFAULT_CAPACITY = 1000

# Level name -> numeric value, ordered so a minimum level can filter by name.
_LEVEL_NO: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class LogBufferHandler(logging.Handler):
    """Captures the most recent log records in an in-memory ring buffer.

    Records are stored oldest-first (appended on the right); :meth:`snapshot`
    returns them newest-first for display.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        super().__init__()
        self._buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        # Bumped on every record: lets clients (SSE) notice new logs without fetching them.
        self.seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: dict[str, Any] = {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                entry["exception"] = (
                    logging.Formatter().formatException(record.exc_info).rstrip()
                )
        except Exception:
            # A logging handler must never break the application.
            return
        with self._lock:
            self._buffer.append(entry)
            self.seq += 1

    def snapshot(
        self,
        *,
        level: str | None = None,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return matching entries, newest-first.

        - ``level``: minimum severity (e.g. ``"WARNING"`` keeps WARNING and above).
        - ``search``: case-insensitive substring matched against message and logger.
        - ``limit``: cap on the number of returned entries.
        """
        with self._lock:
            items = list(self._buffer)
        items.reverse()  # newest first

        if level:
            min_no = _LEVEL_NO.get(str(level).upper())
            if min_no is not None:
                items = [e for e in items if _LEVEL_NO.get(e["level"], 0) >= min_no]

        if search:
            needle = search.lower()
            items = [
                e
                for e in items
                if needle in e["message"].lower()
                or needle in e["logger"].lower()
                or needle in e.get("exception", "").lower()
            ]

        if limit and limit > 0:
            items = items[:limit]
        return items

    def clear(self) -> None:
        """Drop every captured record (used by tests for deterministic output)."""
        with self._lock:
            self._buffer.clear()

    @property
    def capacity(self) -> int:
        return self._buffer.maxlen or DEFAULT_CAPACITY

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._buffer)


# ---------------------------------------------------------------------------
# Process-wide singleton accessor
# ---------------------------------------------------------------------------

_handler: LogBufferHandler | None = None
_install_lock = threading.Lock()

# Root, plus "uvicorn": its config sets propagate=False, so request crashes
# ("uvicorn.error") would otherwise never reach our handlers. "uvicorn.access"
# also doesn't propagate and stays out on purpose (one line per request).
_TARGETS = ("", "uvicorn")


def _attach(h: logging.Handler) -> None:
    for name in _TARGETS:
        lg = logging.getLogger(name)
        if h not in lg.handlers:
            lg.addHandler(h)


def _detach(h: logging.Handler) -> None:
    for name in _TARGETS:
        logging.getLogger(name).removeHandler(h)


def install_log_handler(capacity: int = DEFAULT_CAPACITY) -> LogBufferHandler:
    """Attach the buffer handler to the root logger (idempotent)."""
    global _handler
    with _install_lock:
        if _handler is None:
            _handler = LogBufferHandler(capacity)
        _attach(_handler)
    return _handler


def remove_log_handler() -> None:
    """Detach the buffer handler (called on shutdown)."""
    global _handler
    with _install_lock:
        if _handler is not None:
            _detach(_handler)
            _handler = None


# ---------------------------------------------------------------------------
# Rotating log file
# ---------------------------------------------------------------------------

_file_handler: RotatingFileHandler | None = None


def install_file_handler(path: Path, max_bytes: int, backups: int) -> RotatingFileHandler:
    """Mirror the root logger to ``path``, rotated at ``max_bytes`` keeping ``backups`` old files."""
    global _file_handler
    with _install_lock:
        if _file_handler is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            _file_handler = RotatingFileHandler(
                path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            _file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
            )
            _attach(_file_handler)
    return _file_handler


def remove_file_handler() -> None:
    global _file_handler
    with _install_lock:
        if _file_handler is not None:
            _detach(_file_handler)
            _file_handler.close()
            _file_handler = None


def get_log_handler() -> LogBufferHandler | None:
    """Return the installed handler, or ``None`` if not yet installed."""
    return _handler
