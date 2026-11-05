"""The launcher must not confuse a free port, a stale file or a different owner."""

import json
import socket
from types import SimpleNamespace

import pytest
from bms_tool.desktop import Desktop, local_json
from bms_tool.resources import web_directory


@pytest.fixture
def desktop(tmp_path):
    if web_directory() is None:
        pytest.skip("Build the UI before exercising the actual desktop server.")
    desktop = Desktop(tmp_path / "user-data", 0)
    yield desktop
    desktop.close()


def test_ready_server_occupied_port_verified_reuse_and_closed_field_interfaces(desktop):
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        desktop.port = port
        url = desktop.start()
        assert desktop.port != port
        assert local_json(url + "/api/session")["field_network_open"] is False
        assert local_json(url + "/api/bacnet/status")["commands"] == []
        second = Desktop(desktop.directory)
        try:
            assert second.start() == url
            assert second.reused and second.server is None
        finally:
            second.close()
        assert desktop.thread.is_alive()
        assert not desktop.quit_blocked()


def test_changed_lock_identity_cannot_open_an_unverified_server(desktop):
    desktop.start()
    path = desktop.directory / "desktop.lock"
    original = path.read_bytes()
    record = json.loads(original)
    record["instance"] = "different-owner"
    path.write_text(json.dumps(record))
    second = Desktop(desktop.directory)
    try:
        with pytest.raises(RuntimeError, match="owner cannot be verified"):
            second.start()
        assert second.url is None
    finally:
        second.close()
        path.write_bytes(original)


def test_stale_record_is_replaced_only_under_owned_lock(desktop):
    desktop.directory.mkdir(parents=True)
    (desktop.directory / "desktop.lock").write_text('{"port":1,"instance":"stale"}')
    url = desktop.start()
    assert local_json(url + "/api/desktop/identity")["instance"] == desktop.identity
    desktop.close()
    replacement = Desktop(desktop.directory, 0)
    try:
        assert replacement.start()
        assert replacement.identity != desktop.identity
    finally:
        replacement.close()


@pytest.mark.parametrize(
    "connected,commands,native,instance",
    [
        (True, [], None, None),
        (False, [{}], None, None),
        (False, [], {"operation": "active"}, None),
        (False, [], None, {"active": True}),
    ],
)
def test_launcher_quit_refuses_open_interface_owned_commands_and_active_writers(
    tmp_path, connected, commands, native, instance
):
    desktop = Desktop(tmp_path)
    state = SimpleNamespace(
        bacnet=SimpleNamespace(status=lambda: {"connected": connected, "commands": commands}),
        native_applications=SimpleNamespace(active=native),
        device_instances=SimpleNamespace(status=lambda: {"active_operation": instance}),
    )
    desktop.server = SimpleNamespace(config=SimpleNamespace(app=SimpleNamespace(state=state)))
    assert desktop.quit_blocked()
