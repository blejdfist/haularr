"""Radarr v5 Library Adapter.

API prefix: /api/v3 (documented Radarr prefix, NOT /api/v5)
Endpoints used: parse, movie, moviefile, manualimport, command, history

Same constraints as Sonarr:
- Parse response does not guarantee registration; cross-check /api/v3/movie.
- No auto-registration. No release-grabbing.
- Upgrade eligibility is inconclusive without a supported pre-flight API.
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

API_PREFIX = "/api/v3"


class RadarrAdapter:
    """Radarr v5 Library Adapter."""

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
                "adapter": "radarr",
                "app_name": status_data.get("appName", "Radarr"),
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "adapter": "radarr"}

    async def parse(self, release_name: str) -> MediaMatch:
        """Parse release name via Radarr's /parse endpoint."""
        try:
            data = await self._get("/parse", title=release_name)
        except Exception as exc:
            logger.debug("Radarr parse failed for %r: %s", release_name, exc)
            return MediaMatch(
                media_type=MediaType.UNKNOWN,
                confidence=0.0,
                parse_data={"error": str(exc)},
            )

        movie_data = data.get("movie")
        parsed_info = data.get("parsedMovieInfo", {})

        if not movie_data or not movie_data.get("id"):
            return MediaMatch(
                media_type=MediaType.MOVIE,
                catalog_id=None,
                title=parsed_info.get("movieTitle", ""),
                year=parsed_info.get("year"),
                parse_data=parsed_info,
                confidence=0.3,
                ambiguous=False,
            )

        return MediaMatch(
            media_type=MediaType.MOVIE,
            catalog_id=movie_data["id"],
            title=movie_data.get("title", ""),
            year=movie_data.get("year"),
            parse_data=parsed_info,
            confidence=0.9,
            ambiguous=False,
        )

    async def inspect_library(self, match: MediaMatch) -> LibraryInventory:
        """Check if the parsed movie is present in the library."""
        if match.catalog_id is None:
            return LibraryInventory(
                catalog_id=0,
                title=match.title,
                registered=False,
                has_file=False,
            )

        try:
            movie = await self._get(f"/movie/{match.catalog_id}")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return LibraryInventory(
                    catalog_id=match.catalog_id,
                    title=match.title,
                    registered=False,
                    has_file=False,
                )
            raise

        has_file = bool(movie.get("hasFile", False))
        existing_quality = None
        if has_file and movie.get("movieFile"):
            existing_quality = (
                movie["movieFile"]
                .get("quality", {})
                .get("quality", {})
                .get("name")
            )

        return LibraryInventory(
            catalog_id=match.catalog_id,
            title=movie.get("title", match.title),
            registered=True,
            has_file=has_file,
            existing_quality=existing_quality,
        )

    async def evaluate_candidate(
        self, match: MediaMatch, metadata: dict
    ) -> EligibilityAssessment:
        """
        Evaluate if a candidate qualifies as an upgrade.

        Radarr v5 does not expose a documented side-effect-free pre-flight
        upgrade check for arbitrary remote files. Return INCONCLUSIVE.
        """
        return EligibilityAssessment(
            decision=EligibilityDecision.INCONCLUSIVE,
            evidence={
                "reason": "No side-effect-free pre-flight upgrade check available in Radarr v5",
                "recommendation": "Use post-transfer ManualImport inspection",
            },
            capability_used="none",
        )

    async def inspect_import(
        self, ready_path: str, match: MediaMatch
    ) -> ImportInspection:
        """Inspect files at ready_path using Radarr's ManualImport GET."""
        if match.catalog_id is None:
            return ImportInspection(all_rejected=True)

        try:
            candidates_raw = await self._get(
                "/manualimport",
                folder=ready_path,
                movieId=match.catalog_id,
            )
        except Exception as exc:
            logger.error("Radarr inspect_import failed: %s", exc)
            return ImportInspection(all_rejected=True)

        candidates = []
        for item in (candidates_raw or []):
            path = item.get("path", "")
            rejections = [r.get("reason", "") for r in item.get("rejections", [])]
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
                "movieId": c.media_id,
                "quality": {"quality": {"id": 0}},  # Let Radarr determine
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
            if match.catalog_id:
                try:
                    movie = await self._get(f"/movie/{match.catalog_id}")
                    if movie.get("hasFile"):
                        movie_file_path = movie.get("movieFile", {}).get("path", "")
                        return ImportOutcome(
                            success=True,
                            imported_paths=[movie_file_path] if movie_file_path else [],
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
            return ImportOutcome(
                success=False,
                details={"command_status": cmd_status, "pending": True},
            )
