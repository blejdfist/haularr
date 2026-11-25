"""Sonarr v4 Library Adapter.

API prefix: /api/v3 (Sonarr v4; same as Radarr)
Endpoints used: parse, series, episode, episodefile, manualimport, command, history

Important:
- A parse response does NOT guarantee the series is registered. We always
  cross-check against /api/v3/series to confirm catalog existence.
- Library state (hasFile) comes from the /parse episode records; no upgrades.
- Never auto-register. Never invoke release-grabbing endpoints.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.domain.models import (
    ImportCandidate,
    ImportInspection,
    ImportOperation,
    ImportOutcome,
    LibraryInventory,
    MediaMatch,
    MediaType,
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v3"


class SonarrAdapter:
    """Sonarr v4 Library Adapter (/api/v3)."""

    def __init__(
        self,
        library_id: str,
        base_url: str,
        api_key: str,
        tls_verify: bool = True,
        import_mode: str = "Copy",
    ) -> None:
        self.library_id = library_id
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._tls_verify = tls_verify
        self._import_mode = import_mode

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
            app_name = status_data.get("appName")
            if app_name != "Sonarr":
                return {
                    "ok": False,
                    "error": f"Expected Sonarr, but connected to {app_name or 'unknown service'}.",
                    "adapter": "sonarr",
                }
            return {
                "ok": True,
                "version": status_data.get("version", "unknown"),
                "adapter": "sonarr",
                "app_name": app_name,
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
            library_record={"episodes": episodes},
            confidence=0.9 if episode_ids else 0.6,
            ambiguous=len(episode_ids) == 0 and bool(series_data.get("id")),
        )

    async def inspect_library(self, match: MediaMatch) -> LibraryInventory:
        """Derive library state from the /parse episode records (no HTTP)."""
        episodes = match.library_record.get("episodes", [])
        missing = [
            e["id"]
            for e in episodes
            if e.get("id") is not None and e["id"] in match.episode_ids and not e.get("hasFile")
        ]
        return LibraryInventory(
            catalog_id=match.catalog_id or 0,
            title=match.title,
            registered=match.catalog_id is not None,
            has_file=any(e.get("hasFile") for e in episodes),
            missing_episode_ids=missing,
        )

    async def inspect_import(self, ready_path: str, match: MediaMatch) -> ImportInspection:
        """Inspect files at ready_path using Sonarr's ManualImport GET.

        No catalog_id (the user skipped the library check, e.g. a multi-movie pack): each
        file goes to whatever Sonarr matched it to, and files it couldn't match are rejected.
        """
        try:
            # folder only: with seriesId (and no downloadId) Sonarr ignores folder and
            # scans the series' library folder instead (500 if it doesn't exist yet).
            candidates_raw = await self._get("/manualimport", folder=ready_path)
        except Exception as exc:
            logger.error("Sonarr inspect_import failed: %s", exc)
            return ImportInspection(all_rejected=True)

        candidates = []
        for item in candidates_raw or []:
            path = item.get("path", "")
            rejections = [r.get("reason", "") for r in item.get("rejections", [])]
            episode_ids = [ep["id"] for ep in item.get("episodes", []) if ep.get("id")]
            quality = item.get("quality", {}).get("quality", {}).get("name", "")
            custom_formats = [cf.get("name", "") for cf in item.get("customFormats", [])]
            series_id = (item.get("series") or {}).get("id")
            if match.catalog_id is None:
                if series_id is None:
                    rejections.append("Sonarr couldn't tell which series this is")
            elif series_id != match.catalog_id:
                rejections.append(f"Matched series {series_id}, expected {match.catalog_id}")

            candidates.append(
                ImportCandidate(
                    relative_path=path,
                    absolute_path=path,
                    quality=quality,
                    custom_formats=custom_formats,
                    rejection_reasons=rejections,
                    media_id=match.catalog_id or series_id,
                    episode_ids=episode_ids,
                    quality_model=item.get("quality") or {},
                    languages=item.get("languages") or [],
                    release_group=item.get("releaseGroup") or "",
                )
            )

        all_rejected = all(bool(c.rejection_reasons) for c in candidates) if candidates else True
        return ImportInspection(candidates=candidates, all_rejected=all_rejected)

    async def submit_import(
        self, selected_candidates: list, *, download_id: str | None = None
    ) -> ImportOperation:
        """Submit accepted candidates via ManualImport command."""
        files = []
        for c in selected_candidates:
            files.append(
                {
                    "path": c.absolute_path,
                    "seriesId": c.media_id,
                    "episodeIds": c.episode_ids,
                    "quality": c.quality_model,  # as detected by Sonarr in the GET
                    "languages": c.languages,
                    "releaseGroup": c.release_group,
                    **({"downloadId": download_id} if download_id else {}),
                }
            )

        body = {
            "name": "ManualImport",
            "files": files,
            "importMode": self._import_mode,
        }

        result = await self._post("/command", body)
        command_id = result.get("id")
        return ImportOperation(
            operation_id=str(command_id),
            command_id=command_id,
            submitted_at=datetime.now(UTC),
            candidates=[c.absolute_path for c in selected_candidates],
            media_ids=sorted({c.media_id for c in selected_candidates if c.media_id}),
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
            # A completed ManualImport can still have imported nothing: check the episodes.
            episodes = (
                await self._get("/episode", episodeIds=match.episode_ids)
                if match.episode_ids
                else []
            )
            missing = [e["id"] for e in episodes if not e.get("hasFile")]
            if missing:
                return ImportOutcome(
                    success=False,
                    details={
                        "command_status": cmd_status,
                        "error": f"Episodes {missing} still have no file",
                    },
                )
            return ImportOutcome(
                success=True,
                imported_paths=operation.candidates,
                details={"command_status": cmd_status},
            )
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
