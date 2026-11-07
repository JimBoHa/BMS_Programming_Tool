"""Independent byte counts and owned direct/routed read-only capacity queries."""

import asyncio
import copy
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK, ReadPropertyRequest
from bacpypes3.constructeddata import Any
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Boolean, Real, TagList, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_capacity_evidence import (
    PROFILE,
    SOURCE_PROFILE,
    NativeCapacityEvidence,
    capacity_value,
)
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, mutations
from .test_native_execution_order import setup
from .test_native_wire_compiler import wire_files

BASE = "/api/bacnet/controller/native-application/resources"


async def prepare(link, target=None, **formats):
    peer, _, _, native, original_target = link
    peer.files = wire_files(**formats)
    peer.metadata["object-name"] = "Authored native wire controller"
    target = target or original_target
    capture = await native.capture(**target, operation_id="capacity-original-capture")
    snapshot, _ = native.storage.load(capture["id"])
    service = NativeCapacityEvidence(native, NativeBackupRecords(native.storage))
    request = {
        **target,
        "capture_id": snapshot["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "operation_id": "capacity-explicit-read",
    }
    return service, request


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
def test_source_sizes_are_literal_without_a_field_interface(tmp_path, compressed, diagram_class):
    files = wire_files(compressed=compressed, diagram_class=diagram_class)
    storage, local, snapshot, _ = setup(tmp_path, files)
    folder = storage.directory / snapshot["id"]
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    service = NativeCapacityEvidence(None, local.records)
    report = service.source(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    native = MoiIdentity(files[3])
    assert report["profile"] == SOURCE_PROFILE and report["archive_bytes"] == len(files[3])
    assert report["expanded_bytes"] == len(native.data)
    assert (
        report["native_record_count"]
        == len(native.records)
        == sum(r["count"] for r in report["record_classes"])
    )
    assert report["diagram_count"] == 1
    assert report["compression"] == ("gzip" if compressed else "raw")
    assert report["source_report_sha256"] == seal(
        {k: v for k, v in report.items() if k != "source_report_sha256"}
    )
    assert report["read_only"] and report["source_immutable"]
    assert all(
        report[k] is False
        for k in (
            "controller_queries",
            "controller_write",
            "saved_settings_merged",
            "current_application_verified",
            "current_identity_verified",
            "restore_payload_prepared",
            "can_apply",
        )
    )
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original
    assert not storage.receipts()


@pytest.mark.parametrize("capacity", [1, 502, 10000, 0xFFFFFFFF])
async def test_direct_capacity_is_advisory_and_never_captures_restores_or_writes(
    native_link, capacity, monkeypatch
):
    peer, _, _, native, _ = native_link
    service, request = await prepare(native_link)
    peer.application_capacity = capacity
    events, files, plans = copy.deepcopy(peer.events), dict(peer.files), dict(native.plans)

    def forbidden(*args, **kwargs):
        pytest.fail("Capacity observation must not read credentials or enter backup/restore")

    monkeypatch.setattr(native.credentials, "get", forbidden)
    monkeypatch.setattr(native.files, "state", forbidden)
    monkeypatch.setattr(native.files, "read", forbidden)
    monkeypatch.setattr(native.files, "write", forbidden)
    report = await service.read(request)
    assert report["profile"] == PROFILE
    assert report["capacity"]["bytes"] == capacity
    assert report["capacity"]["object"] == "file,3" and report["capacity"]["property"] == 3380
    assert report["comparison"]["archive_fits"] == (len(files[3]) <= capacity)
    assert report["comparison"]["headroom_for_retained_archive_bytes"] == capacity - len(files[3])
    assert report["identity"] == report["source"]["identity"]
    assert (
        report["controller_queries"] and report["current_identity_verified"] and report["read_only"]
    )
    assert all(
        report[k] is False
        for k in (
            "current_application_verified",
            "controller_write",
            "field_actions",
            "backup_state_commands",
            "restore_payload_prepared",
            "can_apply",
        )
    )
    assert report["observation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "observation_sha256"}
    )
    assert peer.events == events and peer.files == files and native.plans == plans
    assert not native.storage.receipts() and native.active is None


async def test_routed_capacity_retains_exact_station_and_route(native_link):
    peer, _, _, native, target = native_link
    host, port = target["address"].rsplit(":", 1)
    transport, router = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    selected = {
        "address": "3001:7",
        "device": "device,5136",
        "router": router.endpoint,
        "dnet": 3001,
    }
    try:
        service, request = await prepare(native_link, target=selected)
        before = list(mutations(peer))
        report = await service.read(request)
        assert report["target"] == selected
        assert mutations(peer) == before and not router.errors
        assert not native.storage.receipts()
    finally:
        transport.close()


@pytest.mark.parametrize(
    "change", ["device", "address", "snapshot", "source-flag", "interface", "identity", "zero"]
)
async def test_wrong_source_route_identity_and_capacity_are_refused(native_link, change):
    peer, _, _, native, _ = native_link
    service, request = await prepare(native_link)
    if change == "device":
        request["device"] = "device,5137"
    elif change == "address":
        request["address"] = "127.0.0.1:1"
    elif change == "snapshot":
        request["snapshot_sha256"] = "f" * 64
    elif change == "interface":
        native.bacnet.config = {**native.bacnet.config, "local_address": "127.0.0.1:1"}
    elif change == "identity":
        peer.metadata["object-name"] = "Changed responding identity"
    elif change == "zero":
        peer.application_capacity = 0
    else:
        original = native.check_capture

        def unverified(options):
            snapshot, files = original(options)
            return {**snapshot, "source_identity_matches": False}, files

        native.check_capture = unverified
    before = list(mutations(peer))
    with pytest.raises(ValueError):
        await service.read(request)
    assert mutations(peer) == before and not native.storage.receipts() and native.active is None


@pytest.mark.parametrize(
    "kind",
    [
        "real",
        "boolean",
        "trailing",
        "empty",
        "long",
        "wrong-object",
        "wrong-property",
        "array",
        "zero",
    ],
)
def test_capacity_decoder_refuses_malformed_or_unmatched_values(kind):
    request = ReadPropertyRequest(objectIdentifier=(10, 3), propertyIdentifier=3380)
    value = Any(Unsigned(1000))
    if kind == "real":
        value = Any(Real(1000))
    elif kind == "boolean":
        value = Any(Boolean(True))
    elif kind in ("trailing", "empty", "long"):
        raw = {"trailing": "21012102", "empty": "", "long": "25050000000001"}[kind]
        value = TagList.decode(PDUData(bytes.fromhex(raw)))
    elif kind == "zero":
        value = Any(Unsigned(0))
    reply = ReadPropertyACK(
        objectIdentifier=(10, 4) if kind == "wrong-object" else (10, 3),
        propertyIdentifier=3381 if kind == "wrong-property" else 3380,
        propertyValue=value,
    )
    if kind == "array":
        reply.propertyArrayIndex = 0
    with pytest.raises(ValueError):
        capacity_value(reply, request)


def test_resource_routes_are_token_protected_and_closed(tmp_path):
    _, local, snapshot, _ = setup(tmp_path)
    source = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE + "/source", json=source).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/source", json=source, headers=headers).status_code == 200
        assert (
            client.post(
                BASE + "/read",
                json={
                    **source,
                    "address": "127.0.0.1:47809",
                    "device": "device,5136",
                    "operation_id": "capacity-http",
                    "can_apply": True,
                },
                headers=headers,
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]


async def test_lost_capacity_response_is_attempted_once_without_any_recovery_write(native_link):
    peer, _, _, native, _ = native_link
    service, request = await prepare(native_link)
    original = peer.do_ReadPropertyRequest
    calls = []

    async def dropped(self, packet):
        if tuple(packet.objectIdentifier) == (10, 3) and int(packet.propertyIdentifier) == 3380:
            calls.append(packet.apduInvokeID)
            return
        await original(packet)

    peer.do_ReadPropertyRequest = types.MethodType(dropped, peer)
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="timed out"):
        await service.read(request)
    assert len(calls) == 1 and mutations(peer) == before
    assert native.active is None and not native.storage.receipts() and not native.plans


async def test_another_native_operation_blocks_capacity_before_query(native_link):
    peer, _, _, native, _ = native_link
    service, request = await prepare(native_link)
    before = list(peer.events)
    async with native.operation("capacity-other-owner", "authored-existing-operation"):
        with pytest.raises(ValueError, match="busy"):
            await service.read(request)
    assert peer.events == before and not native.storage.receipts() and native.active is None


async def test_cancelled_capacity_query_does_not_replay_and_new_query_remains_usable(native_link):
    peer, _, _, native, _ = native_link
    service, request = await prepare(native_link)
    original = peer.do_ReadPropertyRequest
    arrived, release = asyncio.Event(), asyncio.Event()

    async def held(self, packet):
        if tuple(packet.objectIdentifier) == (10, 3) and int(packet.propertyIdentifier) == 3380:
            arrived.set()
            await release.wait()
        await original(packet)

    peer.do_ReadPropertyRequest = types.MethodType(held, peer)
    before = list(mutations(peer))
    task = asyncio.create_task(service.read(request))
    try:
        await asyncio.wait_for(arrived.wait(), 1)
        native.cancel(request["operation_id"])
        with pytest.raises(ValueError, match="cancelled"):
            await task
    finally:
        release.set()
    peer.do_ReadPropertyRequest = original
    report = await service.read({**request, "operation_id": "capacity-after-cancel"})
    assert report["capacity"]["bytes"] == peer.application_capacity
    assert mutations(peer) == before and not native.storage.receipts() and not native.plans
