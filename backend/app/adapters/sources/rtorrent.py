"""rTorrent/ruTorrent Source Adapter.

Uses XML-RPC (read-only) to discover torrents and their file manifests.
The conventional ruTorrent label is stored in d.custom1.

Connection config keys:
    xmlrpc_url: str         — Full XMLRPC URL, e.g. https://host/RPC2
    username: str | None    — HTTP Basic auth username
    password: str | None    — HTTP Basic auth password (from secret store)
    tls_verify: bool        — Default True; verify server cert
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

import httpx

from app.domain.models import RemoteFileDTO, SourceItemDTO, SourceStatus

logger = logging.getLogger(__name__)

# rTorrent XML-RPC multicall fields (d.multicall2 args: target "", view "main", fields)
_TORRENT_FIELDS = [
    "d.hash=",
    "d.name=",
    "d.custom1=",        # ruTorrent label
    "d.custom2=",        # sometimes used
    "d.state=",          # 0=stopped 1=started
    "d.complete=",       # 1=complete
    "d.size_bytes=",
    "d.completed_bytes=",
    "d.timestamp.finished=",
    "d.base_path=",
    "d.message=",
    "d.directory=",
    "d.down.rate=",      # bytes/s
]

_FILE_FIELDS = [
    "f.path=",
    "f.size_bytes=",
    "f.completed_chunks=",
    "f.size_chunks=",
]


def _xmlrpc_call(method: str, *params: Any) -> str:
    """Build an XML-RPC request body."""
    root = ET.Element("methodCall")
    name_el = ET.SubElement(root, "methodName")
    name_el.text = method
    params_el = ET.SubElement(root, "params")
    for p in params:
        param_el = ET.SubElement(params_el, "param")
        value_el = ET.SubElement(param_el, "value")
        _encode_value(value_el, p)
    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def _encode_value(parent: ET.Element, value: Any) -> None:
    if isinstance(value, bool):
        b = ET.SubElement(parent, "boolean")
        b.text = "1" if value else "0"
    elif isinstance(value, int):
        i = ET.SubElement(parent, "int")
        i.text = str(value)
    elif isinstance(value, str):
        s = ET.SubElement(parent, "string")
        s.text = value
    elif isinstance(value, list):
        arr = ET.SubElement(parent, "array")
        data = ET.SubElement(arr, "data")
        for item in value:
            v = ET.SubElement(data, "value")
            _encode_value(v, item)
    elif isinstance(value, dict):
        st = ET.SubElement(parent, "struct")
        for k, v in value.items():
            m = ET.SubElement(st, "member")
            n = ET.SubElement(m, "name")
            n.text = k
            val = ET.SubElement(m, "value")
            _encode_value(val, v)
    else:
        s = ET.SubElement(parent, "string")
        s.text = str(value)


def _parse_xmlrpc_response(xml_text: str) -> Any:
    """Parse an XML-RPC response and return the Python value."""
    root = ET.fromstring(xml_text)
    fault = root.find("fault")
    if fault is not None:
        fault_val = _decode_value(fault.find("value"))  # type: ignore[arg-type]
        raise RuntimeError(f"XML-RPC fault: {fault_val}")
    params = root.find("params")
    if params is None:
        return None
    param = params.find("param")
    if param is None:
        return None
    value = param.find("value")
    if value is None:
        return None
    return _decode_value(value)


def _decode_value(value: ET.Element) -> Any:
    child = list(value)
    if not child:
        return value.text or ""
    el = child[0]
    tag = el.tag
    if tag in ("string", "i4", "i8", "int", "double", "boolean", "base64", "nil"):
        if tag in ("i4", "i8", "int"):
            return int(el.text or "0")
        if tag == "double":
            return float(el.text or "0")
        if tag == "boolean":
            return el.text == "1"
        if tag == "nil":
            return None
        return el.text or ""
    if tag == "array":
        data = el.find("data")
        if data is None:
            return []
        return [_decode_value(v) for v in data.findall("value")]
    if tag == "struct":
        result: dict[str, Any] = {}
        for member in el.findall("member"):
            name_el = member.find("name")
            val_el = member.find("value")
            if name_el is not None and val_el is not None:
                result[name_el.text or ""] = _decode_value(val_el)
        return result
    return el.text or ""


class RtorrentAdapter:
    """Read-only rTorrent source adapter using XML-RPC."""

    def __init__(
        self,
        source_id: str,
        xmlrpc_url: str,
        username: str | None = None,
        password: str | None = None,
        tls_verify: bool = True,
    ) -> None:
        self.source_id = source_id
        self._url = xmlrpc_url
        self._auth = (username, password) if username else None
        self._tls_verify = tls_verify

    def _make_client(self) -> httpx.AsyncClient:
        auth = httpx.BasicAuth(*self._auth) if self._auth else None
        return httpx.AsyncClient(
            auth=auth,
            verify=self._tls_verify,
            timeout=httpx.Timeout(30.0),
        )

    @classmethod
    def from_config(cls, source_id: str, config: dict) -> "RtorrentAdapter":
        """Build adapter from structured config dict.

        Accepts either:
          - xmlrpc_url: direct URL (legacy / advanced)
          - host + port + url_path: assembled into xmlrpc_url

        TLS controls:
          - use_tls: use https (default True)
          - tls_verify: verify certificate chain (default True, independent of use_tls)
        """
        xmlrpc_url = config.get("xmlrpc_url", "")
        if not xmlrpc_url:
            host = config.get("host", "")
            port = config.get("port", 443)
            url_path = (config.get("url_path") or "rutorrent/plugins/rpc/rpc.php").lstrip("/")
            use_tls = config.get("use_tls", True)
            scheme = "https" if use_tls else "http"
            if host:
                xmlrpc_url = f"{scheme}://{host}:{port}/{url_path}"

        # tls_verify is independent of use_tls — you can use TLS without verifying
        tls_verify = config.get("tls_verify", True)
        return cls(
            source_id=source_id,
            xmlrpc_url=xmlrpc_url,
            username=config.get("username"),
            password=config.get("password"),
            tls_verify=tls_verify,
        )

    async def _call(self, method: str, *params: Any) -> Any:
        body = _xmlrpc_call(method, *params)
        async with self._make_client() as client:
            response = await client.post(
                self._url,
                content=body.encode("utf-8"),
                headers={"Content-Type": "text/xml"},
            )
            response.raise_for_status()
            return _parse_xmlrpc_response(response.text)

    async def test_connection(self) -> dict:
        try:
            version = await self._call("system.client_version")
            return {"ok": True, "version": version, "adapter": "rtorrent"}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "adapter": "rtorrent"}

    async def list_items(self) -> list[SourceItemDTO]:
        """List all torrents via d.multicall2. Errors propagate so the scan records them."""
        rows = await self._call("d.multicall2", "", "main", *_TORRENT_FIELDS)

        items = []
        for row in rows:
            try:
                items.append(self._row_to_dto(row))
            except Exception as exc:
                logger.debug("Failed to parse torrent row: %s — %s", row, exc)
        return items

    def _row_to_dto(self, row: list) -> SourceItemDTO:
        (
            infohash,
            name,
            custom1,  # ruTorrent label
            _custom2,
            state,
            complete,
            size_bytes,
            completed_bytes,
            ts_finished,
            base_path,
            message,
            directory,
            down_rate,
        ) = row

        # Normalize status
        if int(complete) == 1 and int(state) == 1:
            status = SourceStatus.COMPLETED
        elif int(complete) == 1 and int(state) == 0:
            status = SourceStatus.STOPPED
        elif message and "error" in str(message).lower():
            status = SourceStatus.ERROR
        elif int(state) == 1:
            status = SourceStatus.ACTIVE
        else:
            status = SourceStatus.STOPPED

        completed_at: datetime | None = None
        if ts_finished and int(ts_finished) > 0:
            completed_at = datetime.fromtimestamp(int(ts_finished), tz=timezone.utc)

        labels = [custom1.strip()] if custom1 and custom1.strip() else []

        return SourceItemDTO(
            remote_id=str(infohash).lower(),
            name=str(name),
            labels=labels,
            status=status,
            completed_at=completed_at,
            total_bytes=int(size_bytes),
            # f.path is relative to d.directory for every torrent: the torrent's folder when
            # multi-file, the containing folder when single-file. d.base_path is the file itself
            # for single-file torrents (and empty while stopped), so it can't be the base.
            remote_base_path=str(directory),
            infohash=str(infohash).lower(),
            metadata={
                "complete": bool(int(complete)),
                "state": int(state),
                "completed_bytes": int(completed_bytes),
                "message": str(message),
                "down_rate": int(down_rate),
            },
        )

    async def get_item(self, item_key: str) -> SourceItemDTO:
        rows = await self._call("d.multicall2", "", "main", *_TORRENT_FIELDS)
        for row in rows:
            if str(row[0]).lower() == item_key.lower():
                return self._row_to_dto(row)
        raise KeyError(f"Torrent not found: {item_key}")

    async def get_files(self, item_key: str) -> list[RemoteFileDTO]:
        """Every file in the torrent with how much of it is downloaded. Errors propagate."""
        rows = await self._call("f.multicall", item_key, "", *_FILE_FIELDS)
        files = []
        for path, size_bytes, completed_chunks, total_chunks in rows:
            size, total = int(size_bytes), int(total_chunks)
            # Chunks straddle file boundaries, so this is approximate until the file completes.
            done = size * min(int(completed_chunks), total) // total if total else 0
            files.append(RemoteFileDTO(relative_path=str(path), size_bytes=size, done_bytes=done))
        return files

    async def get_manifest(self, item_key: str) -> list[RemoteFileDTO]:
        """Fully downloaded files only (empty files have no chunks and are left out)."""
        try:
            files = await self.get_files(item_key)
        except Exception as exc:
            logger.warning("get_manifest failed for %s: %s", item_key, exc)
            return []
        return [
            RemoteFileDTO(relative_path=f.relative_path, size_bytes=f.size_bytes)
            for f in files
            if f.size_bytes and f.done_bytes == f.size_bytes
        ]
