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
                if needle in e["message"].lower() or needle in e["logger"].lower()
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


def install_log_handler(capacity: int = DEFAULT_CAPACITY) -> LogBufferHandler:
    """Attach the buffer handler to the root logger (idempotent)."""
    global _handler
    with _install_lock:
        if _handler is None:
            _handler = LogBufferHandler(capacity)
        root = logging.getLogger()
        if _handler not in root.handlers:
            root.addHandler(_handler)
    return _handler


def remove_log_handler() -> None:
    """Detach the buffer handler (called on shutdown)."""
    global _handler
    with _install_lock:
        if _handler is not None:
            logging.getLogger().removeHandler(_handler)
            _handler = None


def get_log_handler() -> LogBufferHandler | None:
    """Return the installed handler, or ``None`` if not yet installed."""
    return _handler
