"""Authored configuration HTTP peer; no site credentials or field interfaces."""

import asyncio
import json
import time

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.jct_configuration import (
    OFFLINE_PREFIX,
    JctConfigurationApi,
    archive_name,
    inspection_projection,
)
from bms_tool.jct_connection import ConnectRequest, JctConnections
from bms_tool.metasys_configuration_api import MetasysApiError
from fastapi.testclient import TestClient

from .test_metasys_configuration_api import BASE, OBJECT, AccountPeer

ARCHIVE = "Example Archive"
ROOT = OFFLINE_PREFIX + "/v5/archives/Example%20Archive"


class ArchivePeer(AccountPeer):
    def __init__(self):
        super().__init__()
        self.inventory = [{"name": ARCHIVE, "id": "example-archive"}]
        self.expired = False
        self.version = {"major": 18, "minor": 0, "patch": 0, "build": 1}
        self.hold = False
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = []

    async def handle(self, request):
        path = request.url.path
        if path.endswith(("/GetPreLoginState", "/LogIn")):
            assert path.startswith(OFFLINE_PREFIX + "/")
            return await super().handle(request)
        self.requests.append(request)
        assert request.method == "GET", (
            "No archive edit, transfer, command or security mutation admitted."
        )
        assert request.headers["Authorization"] == "Bearer " + self.token
        assert request.headers["Referer"] == BASE + "/UIOffline/"
        if self.expired:
            return httpx.Response(401, json={"message": "Authored expired session"})
        if path == "/tool/api/v1/version":
            return httpx.Response(200, json=self.version)
        if path == "/tool/api/v1/archives":
            return httpx.Response(200, json={"items": self.inventory})
        if path.endswith("/networkDevices"):
            if self.hold:
                self.entered.set()
                await self.release.wait()
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"id": OBJECT, "name": "Authored engine", "itemReference": "Example:Engine"}
                    ]
                },
            )
        if path.endswith("/objects/" + OBJECT):
            return httpx.Response(
                200,
                json={
                    "item": {
                        "id": OBJECT,
                        "name": "Authored engine",
                        "objectIdentifier": {"instance": 42},
                        "bacnetCommunicationPassword": "authored-private-value",
                        "otherSensitive": "other-private-value",
                    },
                    "schema": {
                        "properties": {
                            "otherSensitive": {
                                "format": "password",
                                "default": "default-private-value",
                            }
                        }
                    },
                },
            )
        if path.endswith("/objects/" + OBJECT + "/objects"):
            return httpx.Response(200, json={"items": []})
        if path.endswith("/attributes/instanceNumber"):
            return httpx.Response(200, json={"item": {"instanceNumber": 77}})
        raise AssertionError(path)


async def make_api(peer):
    api = JctConfigurationApi(
        BASE, httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(peer.handle))
    )
    await api.login(username="test-user", password="test-password")
    return api


@pytest.fixture
async def jct_api():
    peer = ArchivePeer()
    api = await make_api(peer)
    try:
        yield api, peer
    finally:
        await api.close()


async def test_configuration_realm_archive_scope_and_native_identity_are_explicit(jct_api):
    api, peer = jct_api
    assert api.session_key["api_prefix"] == OFFLINE_PREFIX
    assert (await api.tool_version())["major"] == 18
    assert (await api.archives())["items"][0]["name"] == ARCHIVE
    assert (await api.network_devices(ARCHIVE))["items"][0]["id"] == OBJECT
    assert (await api.archive_object(ARCHIVE, OBJECT))["item"]["id"] == OBJECT
    await api.archive_children(ARCHIVE, OBJECT)
    assert (await api.archive_source(ARCHIVE, OBJECT))["item"]["instanceNumber"] == 77
    assert api.archive_resource_guid(BASE + ROOT + "/objects/" + OBJECT, ARCHIVE) == OBJECT
    assert not any(r.url.path.startswith("/API/") for r in peer.requests)
    assert len([r for r in peer.requests if r.method != "GET"]) == 1


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/API/private-api/v6/objects/" + OBJECT),
        ("PATCH", ROOT + "/objects/" + OBJECT),
        ("DELETE", ROOT + "/objects/" + OBJECT),
        ("POST", "/tool/api/v1/archives"),
        ("POST", OFFLINE_PREFIX + "/v5/jobs"),
        ("GET", OFFLINE_PREFIX + "/v5/archives/%2e%2e/objects"),
        ("GET", OFFLINE_PREFIX + "/v5/archives/A%2FB/objects"),
    ],
)
async def test_profile_does_not_admit_online_authority_edits_jobs_or_encoded_paths(
    jct_api, method, path
):
    api, peer = jct_api
    before = len(peer.requests)
    with pytest.raises(ValueError):
        await api._request(method, path)
    assert len(peer.requests) == before


@pytest.mark.parametrize(
    "name", ["../Other", "A/B", "A?x=1", "A#b", "%2F", " Leading", "Trailing ", "A\\B", ""]
)
def test_ambiguous_or_path_like_archive_names_are_rejected(name):
    with pytest.raises(ValueError):
        archive_name(name)


async def test_duplicate_archive_names_and_foreign_resources_are_not_selected(jct_api):
    api, peer = jct_api
    peer.inventory.append({"name": "example archive"})
    with pytest.raises(ValueError, match="ambiguous"):
        await api.archives()
    for url in [
        "https://other.example" + ROOT + "/objects/" + OBJECT,
        BASE + ROOT.replace("Example%20Archive", "Other") + "/objects/" + OBJECT,
        BASE + ROOT + "/objects/" + OBJECT + "?redirect=1",
    ]:
        with pytest.raises(ValueError):
            api.archive_resource_guid(url, ARCHIVE)


def test_display_projection_masks_native_credential_fields_and_defaults():
    source = {
        "item": {
            "unknownOrdinary": {"values": [1, 2]},
            "bacnetCommPassword": "private-a",
            "opaqueCommunity": "private-b",
            "token": "private-d",
            "private_key": "private-e",
        },
        "schema": {
            "properties": {"opaqueCommunity": {"metasysType": "password", "default": "private-c"}}
        },
    }
    result = inspection_projection(source)
    text = json.dumps(result)
    assert all(
        x not in text for x in ["private-a", "private-b", "private-c", "private-d", "private-e"]
    )
    assert result["document"]["item"]["unknownOrdinary"] == source["item"]["unknownOrdinary"]
    assert result["native_backup"] is False and result["editable"] is False
    assert source["item"]["bacnetCommPassword"] == "private-a"


def fields():
    return ConnectRequest(
        server_origin=BASE,
        certificate_sha256="1" * 64,
        username="test-user",
        password="test-password",
    )


@pytest.fixture
async def pool():
    peer = ArchivePeer()
    created = []

    async def connector(server, fingerprint, *, username, password):
        assert (
            server == BASE
            and fingerprint == "1" * 64
            and username == "test-user"
            and password == "test-password"
        )
        api = await make_api(peer)
        created.append(api)
        return api

    pool = JctConnections(connector=connector)
    try:
        yield pool, peer, created
    finally:
        await pool.close()


async def test_only_browser_owner_receives_connection_key_and_never_remote_token(pool):
    connections, peer, _ = pool
    result = await connections.connect(fields())
    key = result["connection_id"]
    assert len(key) == 32 and key != peer.token and peer.token not in json.dumps(result)
    assert "test-password" not in json.dumps(result)
    with pytest.raises(ValueError, match="unavailable"):
        await connections.operate("Z" * 32, lambda api: api.archives())
    assert (await connections.operate(key, lambda api: api.archives()))["items"]
    await connections.disconnect(key)
    assert (await connections.status(key))["connected"] is False


async def test_expiry_and_authentication_failure_retire_the_configuration_session(pool):
    connections, peer, created = pool
    result = await connections.connect(fields())
    key = result["connection_id"]
    connections.entries[key].used = time.monotonic() - 1300
    assert (await connections.status(key))["connected"] is False
    assert created[0]._client.is_closed
    second = await connections.connect(fields())
    peer.expired = True
    with pytest.raises(MetasysApiError):
        await connections.operate(second["connection_id"], lambda api: api.archives())
    assert not connections.entries and created[-1]._client.is_closed


async def test_disconnect_during_a_read_retires_the_late_result(pool):
    connections, peer, _ = pool
    result = await connections.connect(fields())
    key = result["connection_id"]
    peer.hold = True
    task = asyncio.create_task(connections.operate(key, lambda api: api.network_devices(ARCHIVE)))
    await asyncio.wait_for(peer.entered.wait(), 1)
    await connections.disconnect(key)
    peer.release.set()
    with pytest.raises(ValueError, match="changed"):
        await task


async def test_pending_authentication_counts_toward_limit_and_cannot_survive_shutdown():
    entered, release, created = asyncio.Event(), asyncio.Event(), []

    async def connector(*args, **kwargs):
        api = await make_api(ArchivePeer())
        created.append(api)
        if len(created) == 4:
            entered.set()
        await release.wait()
        return api

    connections = JctConnections(connector=connector)
    tasks = [asyncio.create_task(connections.connect(fields())) for _ in range(4)]
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(ValueError, match="Close an existing"):
            await connections.connect(fields())
        assert len(created) == 4 and not connections.entries
        await connections.close()
        release.set()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, ValueError) for result in results)
        assert all(api._client.is_closed for api in created)
        assert not connections.entries and connections.pending == 0
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await connections.close()


def test_http_connection_form_redacts_invalid_credentials_and_keeps_field_interface_closed(
    tmp_path, monkeypatch
):
    peers = []

    async def connector(server, fingerprint, *, username, password):
        peer = ArchivePeer()
        peers.append(peer)
        return await make_api(peer)

    monkeypatch.setattr(JctConfigurationApi, "connect", connector)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"x-studio-token": token}
        request = {
            "server_origin": BASE,
            "certificate_sha256": "1" * 64,
            "username": "test-user",
            "password": "test-password",
        }
        assert client.post("/api/jct/connect", json=request).status_code == 403
        for bad in [
            {**request, "password": {"private": "do-not-echo"}},
            {**request, "unexpected": "do-not-echo"},
        ]:
            reply = client.post("/api/jct/connect", json=bad, headers=headers)
            assert (
                reply.status_code == 422
                and "do-not-echo" not in reply.text
                and "test-password" not in reply.text
            )
        reply = client.post("/api/jct/connect", json=request, headers=headers)
        assert reply.status_code == 200, reply.text
        key = reply.json()["connection_id"]
        assert "test-session-token" not in reply.text and "test-password" not in reply.text
        archives = client.post("/api/jct/archives", json={"connection_id": key}, headers=headers)
        assert archives.status_code == 200
        result = client.post(
            "/api/jct/archive/object",
            json={"connection_id": key, "archive": ARCHIVE, "object_id": OBJECT},
            headers=headers,
        )
        assert (
            result.status_code == 200
            and "authored-private-value" not in result.text
            and "other-private-value" not in result.text
            and "default-private-value" not in result.text
        )
        assert result.json()["document"]["item"]["name"] == "Authored engine"
        assert app.state.bacnet.status()["connected"] is False
    assert not app.state.jct_connections.entries
