"""Deluge Source Adapter.

Uses the Deluge Web API (JSON-RPC over HTTP) or daemon RPC.
We use the Web API here as it's the most accessible HTTP interface.

Connection config keys:
    web_url: str         — Deluge Web UI base URL, e.g. http://host:8112
    password: str        — Deluge Web password (from secret store)
    tls_verify: bool     — Default True

Label support requires the Label plugin to be enabled in Deluge.
If the label plugin is not active, source health reports a clear error.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.domain.models import RemoteFileDTO, SourceItemDTO, SourceStatus

logger = logging.getLogger(__name__)

# Torrent state mapping from Deluge to our SourceStatus
_DELUGE_STATE_MAP = {
    "Downloading": SourceStatus.ACTIVE,
    "Seeding": SourceStatus.COMPLETED,
    "Paused": SourceStatus.STOPPED,
    "Checking": SourceStatus.ACTIVE,
    "Queued": SourceStatus.ACTIVE,
    "Error": SourceStatus.ERROR,
    "Moving": SourceStatus.ACTIVE,
}

_TORRENT_KEYS = [
    "name",
    "hash",
    "state",
    "total_size",
    "time_added",
    "completed_time",
    "save_path",
    "label",
    "is_finished",
    "files",
    "file_progress",
    "num_files",
]


class DelugeAdapter:
    """Deluge Web API source adapter (read-only)."""

    def __init__(
        self,
        source_id: str,
        web_url: str,
        password: str,
        tls_verify: bool = True,
    ) -> None:
        self.source_id = source_id
        self._url = web_url.rstrip("/")
        self._password = password
        self._tls_verify = tls_verify
        self._session_cookie: str | None = None
    def _make_client(self) -> httpx.AsyncClient:
        cookies = {}
        if self._session_cookie:
            cookies["_session_id"] = self._session_cookie
        return httpx.AsyncClient(
            verify=self._tls_verify,
            timeout=httpx.Timeout(30.0),
            cookies=cookies,
        )

    async def _rpc(self, method: str, params: list | None = None) -> Any:
        payload = {
            "method": method,
            "params": params or [],
            "id": 1,
        }
        async with self._make_client() as client:
            resp = await client.post(
                f"{self._url}/json",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise RuntimeError(f"Deluge RPC error: {data['error']}")
            return data.get("result")

    async def _authenticate(self) -> bool:
        result = await self._rpc("auth.login", [self._password])
        return bool(result)

    async def _ensure_connected(self) -> None:
        """Authenticate if needed."""
        try:
            is_connected = await self._rpc("web.connected")
            if not is_connected:
                daemons = await self._rpc("web.get_hosts")
                if daemons:
                    await self._rpc("web.connect", [daemons[0][0]])
        except Exception:
            await self._authenticate()

    async def _check_label_plugin(self) -> bool:
        """Check if the Label plugin is enabled."""
        try:
            plugins = await self._rpc("core.get_enabled_plugins")
            return "Label" in (plugins or [])
        except Exception:
            return False

    async def test_connection(self) -> dict:
        try:
            await self._authenticate()
            await self._ensure_connected()
            version = await self._rpc("daemon.get_version")
            has_labels = await self._check_label_plugin()
            return {
                "ok": True,
                "version": version,
                "adapter": "deluge",
                "label_plugin_enabled": has_labels,
                "warning": None if has_labels else "Label plugin not enabled — label routing unavailable",
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc), "adapter": "deluge"}

    async def list_items(self) -> list[SourceItemDTO]:
        try:
            await self._authenticate()
            await self._ensure_connected()
        except Exception as exc:
            logger.warning("Deluge auth failed for %s: %s", self.source_id, exc)
            return []

        has_labels = await self._check_label_plugin()

        try:
            torrents = await self._rpc(
                "core.get_torrents_status",
                [
                    {},  # filter: all
                    [
                        "name",
                        "hash",
                        "state",
                        "total_size",
                        "time_added",
                        "completed_time",
                        "save_path",
                        "is_finished",
                    ],
                ],
            )
        except Exception as exc:
            logger.warning("Deluge list_items failed for %s: %s", self.source_id, exc)
            return []

        if not torrents:
            return []

        # Fetch labels separately if plugin is enabled
        label_map: dict[str, str] = {}
        if has_labels:
            try:
                labeled = await self._rpc("label.get_labels")
                # get per-torrent labels
                for torrent_hash in torrents:
                    try:
                        label = await self._rpc("label.get_torrent", [torrent_hash])
                        if label:
                            label_map[torrent_hash] = str(label)
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("Could not fetch Deluge labels: %s", exc)

        items = []
        for torrent_hash, info in (torrents or {}).items():
            try:
                items.append(self._info_to_dto(torrent_hash, info, label_map.get(torrent_hash)))
            except Exception as exc:
                logger.debug("Failed to parse Deluge torrent %s: %s", torrent_hash, exc)
        return items

    def _info_to_dto(
        self, torrent_hash: str, info: dict, label: str | None
    ) -> SourceItemDTO:
        state_str = info.get("state", "")
        status = _DELUGE_STATE_MAP.get(state_str, SourceStatus.STOPPED)

        completed_at: datetime | None = None
        completed_time = info.get("completed_time", 0)
        if completed_time and int(completed_time) > 0:
            completed_at = datetime.fromtimestamp(int(completed_time), tz=timezone.utc)
        elif info.get("is_finished"):
            time_added = info.get("time_added", 0)
            if time_added:
                completed_at = datetime.fromtimestamp(int(time_added), tz=timezone.utc)

        labels = [label.strip()] if label and label.strip() else []

        return SourceItemDTO(
            remote_id=str(torrent_hash).lower(),
            name=str(info.get("name", "")),
            labels=labels,
            status=status,
            completed_at=completed_at,
            total_bytes=int(info.get("total_size", 0)),
            remote_base_path=str(info.get("save_path", "")),
            infohash=str(torrent_hash).lower(),
            metadata={
                "state": state_str,
                "is_finished": bool(info.get("is_finished", False)),
            },
        )

    async def get_item(self, item_key: str) -> SourceItemDTO:
        await self._authenticate()
        await self._ensure_connected()
        torrents = await self._rpc(
            "core.get_torrents_status",
            [
                {"id": [item_key]},
                [
                    "name", "hash", "state", "total_size",
                    "time_added", "completed_time", "save_path", "is_finished",
                ],
            ],
        )
        if not torrents or item_key not in torrents:
            raise KeyError(f"Torrent not found: {item_key}")
        label_map: dict[str, str] = {}
        try:
            label = await self._rpc("label.get_torrent", [item_key])
            if label:
                label_map[item_key] = str(label)
        except Exception:
            pass
        return self._info_to_dto(item_key, torrents[item_key], label_map.get(item_key))

    async def get_manifest(self, item_key: str) -> list[RemoteFileDTO]:
        """Return per-file manifest."""
        await self._authenticate()
        await self._ensure_connected()
        try:
            result = await self._rpc(
                "core.get_torrent_status",
                [item_key, ["files", "file_progress", "save_path"]],
            )
        except Exception as exc:
            logger.warning("Deluge get_manifest failed for %s: %s", item_key, exc)
            return []

        files_info = result.get("files", [])
        file_progress = result.get("file_progress", [])

        manifest = []
        for i, file_entry in enumerate(files_info):
            progress = file_progress[i] if i < len(file_progress) else 0.0
            if progress >= 1.0:  # Fully downloaded
                manifest.append(
                    RemoteFileDTO(
                        relative_path=file_entry.get("path", ""),
                        size_bytes=int(file_entry.get("size", 0)),
                    )
                )
        return manifest
