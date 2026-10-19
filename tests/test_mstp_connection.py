"""Direct MS/TP through the production BACnet connector and HTTP endpoints."""

import asyncio
import os
import time

import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_mstp_bacnet import TO_PEER, FixedWirePeer


@pytest.fixture
def serial_path(monkeypatch):
    if os.name != "posix":
        pytest.skip("Real pseudoterminal tests require POSIX")
    master, slave = os.openpty()
    path = os.ttyname(slave)
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: {path})
    monkeypatch.setattr("bms_tool.connections.ports", lambda: [{"device": path}])
    yield master, path
    os.close(master)
    os.close(slave)


def test_http_endpoints_actual_mstp_discovery_and_read(serial_path, tmp_path):
    master, path = serial_path
    peer = FixedWirePeer(master)
    app = create_app(tmp_path)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        config = {"port": path, "mac": 0, "max_master": 1}
        assert client.post("/api/bacnet/connect-mstp", json=config).status_code == 403
        opened = client.post("/api/bacnet/connect-mstp", json=config, headers=headers)
        assert opened.status_code == 200, opened.text
        assert opened.json()["transport"] == "mstp"
        peer.thread.start()
        try:
            found = client.post(
                "/api/bacnet/discover",
                json={"address": "1", "low": 4190012, "high": 4190012},
                headers=headers,
            )
            assert found.status_code == 200, found.text
            assert found.json() == [
                {"address": "1", "device": "device,4190012", "vendor": 999, "max_apdu": 480}
            ]
            value = client.post(
                "/api/bacnet/read",
                json={"address": "1", "object_id": "analog-input,1"},
                headers=headers,
            )
            assert value.status_code == 200, value.text
            assert value.json()["value"] == 12.5
            status = client.get("/api/bacnet/status").json()
            assert status["connected"]
            assert status["serial_link"]["scope"] == "legacy-ms-tp-npdu"
            assert not status["serial_link"]["btcvt"]
            assert status["serial_link"]["statistics"]["received_npdus"] == 2
            assert peer.requests == ["who-is", "read-property"]
        finally:
            app.state.bacnet.close()
            peer.close()
    assert not app.state.bacnet.status()["connected"]


@pytest.mark.asyncio
async def test_owned_commands_keep_exact_mstp_recovery_interface(serial_path, tmp_path):
    _, path = serial_path
    client = Bacnet(Store(tmp_path))
    config = dict(port=path, mac=0, max_master=1)
    await client.connect_mstp(**config)
    saved = client.config.copy()
    # This is a pre-existing uncertain journal entry, not a transmitted command.
    # The same ownership rules used by real BACnet/IP commands must survive a
    # transport restart without allowing them to migrate to a different bus.
    client.commands["uncertain-test"] = {
        "address": "1",
        "object_id": "analog-value,1",
        "priority": 16,
        "status": "uncertain",
        "value": 42,
    }
    client._persist()
    client.close()
    await asyncio.sleep(0)
    recovered = Bacnet(Store(tmp_path))
    try:
        assert recovered.config == saved
        assert "uncertain-test" in recovered.commands
        with pytest.raises(ValueError, match="Relinquish"):
            await recovered.connect_mstp(port=path, mac=1, max_master=1)
        with pytest.raises(ValueError, match="Relinquish"):
            await recovered.connect("127.0.0.1:49999")
        assert not recovered.status()["connected"]
        assert await recovered.connect_mstp(**config) == saved
        assert recovered.status()["connected"]
        assert recovered.status()["commands"][0]["id"] == "uncertain-test"
        working = recovered.app
        with pytest.raises(ValueError, match="Relinquish"):
            await recovered.connect_mstp(**config, max_info_frames=2)
        assert recovered.app is working and recovered.status()["connected"]
        assert recovered.status()["serial_link"]["statistics"]["transmitted_frames"] == 0
    finally:
        recovered.close()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_non_enumerated_port_and_invalid_settings_preserve_working_link(
    serial_path, tmp_path
):
    _, path = serial_path
    client = Bacnet(Store(tmp_path))
    config = dict(port=path, mac=0, max_master=1)
    await client.connect_mstp(**config)
    working = client.app
    try:
        for change in (
            {"port": "/tmp/arbitrary-file"},
            {"baudrate": 1200},
            {"mac": True},
            {"max_master": -1},
            {"max_info_frames": 0},
            {"instance": 4194303},
        ):
            with pytest.raises(ValueError):
                await client.connect_mstp(**{**config, **change})
            assert client.app is working and client.status()["connected"]
        assert await client.connect_mstp(**config) == client.config
        assert client.app is working
    finally:
        client.close()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_mstp_target_rejects_ip_routed_broadcast_and_own_mac(serial_path, tmp_path):
    _, path = serial_path
    client = Bacnet(Store(tmp_path))
    await client.connect_mstp(path, 0, max_master=1)
    try:
        assert str(client.target_address("1")) == "1"
        assert str(client.target_address("254")) == "254"
        for value in ("127.0.0.1:47808", "2001:1", "255", "*", "0", "0x0102"):
            with pytest.raises(ValueError):
                client.target_address(value)
    finally:
        client.close()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_dead_worker_status_requires_and_allows_same_interface_reconnect(
    serial_path, tmp_path
):
    master, path = serial_path
    client = Bacnet(Store(tmp_path))
    config = dict(port=path, mac=0, max_master=1)
    await client.connect_mstp(**config)
    previous = client.app
    try:
        os.write(master, TO_PEER)  # Conflicting source uses the client's MAC.
        for _ in range(100):
            if not client.status()["connected"]:
                break
            await asyncio.sleep(0.005)
        assert not client.status()["connected"]
        assert client.status()["serial_link"]["fault"]
        with pytest.raises(ValueError, match="reconnect"):
            await client.read("1", "analog-input,1")
        assert await client.connect_mstp(**config) == client.config
        assert client.app is not previous and client.status()["connected"]
        assert not client.status()["serial_link"]["fault"]
    finally:
        client.close()
        await asyncio.sleep(0)


def test_http_invalid_mstp_settings_do_not_open_files(serial_path, tmp_path):
    _, path = serial_path
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for config in (
            {"port": "/tmp/not-a-serial-device", "mac": 0},
            {"port": path, "mac": True},
            {"port": path, "mac": 128},
            {"port": path, "mac": 0, "baudrate": 1200},
            {"port": path, "mac": 2, "max_master": 1},
        ):
            result = client.post("/api/bacnet/connect-mstp", json=config, headers=headers)
            assert result.status_code == 422, result.text
            assert not client.get("/api/bacnet/status").json()["connected"]


def test_http_reports_dead_serial_link_and_rejects_services(serial_path, tmp_path):
    master, path = serial_path
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/connect-mstp",
                json={"port": path, "mac": 0, "max_master": 1},
                headers=headers,
            ).status_code
            == 200
        )
        os.write(master, TO_PEER)
        for _ in range(100):
            status = client.get("/api/bacnet/status").json()
            if not status["connected"]:
                break
            time.sleep(0.005)
        assert not status["connected"] and status["serial_link"]["fault"]
        refused = client.post(
            "/api/bacnet/read",
            json={"address": "1", "object_id": "analog-input,1"},
            headers=headers,
        )
        assert refused.status_code == 422
        assert "reconnect" in refused.json()["detail"]
