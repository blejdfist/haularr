"""FTPSAdapter.transfer_file error and resume handling."""

from __future__ import annotations

import ssl

from app.adapters.transfers.ftps import FTPSAdapter
from app.domain.models import RemoteFileDTO

DATA = b"0123456789"


class FakeFTP:
    def voidcmd(self, cmd):
        pass

    def retrbinary(self, cmd, callback, blocksize=8192):
        callback(DATA)

    def quit(self):
        pass


def _adapter(monkeypatch, connect):
    a = FTPSAdapter(transfer_id="t", host="seedbox")
    monkeypatch.setattr(a, "_connect", connect)
    return a


async def _transfer(a, part, resume_offset=0):
    return await a.transfer_file(
        RemoteFileDTO(relative_path="f.mkv", size_bytes=len(DATA)),
        "/remote",
        str(part),
        resume_offset=resume_offset,
    )


async def test_connect_error_returns_failed_result(monkeypatch, tmp_path):
    def boom():
        raise ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")

    r = await _transfer(_adapter(monkeypatch, boom), tmp_path / "f.part")
    assert r.success is False
    assert "CERTIFICATE_VERIFY_FAILED" in r.error


async def test_fresh_transfer(monkeypatch, tmp_path):
    part = tmp_path / "f.part"
    r = await _transfer(_adapter(monkeypatch, FakeFTP), part)
    assert r.success is True
    assert r.bytes_transferred == len(DATA)
    assert part.read_bytes() == DATA


async def test_resume_mismatch_restarts_from_zero(monkeypatch, tmp_path):
    part = tmp_path / "f.part"
    part.write_bytes(b"xx")  # local size 2 != resume offset 5
    r = await _transfer(_adapter(monkeypatch, FakeFTP), part, resume_offset=5)
    assert r.success is True
    assert r.resumed_from == 0
    assert r.bytes_transferred == len(DATA)
    assert part.read_bytes() == DATA


async def test_cancel_returns_at_once_and_stops_the_thread(monkeypatch, tmp_path):
    """Pause or Ctrl+C mid-file: don't wait for the whole file, and don't leave the thread running."""
    import asyncio
    import threading
    import time

    stopped = threading.Event()

    class EndlessFTP(FakeFTP):
        def retrbinary(self, cmd, callback, blocksize=8192):
            try:
                while True:
                    callback(DATA)
                    time.sleep(0.01)
            finally:
                stopped.set()

    task = asyncio.create_task(_transfer(_adapter(monkeypatch, EndlessFTP), tmp_path / "f.part"))
    await asyncio.sleep(0.1)
    task.cancel()
    t0 = time.monotonic()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert time.monotonic() - t0 < 1
    assert await asyncio.to_thread(stopped.wait, 2)
