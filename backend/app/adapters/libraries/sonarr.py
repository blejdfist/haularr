"""Sonarr v5 Library Adapter.

API prefix: /api/v5
Endpoints used: parse, series, episode, episodefile, manualimport, command, history

Important:
- A parse response does NOT guarantee the series is registered. We always
  cross-check against /api/v5/series to confirm catalog existence.
- Quality upgrade decisions require a supported side-effect-free API call;
  if none is definitively available, return EligibilityDecision.INCONCLUSIVE.
- Never auto-register. Never invoke release-grabbing endpoints.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.domain.models import (
    EligibilityAssessment,
    EligibilityDecision,
    ImportCandidate,
    ImportInspection,
    ImportOperation,
    ImportOutcome,
    LibraryInventory,
    MediaMatch,
    MediaType,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v5"


class SonarrAdapter:
    """Sonarr v5 Library Adapter."""

    def __init__(
        self,
        library_id: str,
        base_url: str,
        api_key: str,
        tls_verify: bool = True,
    ) -> None:
        self.library_id = library_id
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._tls_verify = tls_verify

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"X-Api-Key": self._api_key},
            verify=self._tls_verify,
            timeout=httpx.Timeout(30.0),
        )

    async def _get(self, path: str, **params: Any) -> Any:
        async with self._make_client() as client:
            resp = await client.get(f"{API_PREFIX}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def _post(self, path: str, json: Any) -> Any:
        async with self._make_client() as client:
            resp = await client.post(f"{API_PREFIX}{path}", json=json)
            resp.raise_for_status()
            return resp.json()

    async def test_connection(self) -> dict:
        try:
            status_data = await self._get("/system/status")
            return {
                "ok": True,
                "version": status_data.get("version", "unknown"),
                "adapter": "sonarr",
                "app_name": status_data.get("appName", "Sonarr"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "adapter": "sonarr"}

    async def parse(self, release_name: str) -> MediaMatch:
        """Parse release name via Sonarr's /parse endpoint.

        A successful parse does NOT mean the series is registered.
        We require a catalog cross-check.
        """
        try:
            data = await self._get("/parse", title=release_name)
        except Exception as exc:
            logger.debug("Sonarr parse failed for %r: %s", release_name, exc)
            return MediaMatch(
                media_type=MediaType.UNKNOWN,
                confidence=0.0,
                parse_data={"error": str(exc)},
            )

        series_data = data.get("series")
        episodes = data.get("episodes", [])
        parsed_info = data.get("parsedEpisodeInfo", {})

        if not series_data or not series_data.get("id"):
            # Parse found something but no registered series
            return MediaMatch(
                media_type=MediaType.SERIES,
                catalog_id=None,
                title=parsed_info.get("seriesTitle", ""),
                episode_ids=[],
                parse_data=parsed_info,
                confidence=0.3,
                ambiguous=False,
            )

        episode_ids = [ep["id"] for ep in episodes if ep.get("id")]
        return MediaMatch(
            media_type=MediaType.SERIES,
            catalog_id=series_data["id"],
            title=series_data.get("title", ""),
            year=series_data.get("year"),
            episode_ids=episode_ids,
            parse_data=parsed_info,
            confidence=0.9 if episode_ids else 0.6,
            ambiguous=len(episode_ids) == 0 and bool(series_data.get("id")),
        )

    async def inspect_library(self, match: MediaMatch) -> LibraryInventory:
        """Check if the parsed series/episodes are present in the library."""
        if match.catalog_id is None:
            return LibraryInventory(
                catalog_id=0,
                title=match.title,
                registered=False,
                has_file=False,
            )

        # Verify the series actually exists
        try:
            series = await self._get(f"/series/{match.catalog_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return LibraryInventory(
                    catalog_id=match.catalog_id,
                    title=match.title,
                    registered=False,
                    has_file=False,
                )
            raise

        # Fetch episodes
        episodes = await self._get("/episode", seriesId=match.catalog_id)
        episode_files = await self._get("/episodefile", seriesId=match.catalog_id)
        file_episode_ids = {ef["episodeId"] for ef in episode_files if ef.get("episodeId")}

        # Determine which of the matched episode_ids are missing
        all_episode_ids = {ep["id"] for ep in episodes}
        missing = []
        for ep_id in (match.episode_ids or []):
            if ep_id not in file_episode_ids:
                missing.append(ep_id)

        # Season summary
        season_counts: dict[str, int] = {}
        for ep in episodes:
            season = str(ep.get("seasonNumber", 0))
            season_counts[season] = season_counts.get(season, 0) + (
                1 if ep["id"] in file_episode_ids else 0
            )

        return LibraryInventory(
            catalog_id=match.catalog_id,
            title=series.get("title", match.title),
            registered=True,
            has_file=len(file_episode_ids) > 0,
            episode_counts=season_counts,
            missing_episode_ids=missing,
            existing_quality=None,  # Would need per-episode quality data
        )

    async def evaluate_candidate(
        self, match: MediaMatch, metadata: dict
    ) -> EligibilityAssessment:
        """
        Evaluate if a candidate qualifies as an upgrade.

        Sonarr v5 does not expose a documented side-effect-free pre-flight
        upgrade check for arbitrary remote files. We return INCONCLUSIVE
        to avoid auto-downloading based on our own heuristics.
        Post-transfer inspection via ManualImport is authoritative.
        """
        return EligibilityAssessment(
            decision=EligibilityDecision.INCONCLUSIVE,
            evidence={
                "reason": "No side-effect-free pre-flight upgrade check available in Sonarr v5",
                "recommendation": "Use post-transfer ManualImport inspection",
            },
            capability_used="none",
        )

    async def inspect_import(
        self, ready_path: str, match: MediaMatch
    ) -> ImportInspection:
        """Inspect files at ready_path using Sonarr's ManualImport GET."""
        if match.catalog_id is None:
            return ImportInspection(all_rejected=True)

        try:
            candidates_raw = await self._get(
                "/manualimport",
                folder=ready_path,
                seriesId=match.catalog_id,
            )
        except Exception as exc:
            logger.error("Sonarr inspect_import failed: %s", exc)
            return ImportInspection(all_rejected=True)

        candidates = []
        for item in (candidates_raw or []):
            path = item.get("path", "")
            rejections = [r.get("reason", "") for r in item.get("rejections", [])]
            episode_ids = [ep["id"] for ep in item.get("episodes", []) if ep.get("id")]
            quality = item.get("quality", {}).get("quality", {}).get("name", "")
            custom_formats = [cf.get("name", "") for cf in item.get("customFormats", [])]
            media_id = match.catalog_id

            candidates.append(
                ImportCandidate(
                    relative_path=path,
                    absolute_path=path,
                    quality=quality,
                    custom_formats=custom_formats,
                    rejection_reasons=rejections,
                    media_id=media_id,
                    episode_ids=episode_ids,
                )
            )

        all_rejected = all(bool(c.rejection_reasons) for c in candidates) if candidates else True
        return ImportInspection(candidates=candidates, all_rejected=all_rejected)

    async def submit_import(self, selected_candidates: list) -> ImportOperation:
        """Submit accepted candidates via ManualImport command."""
        files = []
        for c in selected_candidates:
            files.append({
                "path": c.absolute_path,
                "seriesId": c.media_id,
                "episodeIds": c.episode_ids,
                "quality": {"quality": {"id": 0}},  # Let Sonarr determine
                "languages": [],
                "releaseGroup": "",
                "downloadId": None,
            })

        body = {
            "name": "ManualImport",
            "files": files,
            "importMode": "Move",
        }

        result = await self._post("/command", body)
        command_id = result.get("id")
        return ImportOperation(
            operation_id=str(command_id),
            command_id=command_id,
            submitted_at=datetime.now(timezone.utc),
            candidates=[c.absolute_path for c in selected_candidates],
        )

    async def reconcile_import(
        self, operation: ImportOperation, match: MediaMatch
    ) -> ImportOutcome:
        """Confirm import by checking command status and library state."""
        if not operation.command_id:
            return ImportOutcome(success=False, details={"error": "No command ID"})

        try:
            cmd = await self._get(f"/command/{operation.command_id}")
        except Exception as exc:
            return ImportOutcome(
                success=False,
                details={"error": str(exc), "command_id": operation.command_id},
            )

        cmd_status = cmd.get("status", "unknown")
        if cmd_status == "completed":
            # Check actual episode files in library to confirm
            if match.catalog_id:
                try:
                    ep_files = await self._get(
                        "/episodefile", seriesId=match.catalog_id
                    )
                    imported = [ef.get("path", "") for ef in ep_files]
                    return ImportOutcome(
                        success=True,
                        imported_paths=imported,
                        details={"command_status": cmd_status},
                    )
                except Exception:
                    pass
            return ImportOutcome(success=True, details={"command_status": cmd_status})
        elif cmd_status in ("failed", "aborted"):
            return ImportOutcome(
                success=False,
                details={"command_status": cmd_status, "body": cmd},
            )
        else:
            # Still running
            return ImportOutcome(
                success=False,
                details={"command_status": cmd_status, "pending": True},
            )
