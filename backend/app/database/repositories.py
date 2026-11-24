"""Repository layer — all SQLAlchemy specifics live here.

Domain/services depend on these interfaces, not raw SQL.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Sequence

from sqlalchemy import select, update, func, and_, exists, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

_event_log = logging.getLogger("app.jobs.events")
_SEVERITY = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING,
             "error": logging.ERROR, "critical": logging.CRITICAL}

from app.database.models import (
    AppSetting,
    EligibilityCheck,
    FileImport,
    Job,
    JobEvent,
    JobFile,
    LibraryInstance,
    MediaMatch,
    NotificationDelivery,
    SourceInstance,
    SourceItem,
    SourceLabelRule,
    StageRun,
    TransferEndpoint,
    TransferInstance,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Source repositories
# ---------------------------------------------------------------------------


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> SourceInstance:
        obj = SourceInstance(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, source_id: str) -> SourceInstance | None:
        result = await self.session.execute(
            select(SourceInstance)
            .where(SourceInstance.id == source_id)
            .options(selectinload(SourceInstance.label_rules))
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[SourceInstance]:
        result = await self.session.execute(
            select(SourceInstance)
            .options(selectinload(SourceInstance.label_rules))
            .order_by(SourceInstance.created_at)
        )
        return result.scalars().all()

    async def update(self, source_id: str, **kwargs: Any) -> SourceInstance | None:
        kwargs["updated_at"] = _utcnow()
        await self.session.execute(
            update(SourceInstance).where(SourceInstance.id == source_id).values(**kwargs)
        )
        return await self.get(source_id)

    async def delete(self, source_id: str) -> None:
        obj = await self.get(source_id)
        if obj:
            await self.session.delete(obj)


class LabelRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> SourceLabelRule:
        obj = SourceLabelRule(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, rule_id: str) -> SourceLabelRule | None:
        result = await self.session.execute(
            select(SourceLabelRule).where(SourceLabelRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def get_by_source_label(
        self, source_id: str, label: str
    ) -> SourceLabelRule | None:
        result = await self.session.execute(
            select(SourceLabelRule).where(
                and_(
                    SourceLabelRule.source_id == source_id,
                    SourceLabelRule.label == label,
                    SourceLabelRule.enabled == True,  # noqa: E712
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_source(self, source_id: str) -> Sequence[SourceLabelRule]:
        result = await self.session.execute(
            select(SourceLabelRule)
            .where(SourceLabelRule.source_id == source_id)
            .order_by(SourceLabelRule.priority.desc(), SourceLabelRule.label)
        )
        return result.scalars().all()

    async def update(self, rule_id: str, **kwargs: Any) -> SourceLabelRule | None:
        kwargs["updated_at"] = _utcnow()
        await self.session.execute(
            update(SourceLabelRule).where(SourceLabelRule.id == rule_id).values(**kwargs)
        )
        return await self.get(rule_id)

    async def delete(self, rule_id: str) -> None:
        obj = await self.get(rule_id)
        if obj:
            await self.session.delete(obj)


# ---------------------------------------------------------------------------
# Transfer repositories
# ---------------------------------------------------------------------------


class TransferRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> TransferInstance:
        obj = TransferInstance(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, transfer_id: str) -> TransferInstance | None:
        result = await self.session.execute(
            select(TransferInstance)
            .where(TransferInstance.id == transfer_id)
            .options(selectinload(TransferInstance.endpoints))
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[TransferInstance]:
        result = await self.session.execute(
            select(TransferInstance)
            .options(selectinload(TransferInstance.endpoints))
            .order_by(TransferInstance.created_at)
        )
        return result.scalars().all()

    async def update(self, transfer_id: str, **kwargs: Any) -> TransferInstance | None:
        kwargs["updated_at"] = _utcnow()
        await self.session.execute(
            update(TransferInstance)
            .where(TransferInstance.id == transfer_id)
            .values(**kwargs)
        )
        return await self.get(transfer_id)

    async def add_endpoint(self, transfer_id: str, **kwargs: Any) -> TransferEndpoint:
        obj = TransferEndpoint(transfer_id=transfer_id, **kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj


# ---------------------------------------------------------------------------
# Library repositories
# ---------------------------------------------------------------------------


class LibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> LibraryInstance:
        obj = LibraryInstance(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, library_id: str) -> LibraryInstance | None:
        result = await self.session.execute(
            select(LibraryInstance).where(LibraryInstance.id == library_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[LibraryInstance]:
        result = await self.session.execute(
            select(LibraryInstance).order_by(LibraryInstance.created_at)
        )
        return result.scalars().all()

    async def update(self, library_id: str, **kwargs: Any) -> LibraryInstance | None:
        kwargs["updated_at"] = _utcnow()
        await self.session.execute(
            update(LibraryInstance)
            .where(LibraryInstance.id == library_id)
            .values(**kwargs)
        )
        return await self.get(library_id)


# ---------------------------------------------------------------------------
# Source item repositories
# ---------------------------------------------------------------------------


class SourceItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self, source_id: str, remote_id: str, **kwargs: Any
    ) -> tuple[SourceItem, bool]:
        """Create or update a source item. Returns (item, created)."""
        result = await self.session.execute(
            select(SourceItem).where(
                and_(
                    SourceItem.source_id == source_id,
                    SourceItem.remote_id == remote_id,
                )
            )
        )
        existing = result.scalar_one_or_none()
        if existing is None:
            obj = SourceItem(source_id=source_id, remote_id=remote_id, **kwargs)
            self.session.add(obj)
            await self.session.flush()
            return obj, True
        else:
            kwargs["last_seen_at"] = _utcnow()
            for k, v in kwargs.items():
                setattr(existing, k, v)
            await self.session.flush()
            return existing, False

    async def get(self, item_id: str) -> SourceItem | None:
        result = await self.session.execute(
            select(SourceItem)
            .where(SourceItem.id == item_id)
            .options(
                selectinload(SourceItem.media_matches),
                selectinload(SourceItem.eligibility_checks),
            )
        )
        return result.scalar_one_or_none()

    async def list_filtered(
        self,
        source_id: str | None = None,
        label: str | None = None,
        eligibility: str | None = None,
        search: str | None = None,
        has_job: bool | None = None,
        include_ignored: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Sequence[SourceItem], int]:
        query = select(SourceItem)
        count_query = select(func.count()).select_from(SourceItem)

        conditions = []
        if source_id:
            conditions.append(SourceItem.source_id == source_id)
        if label:
            # JSON contains check — SQLite compatible
            conditions.append(SourceItem.labels_json.contains([label]))
        if eligibility:
            conditions.append(SourceItem.last_eligibility == eligibility)
        if search:
            conditions.append(SourceItem.title.ilike(f"%{search}%"))
        if has_job is not None:
            job_exists = exists(select(Job.id).where(Job.source_item_id == SourceItem.id))
            conditions.append(job_exists if has_job else ~job_exists)
        if not include_ignored:
            conditions.append(SourceItem.ignored_at.is_(None))

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        query = (
            query.order_by(SourceItem.first_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return result.scalars().all(), total

    async def update(self, item_id: str, **kwargs: Any) -> SourceItem | None:
        await self.session.execute(
            update(SourceItem).where(SourceItem.id == item_id).values(**kwargs)
        )
        return await self.get(item_id)

    async def save_media_match(
        self,
        source_item_id: str,
        library_instance_id: str | None,
        **kwargs: Any,
    ) -> MediaMatch:
        # Remove old matches for this item+library combo
        existing = await self.session.execute(
            select(MediaMatch).where(
                and_(
                    MediaMatch.source_item_id == source_item_id,
                    MediaMatch.library_instance_id == library_instance_id,
                )
            )
        )
        for old in existing.scalars().all():
            await self.session.delete(old)

        match = MediaMatch(
            source_item_id=source_item_id,
            library_instance_id=library_instance_id,
            **kwargs,
        )
        self.session.add(match)
        await self.session.flush()
        return match

    async def save_eligibility_check(
        self, source_item_id: str, **kwargs: Any
    ) -> EligibilityCheck:
        check = EligibilityCheck(source_item_id=source_item_id, **kwargs)
        self.session.add(check)
        await self.session.flush()
        return check


# ---------------------------------------------------------------------------
# Job repositories
# ---------------------------------------------------------------------------


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, **kwargs: Any) -> Job:
        obj = Job(**kwargs)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get(self, job_id: str) -> Job | None:
        result = await self.session.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(
                selectinload(Job.stage_runs),
                selectinload(Job.job_files),
                selectinload(Job.events),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_item(self, source_item_id: str) -> Job | None:
        """Return non-terminal job for source item (at most one)."""
        result = await self.session.execute(
            select(Job).where(
                and_(
                    Job.source_item_id == source_item_id,
                    Job.ended_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def has_cancelled_for_item(self, source_item_id: str) -> bool:
        result = await self.session.execute(
            select(Job.id)
            .where(Job.source_item_id == source_item_id, Job.status == "cancelled")
            .limit(1)
        )
        return result.first() is not None

    async def list_filtered(
        self,
        status: list[str] | None = None,
        stage: str | None = None,
        source_id: str | None = None,
        offset: int = 0,
        limit: int = 50,
        sort: str = "newest",
    ) -> tuple[Sequence[Job], int]:
        # Join source item to filter by source
        query = select(Job)
        count_query = select(func.count()).select_from(Job)

        conditions = []
        if status:
            conditions.append(Job.status.in_(status))
        if stage:
            conditions.append(Job.stage == stage)
        if source_id:
            query = query.join(SourceItem, Job.source_item_id == SourceItem.id)
            count_query = count_query.join(SourceItem, Job.source_item_id == SourceItem.id)
            conditions.append(SourceItem.source_id == source_id)

        if conditions:
            query = query.where(and_(*conditions))
            count_query = count_query.where(and_(*conditions))

        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()

        order = [Job.created_at.desc()]
        if sort == "attention":
            order.insert(0, case((Job.status.in_(["failed", "needs_attention"]), 0), else_=1))
        query = (
            query.order_by(*order)
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(query)
        return result.scalars().all(), total

    async def claim_next(
        self,
        stage: str,
        worker_token: str,
        lease_until: datetime,
        now: datetime,
    ) -> Job | None:
        """Atomic claim of the next eligible job for a given stage."""
        # Find candidate IDs
        subq = (
            select(Job.id)
            .where(
                and_(
                    Job.stage == stage,
                    Job.ended_at.is_(None),
                    or_(
                        Job.status == "queued",
                        and_(
                            Job.status == "retry_wait",
                            Job.next_run_at <= now,
                        ),
                    ),
                )
            )
            .order_by(Job.priority.desc(), Job.created_at.asc())
            .limit(1)
        )
        # Atomic update
        result = await self.session.execute(
            update(Job)
            .where(
                and_(
                    Job.id.in_(subq),
                    or_(
                        Job.status == "queued",
                        and_(
                            Job.status == "retry_wait",
                            Job.next_run_at <= now,
                        ),
                    ),
                )
            )
            .values(
                status="running",
                worker_token=worker_token,
                lease_expires_at=lease_until,
                updated_at=_utcnow(),
            )
            .returning(Job.id)
        )
        row = result.fetchone()
        if row is None:
            return None
        await self.session.commit()
        return await self.get(row[0])

    async def update(self, job_id: str, **kwargs: Any) -> Job | None:
        kwargs["updated_at"] = _utcnow()
        await self.session.execute(
            update(Job).where(Job.id == job_id).values(**kwargs)
        )
        return await self.get(job_id)

    async def add_event(self, job_id: str, **kwargs: Any) -> JobEvent:
        event = JobEvent(job_id=job_id, **kwargs)
        self.session.add(event)
        # Mirror into the application log so job activity shows in the logs view and file.
        _event_log.log(
            _SEVERITY.get(kwargs.get("severity", "info"), logging.INFO),
            "job %s %s%s: %s",
            job_id[:8],
            kwargs.get("kind", "event"),
            f" [{kwargs['stage']}]" if kwargs.get("stage") else "",
            kwargs.get("message", ""),
        )
        await self.session.flush()
        return event

    async def add_stage_run(self, job_id: str, **kwargs: Any) -> StageRun:
        run = StageRun(job_id=job_id, **kwargs)
        self.session.add(run)
        await self.session.flush()
        return run


# ---------------------------------------------------------------------------
# Settings repository
# ---------------------------------------------------------------------------


class SettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> Any | None:
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        obj = result.scalar_one_or_none()
        return obj.value_json if obj else None

    async def set(self, key: str, value: Any) -> None:
        result = await self.session.execute(
            select(AppSetting).where(AppSetting.key == key)
        )
        obj = result.scalar_one_or_none()
        if obj is None:
            obj = AppSetting(key=key, value_json=value)
            self.session.add(obj)
        else:
            obj.value_json = value
            obj.updated_at = _utcnow()
        await self.session.flush()

    async def get_all(self) -> dict[str, Any]:
        result = await self.session.execute(select(AppSetting))
        return {row.key: row.value_json for row in result.scalars().all()}
