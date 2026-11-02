"""Timestamp storage remains evidence, not an application-schema declaration."""

import copy

import pytest
from bms_tool.moi_identity import MoiIdentity

from . import test_native_applications as native
from .test_moi_parameters import binary_saved_state
from .test_native_applications import native_link as native_link  # noqa: F401


def test_client_port_cannot_repeat_the_pending_peer_port(monkeypatch):
    held, observed = [], []

    class Socket:
        def __init__(self, port):
            self.port = port
            self.closed = False

        def __enter__(self):
            held.append(self)
            return self

        def __exit__(self, *args):
            self.closed = True

        def bind(self, address):
            assert address == ("127.0.0.1", 0)
            assert all(not previous.closed for previous in held)

        def getsockname(self):
            return "127.0.0.1", self.port

    candidates = iter([53067, 53068])

    def socket(*args):
        result = Socket(next(candidates))
        observed.append(result)
        return result

    monkeypatch.setattr(native.socket, "socket", socket)
    assert native.port(exclude={53067}) == 53068
    assert len(observed) == 2 and all(sock.closed for sock in observed)


@pytest.mark.parametrize("rename", [False, True])
async def test_native_udp_preserves_settings_without_injecting_timestamp_defaults(
    native_link, rename
):
    peer, bacnet, _, service, target = native_link
    assert str(bacnet.require().nsap.local_adapter.adapterAddr) != target["address"]
    peer.files = dict(zip((3, 11, 12), binary_saved_state(), strict=True))
    original = copy.deepcopy(peer.files)
    _, plan = await (native.name_review(native_link) if rename else native.review(native_link))
    result = await service.apply(**native.apply_request(plan), name_change_confirmed=rename)
    assert result["result"]["status"] == "verified" and not result["pending"], result
    preserved = result["result"]["preservation"]
    assert preserved["saved_application_parameters_verified"] == 9
    runtime = preserved["retained_runtime_parameters"]
    assert len(runtime) == 1 and runtime[0]["stored_epoch_seconds"] == 1700000000
    editor = MoiIdentity(peer.files[3])
    binary = next(r for r in editor.records if r["class_id"] == 242)
    assert 16 not in binary["properties"]
    assert editor.reader.scalar(binary, 15) == 1234
    assert editor.reader.scalar(binary, 33) == 5678
    _, retained = service.storage.load(result["intent"]["backup_id"])
    assert retained == original
    transfers = peer.events.count(("state", "start-restore"))
    observed = await service.reconcile(
        operation_id="timestamp-readback", receipt_id=result["intent"]["id"]
    )
    assert not observed["pending"] and observed["latest_readback"]["status"] == "verified"
    assert peer.events.count(("state", "start-restore")) == transfers == 1
