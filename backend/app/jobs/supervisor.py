"""Discovery supervisor — runs periodic source polling loops.

One background loop per source, with per-source poll intervals.
Sources being offline do not block other sources.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.settings import Settings

from app.logging_buffer import named

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoverySupervisor:
    """Manages discovery polling tasks for all enabled sources."""

    def __init__(self, settings: Settings, master_key: bytes) -> None:
        self.settings = settings
        self.master_key = master_key
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False
        self._coordinator_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the coordinator that manages per-source polling tasks."""
        if self._running:
            return
        self._running = True
        self._coordinator_task = asyncio.create_task(self._coordinator_loop())
        logger.info("Discovery supervisor started")

    async def stop(self) -> None:
        """Stop all discovery tasks gracefully."""
        self._running = False
        if self._coordinator_task:
            self._coordinator_task.cancel()
            try:
                await asyncio.wait_for(self._coordinator_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        for source_id, task in list(self._tasks.items()):
            task.cancel()
            try:
                await asyncio.wait_for(task, timeout=10.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        self._tasks.clear()
        logger.info("Discovery supervisor stopped")

    async def trigger_scan(self, source_id: str) -> None:
        """Trigger an immediate scan for a source (outside normal polling)."""
        from app.services.discovery import DiscoveryService

        svc = DiscoveryService(self.settings, self.master_key)
        try:
            counts = await svc.run_discovery_for_source(source_id)
            logger.info("Triggered scan for %s: %s", svc.source_label or source_id, counts)
        except Exception as exc:
            logger.warning("Triggered scan error for %s: %s", svc.source_label or source_id, exc)

    async def _coordinator_loop(self) -> None:
        """Periodically reconcile the set of active polling tasks with enabled sources."""
        while self._running:
            try:
                await self._reconcile_tasks()
            except Exception:
                logger.exception("Coordinator error")
            # Check every 60s for new/removed sources
            await asyncio.sleep(60)

    async def _reconcile_tasks(self) -> None:
        """Start/stop per-source tasks based on current DB config."""
        from app.database.session import get_session_factory
        from app.database.models import SourceInstance
        from sqlalchemy import select

        factory = get_session_factory(self.settings)
        async with factory() as session:
            result = await session.execute(
                select(SourceInstance).where(SourceInstance.enabled == True)  # noqa: E712
            )
            enabled_sources = {s.id: (s.poll_interval, named(s.name, s.id)) for s in result.scalars().all()}

        # Start tasks for new sources
        for source_id, (poll_interval, label) in enabled_sources.items():
            if source_id not in self._tasks or self._tasks[source_id].done():
                self._tasks[source_id] = asyncio.create_task(
                    self._source_poll_loop(source_id, poll_interval, label)
                )

        # Stop tasks for removed/disabled sources
        for source_id in list(self._tasks.keys()):
            if source_id not in enabled_sources:
                task = self._tasks.pop(source_id)
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

    async def _source_poll_loop(self, source_id: str, initial_interval: int, label: str) -> None:
        """Poll a single source at its configured interval."""
        from app.services.discovery import DiscoveryService

        logger.info("Starting poll loop for source %s (interval=%ds)", label, initial_interval)

        while self._running:
            try:
                svc = DiscoveryService(self.settings, self.master_key)
                await svc.run_discovery_for_source(source_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Poll loop error for source %s", label)

            # Re-read the poll interval from DB in case it changed
            try:
                interval = await self._get_poll_interval(source_id)
            except Exception:
                interval = initial_interval

            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

        logger.info("Poll loop stopped for source %s", label)

    async def _get_poll_interval(self, source_id: str) -> int:
        """Read the current poll interval from DB."""
        from app.database.session import get_session_factory
        from app.database.models import SourceInstance
        from sqlalchemy import select

        factory = get_session_factory(self.settings)
        async with factory() as session:
            result = await session.execute(
                select(SourceInstance.poll_interval).where(SourceInstance.id == source_id)
            )
            row = result.scalar_one_or_none()
            return row or self.settings.discovery_interval_seconds
