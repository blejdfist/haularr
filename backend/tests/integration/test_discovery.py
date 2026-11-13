"""Test discovery service and classification pipeline.

Acceptance criteria:
4. First scan inventories without auto-queuing (zero jobs created).
5. Adding a new source later doesn't change established sources.
6. Newly completed, labeled, registered, missing media creates exactly one job after onboarding.
7. Unknown/unregistered media never auto-queues.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.database.models import Job, SourceItem
from app.database.repositories import (
    JobRepository,
    LabelRuleRepository,
    LibraryRepository,
    SourceItemRepository,
    SourceRepository,
)
from app.domain.models import (
    EligibilityDecision,
    EligibilityStatus,
    LibraryInventory,
    MediaMatch,
    MediaType,
    OnboardingState,
    RemoteFileDTO,
    SourceItemDTO,
    SourceStatus,
)
from app.services.classification import classify_item


class FakeLibraryAdapter:
    """Fake adapter for classification tests."""

    def __init__(
        self,
        ok: bool = True,
        match: MediaMatch | None = None,
        inventory: LibraryInventory | None = None,
    ):
        self._ok = ok
        self._match = match
        self._inventory = inventory

    async def test_connection(self) -> dict:
        return {"ok": self._ok}

    async def parse(self, release_name: str) -> MediaMatch:
        return self._match or MediaMatch(
            media_type=MediaType.SERIES,
            catalog_id=1,
            title="Test Show",
            episode_ids=[1, 2],
        )

    async def inspect_library(self, match: MediaMatch) -> LibraryInventory:
        return self._inventory or LibraryInventory(
            catalog_id=1,
            title="Test Show",
            registered=True,
            has_file=False,
            missing_episode_ids=[1, 2],
        )

    async def evaluate_candidate(self, match, metadata) -> object:
        from app.domain.models import EligibilityAssessment
        return EligibilityAssessment(decision=EligibilityDecision.INCONCLUSIVE)


@pytest.mark.asyncio
async def test_classify_missing_media(app, settings):
    """Classification correctly identifies missing media."""
    from app.database.session import get_session_factory
    from app.database.models import LibraryInstance, SourceInstance, SourceLabelRule

    factory = get_session_factory(settings)
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        # Create library
        library = LibraryInstance(
            name="Sonarr",
            adapter_type="sonarr",
            base_url="http://sonarr:8989",
            api_key_secret_ref="test-key",
        )
        session.add(library)
        await session.flush()
        rule.library_instance_id = library.id

        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Show.S01E01.1080p",
            labels_json=["tv"],
            source_status="completed",
        )
        await session.commit()

        # Reload for classification
        item = await item_repo.get(item.id)
        rule = (await label_repo.list_by_source(source.id))[0]
        rule.library_instance_id = library.id

        # Patch library adapter creation
        fake_adapter = FakeLibraryAdapter()
        with patch("app.services.classification.create_library_adapter", return_value=fake_adapter):
            status = await classify_item(session, item, rule, library, b"\x00" * 32)

        await session.commit()

    assert status == EligibilityStatus.MISSING.value

    # Check eligibility was persisted
    async with factory() as session:
        item_repo = SourceItemRepository(session)
        updated = await item_repo.get(item.id)
        assert updated.last_eligibility == EligibilityStatus.MISSING.value


@pytest.mark.asyncio
async def test_classify_not_registered(app, settings):
    """Classification correctly identifies unregistered media — never auto-queues."""
    from app.database.session import get_session_factory
    from app.database.models import LibraryInstance

    factory = get_session_factory(settings)
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        library = LibraryInstance(
            name="Sonarr",
            adapter_type="sonarr",
            base_url="http://sonarr:8989",
            api_key_secret_ref="test-key",
        )
        session.add(library)
        await session.flush()
        rule.library_instance_id = library.id

        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Unknown.Show.S01E01",
            labels_json=["tv"],
            source_status="completed",
        )
        await session.commit()

        item = await item_repo.get(item.id)
        rule = (await label_repo.list_by_source(source.id))[0]
        rule.library_instance_id = library.id

        # Adapter returns no catalog_id (not registered)
        fake_adapter = FakeLibraryAdapter(
            match=MediaMatch(media_type=MediaType.SERIES, catalog_id=None, title="Unknown Show")
        )
        with patch("app.services.classification.create_library_adapter", return_value=fake_adapter):
            status = await classify_item(session, item, rule, library, b"\x00" * 32)

        await session.commit()

    assert status == EligibilityStatus.NOT_REGISTERED.value


@pytest.mark.asyncio
async def test_classify_already_available(app, settings):
    """Already-available media is marked correctly — no auto-queue."""
    from app.database.session import get_session_factory
    from app.database.models import LibraryInstance

    factory = get_session_factory(settings)
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test",
            adapter_type="rtorrent",
            connection_config_json={}, credential_ref="",
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="movies",
            temporary_directory="/tmp",
            completed_directory="/tmp",
        )
        library = LibraryInstance(
            name="Radarr",
            adapter_type="radarr",
            base_url="http://radarr:7878",
            api_key_secret_ref="test-key",
        )
        session.add(library)
        await session.flush()
        rule.library_instance_id = library.id

        item_repo = SourceItemRepository(session)
        item, _ = await item_repo.upsert(
            source_id=source.id,
            remote_id="hash1",
            title="Test.Movie.2024.1080p",
            labels_json=["movies"],
            source_status="completed",
        )
        await session.commit()

        item = await item_repo.get(item.id)
        rule = (await label_repo.list_by_source(source.id))[0]
        rule.library_instance_id = library.id

        # Movie has file, upgrade is inconclusive → already_available / unconfirmed_upgrade
        fake_adapter = FakeLibraryAdapter(
            match=MediaMatch(media_type=MediaType.MOVIE, catalog_id=10, title="Test Movie"),
            inventory=LibraryInventory(
                catalog_id=10,
                title="Test Movie",
                registered=True,
                has_file=True,
                missing_episode_ids=[],
            ),
        )
        with patch("app.services.classification.create_library_adapter", return_value=fake_adapter):
            status = await classify_item(session, item, rule, library, b"\x00" * 32)

        await session.commit()

    # Inconclusive upgrade → unconfirmed_upgrade
    assert status == EligibilityStatus.UNCONFIRMED_UPGRADE.value


@pytest.mark.asyncio
async def test_no_auto_queue_before_onboarding(app, settings):
    """First scan: items classified but zero jobs created (onboarding not complete)."""
    from app.database.session import get_session_factory
    from app.services.discovery import DiscoveryService
    from app.database.models import SourceInstance, SourceLabelRule

    factory = get_session_factory(settings)

    # Create source in pending state
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test Source",
            adapter_type="rtorrent",
            connection_config_json={'xmlrpc_url': 'http://rt.example/RPC2'}, credential_ref='',
            onboarding_state=OnboardingState.PENDING.value,
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
            automatic_processing=True,  # Even if True, no auto-queue before onboarding
        )
        await session.commit()
        source_id = source.id

    # Fake source adapter
    fake_items = [
        SourceItemDTO(
            remote_id="hash1",
            name="Test.Show.S01E01.1080p",
            labels=["tv"],
            status=SourceStatus.COMPLETED,
            total_bytes=1000,
        ),
    ]

    # Fake library adapter returns missing
    fake_library_adapter = FakeLibraryAdapter()

    with (
        patch("app.adapters.sources.create_source_adapter") as mock_sa,
        patch("app.services.classification.create_library_adapter", return_value=fake_library_adapter),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.test_connection = AsyncMock(return_value={"ok": True})
        mock_adapter.list_items = AsyncMock(return_value=fake_items)
        mock_sa.return_value = mock_adapter

        svc = DiscoveryService(settings, b"\x00" * 32)
        counts = await svc.run_discovery_for_source(source_id)

    # Items discovered but no jobs queued (onboarding pending)
    assert counts["discovered"] == 1
    assert counts["new"] == 1
    assert counts["queued"] == 0

    # Source transitioned to awaiting_review
    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.get(source_id)
        assert source.onboarding_state == OnboardingState.AWAITING_REVIEW.value

    # Zero jobs created
    async with factory() as session:
        result = await session.execute(select(Job))
        jobs = result.scalars().all()
        assert len(jobs) == 0


@pytest.mark.asyncio
async def test_auto_queue_after_onboarding(app, settings):
    """After onboarding complete, missing eligible items are auto-queued."""
    from app.database.session import get_session_factory
    from app.services.discovery import DiscoveryService

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test Source",
            adapter_type="rtorrent",
            connection_config_json={'xmlrpc_url': 'http://rt.example/RPC2'}, credential_ref='',
            onboarding_state=OnboardingState.COMPLETED.value,  # Onboarding done
        )
        label_repo = LabelRuleRepository(session)
        rule = await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
            automatic_processing=True,
        )
        await session.commit()
        source_id = source.id

    fake_items = [
        SourceItemDTO(
            remote_id="hash1",
            name="Test.Show.S01E01.1080p",
            labels=["tv"],
            status=SourceStatus.COMPLETED,
            total_bytes=1000,
        ),
    ]

    fake_library_adapter = FakeLibraryAdapter()

    with (
        patch("app.adapters.sources.create_source_adapter") as mock_sa,
        patch("app.services.classification.create_library_adapter", return_value=fake_library_adapter),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.test_connection = AsyncMock(return_value={"ok": True})
        mock_adapter.list_items = AsyncMock(return_value=fake_items)
        mock_sa.return_value = mock_adapter

        svc = DiscoveryService(settings, b"\x00" * 32)
        counts = await svc.run_discovery_for_source(source_id)

    # Exactly one job created
    assert counts["queued"] == 1

    async with factory() as session:
        result = await session.execute(select(Job))
        jobs = result.scalars().all()
        assert len(jobs) == 1
        assert jobs[0].stage == "resolve_source"
        assert jobs[0].status == "queued"


@pytest.mark.asyncio
async def test_no_duplicate_jobs_on_rescan(app, settings):
    """Rescanning doesn't create duplicate jobs for already-queued items."""
    from app.database.session import get_session_factory
    from app.services.discovery import DiscoveryService

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test Source",
            adapter_type="rtorrent",
            connection_config_json={'xmlrpc_url': 'http://rt.example/RPC2'}, credential_ref='',
            onboarding_state=OnboardingState.COMPLETED.value,
        )
        label_repo = LabelRuleRepository(session)
        await label_repo.create(
            source_id=source.id,
            label="tv",
            temporary_directory="/tmp",
            completed_directory="/tmp",
            automatic_processing=True,
        )
        await session.commit()
        source_id = source.id

    fake_items = [
        SourceItemDTO(
            remote_id="hash1",
            name="Test.Show.S01E01.1080p",
            labels=["tv"],
            status=SourceStatus.COMPLETED,
            total_bytes=1000,
        ),
    ]

    fake_library_adapter = FakeLibraryAdapter()

    with (
        patch("app.adapters.sources.create_source_adapter") as mock_sa,
        patch("app.services.classification.create_library_adapter", return_value=fake_library_adapter),
    ):
        mock_adapter = AsyncMock()
        mock_adapter.test_connection = AsyncMock(return_value={"ok": True})
        mock_adapter.list_items = AsyncMock(return_value=fake_items)
        mock_sa.return_value = mock_adapter

        svc = DiscoveryService(settings, b"\x00" * 32)

        # First scan — creates one job
        counts1 = await svc.run_discovery_for_source(source_id)
        assert counts1["queued"] == 1

        # Second scan — no duplicate
        counts2 = await svc.run_discovery_for_source(source_id)
        assert counts2["queued"] == 0

    async with factory() as session:
        result = await session.execute(select(Job))
        jobs = result.scalars().all()
        assert len(jobs) == 1  # Still exactly one job


@pytest.mark.asyncio
async def test_unrouted_items_not_queued(app, settings):
    """Items with no matching label rule remain unrouted — never queued."""
    from app.database.session import get_session_factory
    from app.services.discovery import DiscoveryService

    factory = get_session_factory(settings)

    async with factory() as session:
        source_repo = SourceRepository(session)
        source = await source_repo.create(
            name="Test Source",
            adapter_type="rtorrent",
            connection_config_json={'xmlrpc_url': 'http://rt.example/RPC2'}, credential_ref='',
            onboarding_state=OnboardingState.COMPLETED.value,
        )
        # Only "movies" label rule, but item has "tv" label
        label_repo = LabelRuleRepository(session)
        await label_repo.create(
            source_id=source.id,
            label="movies",
            temporary_directory="/tmp",
            completed_directory="/tmp",
            automatic_processing=True,
        )
        await session.commit()
        source_id = source.id

    fake_items = [
        SourceItemDTO(
            remote_id="hash1",
            name="Test.Show.S01E01",
            labels=["tv"],  # No matching rule for "tv"
            status=SourceStatus.COMPLETED,
            total_bytes=1000,
        ),
    ]

    with patch("app.adapters.sources.create_source_adapter") as mock_sa:
        mock_adapter = AsyncMock()
        mock_adapter.test_connection = AsyncMock(return_value={"ok": True})
        mock_adapter.list_items = AsyncMock(return_value=fake_items)
        mock_sa.return_value = mock_adapter

        svc = DiscoveryService(settings, b"\x00" * 32)
        counts = await svc.run_discovery_for_source(source_id)

    assert counts["queued"] == 0

    # Item should be marked unrouted
    async with factory() as session:
        item_repo = SourceItemRepository(session)
        items, _ = await item_repo.list_filtered(source_id=source_id)
        assert len(items) == 1
        assert items[0].last_eligibility == EligibilityStatus.UNROUTED.value

