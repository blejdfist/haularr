"""Test rTorrent adapter XML-RPC parsing with mocked responses.

Tests the XML-RPC request building and response parsing without a real rTorrent server.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.adapters.sources.rtorrent import RtorrentAdapter, _parse_xmlrpc_response, _xmlrpc_call


def test_xmlrpc_call_structure():
    """XML-RPC request body is well-formed."""
    body = _xmlrpc_call("system.client_version")
    assert "methodCall" in body
    assert "system.client_version" in body


def test_xmlrpc_response_parsing():
    """XML-RPC response with a string value is parsed correctly."""
    xml = """<?xml version="1.0"?>
<methodResponse>
  <params>
    <param>
      <value><string>0.9.8</string></value>
    </param>
  </params>
</methodResponse>"""
    result = _parse_xmlrpc_response(xml)
    assert result == "0.9.8"


def test_xmlrpc_response_int():
    """XML-RPC response with an int value."""
    xml = """<?xml version="1.0"?>
<methodResponse>
  <params>
    <param>
      <value><i4>42</i4></value>
    </param>
  </params>
</methodResponse>"""
    result = _parse_xmlrpc_response(xml)
    assert result == 42


def test_xmlrpc_response_array():
    """XML-RPC response with an array of values."""
    xml = """<?xml version="1.0"?>
<methodResponse>
  <params>
    <param>
      <value><array><data>
        <value><string>hash1</string></value>
        <value><string>Test.Release</string></value>
      </data></array></value>
    </param>
  </params>
</methodResponse>"""
    result = _parse_xmlrpc_response(xml)
    assert result == ["hash1", "Test.Release"]


def test_xmlrpc_fault():
    """XML-RPC fault is raised as RuntimeError."""
    xml = """<?xml version="1.0"?>
<methodResponse>
  <fault>
    <value><struct>
      <member><name>faultCode</name><value><i4>1</i4></value></member>
      <member><name>faultString</name><value><string>Bad method</string></value></member>
    </struct></value>
  </fault>
</methodResponse>"""
    with pytest.raises(RuntimeError, match="XML-RPC fault"):
        _parse_xmlrpc_response(xml)


@pytest.mark.asyncio
async def test_rtorrent_test_connection_mocked():
    """Test connection returns ok when XML-RPC responds."""
    adapter = RtorrentAdapter(
        source_id="test",
        xmlrpc_url="http://example.com/RPC2",
    )

    mock_response_text = """<?xml version="1.0"?>
<methodResponse>
  <params><param><value><string>0.9.8</string></value></param></params>
</methodResponse>"""

    mock_response = type("MockResp", (), {
        "text": mock_response_text,
        "raise_for_status": lambda self: None,
    })()

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
        result = await adapter.test_connection()
    assert result["ok"] is True
    assert result["version"] == "0.9.8"
    assert result["adapter"] == "rtorrent"


@pytest.mark.asyncio
async def test_rtorrent_test_connection_failure():
    """Test connection returns error when XML-RPC fails."""
    adapter = RtorrentAdapter(
        source_id="test",
        xmlrpc_url="http://nonexistent.invalid/RPC2",
    )
    result = await adapter.test_connection()
    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_list_items_uses_main_view():
    """d.multicall2 takes (target, view, *fields); an empty view is rejected by rTorrent."""
    adapter = RtorrentAdapter(source_id="test", xmlrpc_url="http://example.com/RPC2")
    with patch.object(adapter, "_call", new_callable=AsyncMock, return_value=[]) as call:
        await adapter.list_items()
    method, target, view, *fields = call.call_args.args
    assert (method, target, view) == ("d.multicall2", "", "main")
    assert fields[0] == "d.hash="


@pytest.mark.asyncio
async def test_list_items_raises_on_fault():
    """A failed listing must surface as a scan error, not as an empty source."""
    adapter = RtorrentAdapter(source_id="test", xmlrpc_url="http://example.com/RPC2")
    err = RuntimeError("XML-RPC fault: {'faultCode': -503, 'faultString': 'Could not find view.'}")
    with patch.object(adapter, "_call", new_callable=AsyncMock, side_effect=err):
        with pytest.raises(RuntimeError, match="Could not find view"):
            await adapter.list_items()



# Field values as reported by a real rTorrent (seedbox) for both torrent shapes.
_COMMON = {"d.custom1=": "TV", "d.custom2=": "", "d.state=": 1, "d.complete=": 1, "d.size_bytes=": 10,
           "d.completed_bytes=": 10, "d.timestamp.finished=": 0, "d.message=": ""}
_SINGLE = {**_COMMON, "d.hash=": "A", "d.name=": "Show.S01E01.mkv",
           "d.base_path=": "/home/u/files/completed/TV/Show.S01E01.mkv",
           "d.directory=": "/home/u/files/completed/TV"}
_MULTI = {**_COMMON, "d.hash=": "B", "d.name=": "Show.S02",
          "d.base_path=": "/home/u/files/completed/TV/Show.S02",
          "d.directory=": "/home/u/files/completed/TV/Show.S02"}


@pytest.mark.asyncio
@pytest.mark.parametrize("rt,expected", [
    (_SINGLE, "/home/u/files/completed/TV"),          # + f.path "Show.S01E01.mkv"
    (_MULTI, "/home/u/files/completed/TV/Show.S02"),  # + f.path "Show.S02E01.mkv"
    ({**_MULTI, "d.base_path=": ""}, "/home/u/files/completed/TV/Show.S02"),  # stopped torrent
])
async def test_remote_base_path_is_folder_manifest_paths_are_relative_to(rt, expected):
    async def fake_call(method, target, view, *fields):
        return [[rt[f] for f in fields]]

    adapter = RtorrentAdapter(source_id="test", xmlrpc_url="http://example.com/RPC2")
    with patch.object(adapter, "_call", side_effect=fake_call):
        [item] = await adapter.list_items()
    assert item.remote_base_path == expected
