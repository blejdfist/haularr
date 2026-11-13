"""Test config export redacts secrets.

Acceptance criterion 30: Credential values are redacted from logs,
API responses, config export and screenshot-visible fields.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_config_export_redacts_secrets(auth_client):
    """Config export endpoint never exposes credential values."""
    # Create a source with a connection secret
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Test Source",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://secret.example/RPC2"}, "credential": "my-super-secret",
    })
    assert r.status_code == 201
    source_id = r.json()["id"]

    # Create a library with an API key
    r = await auth_client.post("/api/v1/libraries", json={
        "name": "Sonarr Main",
        "adapter_type": "sonarr",
        "base_url": "http://sonarr:8989",
        "api_key_secret_ref": "enc:super-secret-api-key",
    })
    assert r.status_code == 201

    # Create a transfer with credentials
    r = await auth_client.post("/api/v1/transfers", json={
        "name": "FTPS Transfer",
        "adapter_type": "ftps",
        "config": {"host": "ftp.example.com", "password": "ftp-password"},
    })
    assert r.status_code == 201

    # Export config
    r = await auth_client.get("/api/v1/config/export")
    assert r.status_code == 200
    export = r.json()

    # Verify secrets are redacted
    assert export["sources"][0]["credential_ref"] == "***REDACTED***"
    assert "my-super-secret" not in str(export)  # credential value never in export

    assert export["libraries"][0]["api_key_secret_ref"] == "***REDACTED***"
    assert "super-secret-api-key" not in str(export)

    assert export["transfers"][0]["config"] == "***REDACTED***"
    assert "ftp-password" not in str(export)

    # Verify non-secret data is present
    assert export["sources"][0]["name"] == "Test Source"
    assert export["sources"][0]["adapter_type"] == "rtorrent"
    assert export["libraries"][0]["base_url"] == "http://sonarr:8989"


@pytest.mark.asyncio
async def test_source_detail_redacts_connection(auth_client):
    """Source detail endpoint doesn't expose connection secret."""
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Test",
        "adapter_type": "rtorrent",
        "connection_config": {}, "credential": "secret123",
    })
    source_id = r.json()["id"]

    r = await auth_client.get(f"/api/v1/sources/{source_id}")
    assert r.status_code == 200
    data = r.json()
    # connection_secret_ref should not be in the response
    assert "credential_ref" not in data  # credential never exposed in source detail


@pytest.mark.asyncio
async def test_transfer_detail_redacts_config(auth_client):
    """Transfer detail endpoint doesn't expose config with passwords."""
    r = await auth_client.post("/api/v1/transfers", json={
        "name": "Test Transfer",
        "adapter_type": "ftps",
        "config": {"host": "ftp.example.com", "password": "my-password"},
    })
    transfer_id = r.json()["id"]

    r = await auth_client.get(f"/api/v1/transfers/{transfer_id}")
    assert r.status_code == 200
    data = r.json()
    # Config may be returned but should not contain password in plain text
    # The test verifies the API doesn't expose raw password fields
    config = data.get("config", {})
    if config:
        assert "password" not in config or config["password"] != "my-password"
