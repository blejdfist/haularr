"""Download/resolve stages must pass the endpoint's FTP credentials and port to the adapter."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.adapters.transfers import ftps
from app.adapters.transfers.ftps import FTPSAdapter
from app.jobs.runner import JobRunner
from app.security import encrypt_secret, get_or_create_master_key


def test_transfer_config_includes_decrypted_credentials(settings):
    key = get_or_create_master_key(settings.config_dir)
    cred = "enc:" + encrypt_secret(json.dumps({"username": "u", "password": "pw"}), key)
    transfer = SimpleNamespace(config_json={"tls_verify": False})
    endpoint = SimpleNamespace(host="ftp.x", port=2121, credential_ref=cred)

    cfg = JobRunner(settings, "j", "transfer", "tok")._transfer_config(transfer, endpoint)

    assert cfg == {
        "tls_verify": False,
        "host": "ftp.x",
        "port": 2121,
        "username": "u",
        "password": "pw",
    }


def test_connect_uses_configured_port(monkeypatch):
    calls = {}

    class FakeFTPTLS:
        def __init__(self, **kw):
            calls["init"] = kw

        def connect(self, host, port, timeout=None):
            calls["connect"] = (host, port)

        def login(self, u, p):
            calls["login"] = (u, p)

        def prot_p(self):
            pass

        def set_pasv(self, v):
            pass

        def voidcmd(self, cmd):
            calls["voidcmd"] = cmd

    monkeypatch.setattr(ftps, "FTP_TLS", FakeFTPTLS)
    FTPSAdapter(transfer_id="t", host="ftp.x", port=2121, username="u", password="pw")._connect()
    assert calls["connect"] == ("ftp.x", 2121)
    assert calls["login"] == ("u", "pw")
    assert calls["voidcmd"] == "TYPE I"  # SIZE is refused in ASCII mode
