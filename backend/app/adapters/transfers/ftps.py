"""Explicit FTPS Transfer Adapter.

Uses ftplib (stdlib) wrapped in anyio.to_thread for async compatibility.
All connections use TLS for control and data channels (AUTH TLS explicit).
Never falls back to cleartext FTP.

Connection config:
    host: str
    port: int (default 21)
    username: str
    password: str
    tls_mode: "explicit" (only explicit supported in v1)
    passive: bool (default True)
    timeout: int (default 30)
    tls_verify: bool (default True) — verify cert chain
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import anyio
from ftplib import FTP_TLS, error_perm, error_temp, error_reply

from app.domain.models import (
    RemoteFileDTO,
    RemoteManifest,
    SourceItemDTO,
    TransferResult,
    TransferStatus,
)

logger = logging.getLogger(__name__)


class FTPSAdapter:
    """Explicit FTPS transfer adapter using stdlib ftplib."""

    def __init__(
        self,
        transfer_id: str,
        host: str,
        port: int = 21,
        username: str = "",
        password: str = "",
        passive: bool = True,
        timeout: int = 30,
        tls_verify: bool = True,
    ) -> None:
        self.transfer_id = transfer_id
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._passive = passive
        self._timeout = timeout
        self._tls_verify = tls_verify

    def _connect(self) -> FTP_TLS:
        """Create and authenticate an FTPS connection (blocking, run in thread)."""
        ctx = ssl.create_default_context()
        if not self._tls_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        ftp = FTP_TLS(timeout=self._timeout, context=ctx)
        ftp.connect(self._host, self._port, timeout=self._timeout)  # FTP_TLS(host=...) ignores port
        ftp.login(self._username, self._password)
        ftp.prot_p()  # Protect data channel (PBSZ 0, PROT P)
        ftp.set_pasv(self._passive)
        ftp.voidcmd("TYPE I")  # binary; servers refuse SIZE in ASCII mode ("550 SIZE not allowed")
        return ftp

    async def test_connection(self) -> dict:
        def _test() -> dict:
            try:
                ftp = self._connect()
                welcome = ftp.getwelcome()
                ftp.quit()
                return {
                    "ok": True,
                    "adapter": "ftps",
                    "host": self._host,
                    "port": self._port,
                    "welcome": welcome[:200],
                    "tls": "explicit",
                }
            except Exception as exc:
                return {"ok": False, "error": str(exc), "adapter": "ftps"}

        return await anyio.to_thread.run_sync(_test)

    def _resolve_remote_path(
        self,
        remote_base: str,
        source_prefixes: list[str],
        remote_prefixes: list[str],
        relpath: str,
    ) -> str:
        """Apply path mappings to convert source path to FTPS-visible path."""
        for sp, rp in zip(source_prefixes, remote_prefixes):
            if remote_base.startswith(sp):
                mapped = remote_base[len(sp):].lstrip("/")
                return f"{rp.rstrip('/')}/{mapped}/{relpath}".replace("//", "/")
        # Fallback: join base and relpath
        return f"{remote_base.rstrip('/')}/{relpath}".replace("//", "/")

    async def inspect(
        self,
        source_item: SourceItemDTO,
        file_manifest: list[RemoteFileDTO],
        path_mappings: list[dict[str, str]] | None = None,
    ) -> RemoteManifest:
        """Check which files are present on the remote endpoint and their sizes."""
        source_prefixes = [m.get("source_prefix", "") for m in (path_mappings or [])]
        remote_prefixes = [m.get("remote_prefix", "") for m in (path_mappings or [])]

        def _inspect() -> list[RemoteFileDTO]:
            ftp = self._connect()
            found = []
            try:
                for f in file_manifest:
                    remote_path = self._resolve_remote_path(
                        source_item.remote_base_path,
                        source_prefixes,
                        remote_prefixes,
                        f.relative_path,
                    )
                    try:
                        size = ftp.size(remote_path)
                        if size is not None and size == f.size_bytes:
                            found.append(f)
                        elif size is not None:
                            # Size mismatch — still include but flag
                            logger.warning(
                                "Size mismatch for %s: expected %d got %d",
                                remote_path, f.size_bytes, size,
                            )
                            found.append(f)
                    except error_perm as exc:  # usually not found; log so other refusals show up
                        logger.info("inspect: %s: %s", remote_path, exc)
                    except Exception as exc:
                        logger.debug("inspect: error checking %s: %s", remote_path, exc)
            finally:
                try:
                    ftp.quit()
                except Exception:
                    pass
            return found

        files = await anyio.to_thread.run_sync(_inspect)
        return RemoteManifest(
            endpoint_name=self._host,
            files=files,
            checked_at=datetime.now(timezone.utc),
        )

    async def transfer_file(
        self,
        remote_file: RemoteFileDTO,
        remote_base_path: str,
        destination_part_path: str,
        resume_offset: int = 0,
        progress_callback: Callable[[int, int], None] | None = None,
        cancellation_token: anyio.CancelScope | None = None,
        path_mappings: list[dict[str, str]] | None = None,
    ) -> TransferResult:
        """Transfer a single file via FTPS with resume support."""
        source_prefixes = [m.get("source_prefix", "") for m in (path_mappings or [])]
        remote_prefixes = [m.get("remote_prefix", "") for m in (path_mappings or [])]

        remote_path = self._resolve_remote_path(
            remote_base_path,
            source_prefixes,
            remote_prefixes,
            remote_file.relative_path,
        )

        total_size = remote_file.size_bytes
        bytes_transferred = resume_offset
        # Set when the awaiting task is cancelled: the thread stops at the next block.
        abort = threading.Event()

        def _check_abort() -> None:
            if abort.is_set():
                raise RuntimeError("transfer aborted")

        def _transfer() -> TransferResult:
            # resume_offset is reassigned below on restart; without nonlocal it
            # becomes a local and every read before that raises UnboundLocalError.
            nonlocal bytes_transferred, resume_offset
            try:
                ftp = self._connect()
                try:
                    # Ensure parent dir exists locally
                    os.makedirs(
                        os.path.dirname(destination_part_path), exist_ok=True
                    )

                    # Check resume: validate local .part size
                    if resume_offset > 0 and os.path.exists(destination_part_path):
                        local_size = os.path.getsize(destination_part_path)
                        if local_size != resume_offset:
                            logger.warning(
                                "Resume offset mismatch: expected %d, local %d — restarting",
                                resume_offset, local_size,
                            )
                            resume_offset = 0
                            bytes_transferred = 0

                    mode = "ab" if resume_offset > 0 else "wb"

                    with open(destination_part_path, mode) as f:
                        def _callback(block: bytes) -> None:
                            nonlocal bytes_transferred
                            _check_abort()
                            f.write(block)
                            bytes_transferred += len(block)
                            if progress_callback:
                                progress_callback(bytes_transferred, total_size)

                        if resume_offset > 0:
                            ftp.voidcmd("TYPE I")  # Binary mode
                            # Use REST command for resume
                            sock = ftp.transfercmd(
                                f"RETR {remote_path}",
                                rest=resume_offset,
                            )
                            if sock is None:
                                raise RuntimeError("FTP data connection failed")
                            try:
                                while True:
                                    _check_abort()
                                    data = sock.recv(65536)
                                    if not data:
                                        break
                                    f.write(data)
                                    bytes_transferred += len(data)
                                    if progress_callback:
                                        progress_callback(bytes_transferred, total_size)
                            finally:
                                sock.close()
                                ftp.voidresp()
                        else:
                            ftp.voidcmd("TYPE I")
                            ftp.retrbinary(
                                f"RETR {remote_path}",
                                _callback,
                                blocksize=65536,
                            )

                    return TransferResult(
                        success=True,
                        bytes_transferred=bytes_transferred - resume_offset,
                        resumed_from=resume_offset,
                        endpoint_name=self._host,
                    )
                finally:
                    try:
                        ftp.quit()
                    except Exception:
                        pass
            except Exception as exc:
                logger.error("FTPS transfer failed for %s: %s", remote_path, exc)
                return TransferResult(
                    success=False,
                    bytes_transferred=bytes_transferred - resume_offset,
                    resumed_from=resume_offset,
                    error=str(exc),
                    endpoint_name=self._host,
                )

        try:
            # abandon_on_cancel: return to the caller at once (pause, shutdown); the abort
            # flag then ends the thread within one block instead of after the whole file.
            return await anyio.to_thread.run_sync(_transfer, abandon_on_cancel=True)
        except anyio.get_cancelled_exc_class():
            abort.set()
            raise
