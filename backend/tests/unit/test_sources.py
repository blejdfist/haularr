"""Test source instance CRUD and label rules.

Acceptance criteria covered:
1. Two simultaneous Source instances (rTorrent + rTorrent) both have label 'tv'
   and route to different temporary/completed directories, without config leakage.
2. Two separate instances of the same Source Adapter type operate independently.
3. Distinct Source Label Rules can reference the same or different Library Adapter instances.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_two_different_sources(auth_client):
    """Create two rTorrent sources with same label 'tv' but different paths."""
    # Create rTorrent source
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Primary seedbox",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://seedbox.example/RPC2"},
        "poll_interval": 30,
        "enabled": True,
    })
    assert r.status_code == 201, r.text
    rtorrent = r.json()
    assert rtorrent["adapter_type"] == "rtorrent"
    assert rtorrent["enabled"] is True
    source_id_1 = rtorrent["id"]

    # Create second rTorrent source
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Backup downloader",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://b.example/RPC2"},
        "poll_interval": 30,
        "enabled": True,
    })
    assert r.status_code == 201, r.text
    backup = r.json()
    assert backup["adapter_type"] == "rtorrent"
    source_id_2 = backup["id"]

    # Add label 'tv' to rTorrent with path A1/B1
    r = await auth_client.post(f"/api/v1/sources/{source_id_1}/labels", json={
        "label": "tv",
        "enabled": True,
        "automatic_processing": False,
        "temporary_directory": "/data/temp/rtorrent-tv",
        "completed_directory": "/data/completed/rtorrent-tv",
        "library_instance_id": None,
    })
    assert r.status_code == 201, r.text
    rule1 = r.json()
    assert rule1["label"] == "tv"
    assert rule1["temporary_directory"] == "/data/temp/rtorrent-tv"
    assert rule1["completed_directory"] == "/data/completed/rtorrent-tv"

    # Add label 'tv' to second source with different path A2/B2
    r = await auth_client.post(f"/api/v1/sources/{source_id_2}/labels", json={
        "label": "tv",
        "enabled": True,
        "automatic_processing": False,
        "temporary_directory": "/data/temp/backup-tv",
        "completed_directory": "/data/completed/backup-tv",
        "library_instance_id": None,
    })
    assert r.status_code == 201, r.text
    rule2 = r.json()
    assert rule2["label"] == "tv"
    assert rule2["temporary_directory"] == "/data/temp/backup-tv"
    assert rule2["completed_directory"] == "/data/completed/backup-tv"

    # Verify no config leakage: paths are different
    assert rule1["temporary_directory"] != rule2["temporary_directory"]
    assert rule1["completed_directory"] != rule2["completed_directory"]

    # Verify both sources are listed
    r = await auth_client.get("/api/v1/sources")
    assert r.status_code == 200
    sources = r.json()
    assert len(sources) == 2
    adapter_types = {s["adapter_type"] for s in sources}
    assert adapter_types == {"rtorrent"}

    # Verify labels are source-scoped (each source has its own 'tv' rule)
    r = await auth_client.get(f"/api/v1/sources/{source_id_1}/labels")
    labels1 = r.json()
    assert len(labels1) == 1
    assert labels1[0]["label"] == "tv"
    assert labels1[0]["temporary_directory"] == "/data/temp/rtorrent-tv"

    r = await auth_client.get(f"/api/v1/sources/{source_id_2}/labels")
    labels2 = r.json()
    assert len(labels2) == 1
    assert labels2[0]["label"] == "tv"
    assert labels2[0]["temporary_directory"] == "/data/temp/backup-tv"


@pytest.mark.asyncio
async def test_two_same_type_sources_independent(auth_client):
    """Two instances of the same adapter type operate independently."""
    # Create two rTorrent sources
    r1 = await auth_client.post("/api/v1/sources", json={
        "name": "Primary rTorrent",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://rt1.example/RPC2"},
    })
    assert r1.status_code == 201, r1.text
    src1 = r1.json()

    r2 = await auth_client.post("/api/v1/sources", json={
        "name": "Secondary rTorrent",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://rt2.example/RPC2"},
    })
    assert r2.status_code == 201, r2.text
    src2 = r2.json()

    assert src1["id"] != src2["id"]
    assert src1["name"] != src2["name"]

    # Add labels to each
    await auth_client.post(f"/api/v1/sources/{src1['id']}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/rt1-tv",
        "completed_directory": "/data/completed/rt1-tv",
    })
    await auth_client.post(f"/api/v1/sources/{src2['id']}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/rt2-tv",
        "completed_directory": "/data/completed/rt2-tv",
    })

    # Verify isolation
    r = await auth_client.get(f"/api/v1/sources/{src1['id']}/labels")
    l1 = r.json()
    assert l1[0]["temporary_directory"] == "/data/temp/rt1-tv"

    r = await auth_client.get(f"/api/v1/sources/{src2['id']}/labels")
    l2 = r.json()
    assert l2[0]["temporary_directory"] == "/data/temp/rt2-tv"


@pytest.mark.asyncio
async def test_duplicate_label_rejected(auth_client):
    """Duplicate (source_id, label) is rejected with 409."""
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Test Source",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://rt.example/RPC2"},
    })
    source_id = r.json()["id"]

    r = await auth_client.post(f"/api/v1/sources/{source_id}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/tv",
        "completed_directory": "/data/completed/tv",
    })
    assert r.status_code == 201

    r = await auth_client.post(f"/api/v1/sources/{source_id}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/tv2",
        "completed_directory": "/data/completed/tv2",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_label_references_same_library(auth_client):
    """Distinct Source Label Rules can reference the same Library Adapter instance."""
    # Create a library
    r = await auth_client.post("/api/v1/libraries", json={
        "name": "Sonarr Main",
        "adapter_type": "sonarr",
        "base_url": "http://sonarr:8989",
        "api_key_secret_ref": "enc:test-key",
    })
    assert r.status_code == 201, r.text
    library_id = r.json()["id"]

    # Create two sources
    r = await auth_client.post("/api/v1/sources", json={
        "name": "Source A",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://a.example/RPC2"},
    })
    source_a = r.json()

    r = await auth_client.post("/api/v1/sources", json={
        "name": "Source B",
        "adapter_type": "rtorrent",
        "connection_config": {"xmlrpc_url": "https://b.example/RPC2"},
    })
    source_b = r.json()

    # Both reference the same library
    r = await auth_client.post(f"/api/v1/sources/{source_a['id']}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/a-tv",
        "completed_directory": "/data/completed/a-tv",
        "library_instance_id": library_id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["library_instance_id"] == library_id

    r = await auth_client.post(f"/api/v1/sources/{source_b['id']}/labels", json={
        "label": "tv",
        "temporary_directory": "/data/temp/b-tv",
        "completed_directory": "/data/completed/b-tv",
        "library_instance_id": library_id,
    })
    assert r.status_code == 201, r.text
    assert r.json()["library_instance_id"] == library_id


def test_create_source_adapter_rejects_deluge():
    from app.adapters.sources import create_source_adapter
    with pytest.raises(ValueError, match="Unknown source adapter type"):
        create_source_adapter("s1", "deluge", {})


def test_adapter_type_has_no_deluge():
    from app.domain.models import AdapterType
    assert "deluge" not in {a.value for a in AdapterType}


@pytest.mark.asyncio
async def test_label_can_be_renamed(auth_client):
    sid = (await auth_client.post("/api/v1/sources", json={
        "name": "R", "adapter_type": "rtorrent", "connection_config": {}, "credential": "",
    })).json()["id"]
    base = {"temporary_directory": "/t", "completed_directory": "/c"}
    rule = (await auth_client.post(f"/api/v1/sources/{sid}/labels", json={"label": "tv", **base})).json()
    await auth_client.post(f"/api/v1/sources/{sid}/labels", json={"label": "movies", **base})

    r = await auth_client.patch(f"/api/v1/sources/{sid}/labels/{rule['id']}", json={"label": "shows"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "shows"

    dup = await auth_client.patch(f"/api/v1/sources/{sid}/labels/{rule['id']}", json={"label": "movies"})
    assert dup.status_code == 409
