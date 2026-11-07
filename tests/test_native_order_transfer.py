"""Literal bytes, real localhost BACnet peers and durable order recovery."""

import asyncio
import copy
import gzip
import struct
import time
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_applications import NativeApplications, native_application_router
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_execution_order import NativeExecutionOrder
from bms_tool.native_order_transfer import (
    PROFILE,
    compile_order,
    validate_order_evidence,
    verify_order_preservation,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_execution_order import proposal, setup
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import BOOLEAN, wire_files

BASE = "/api/bacnet/controller/native-application/execution-order/transfer"


def applying(plan, **changes):
    return {
        "operation_id": "native-order-apply",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "order_change_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


async def order_review(link, *, target=None, configuration=False, **formats):
    peer, _, _, native, original_target = link
    peer.files = wire_files(**formats)
    if configuration:
        from bms_tool.mstp import header_crc

        for instance, cid in [(10, 551), (11, 551), (12, 527), (13, 527)]:
            peer.files[11] += slot((2 << 22) | instance, cid, 65000, 2, len(peer.files[12]))
            payload = (1).to_bytes(4, "big")
            peer.files[12] += payload + bytes([header_crc(payload) ^ 255])
    peer.metadata["object-name"] = "Authored native wire controller"

    async def no_collision(_):
        pytest.fail("An order permutation must not allocate or scan Device identities")

    native.instances._collision = no_collision
    target = target or original_target
    capture = await native.capture(**target, operation_id="native-order-capture")
    snapshot, _ = native.storage.load(capture["id"])
    service = NativeExecutionOrder(NativeBackupRecords(native.storage))
    query = {
        "capture_id": capture["id"],
        "snapshot_sha256": snapshot["evidence_sha256"],
        "source_sha256": sha(peer.files[3]),
        "diagram_ref": REF,
        "record_sha256": MoiIdentity(peer.files[3]).reader.records[REF]["sha256"],
    }
    body = proposal(service, query)
    plan = await native.preview_order(**target, **body, operation_id="native-order-preview")
    return body, plan


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
async def test_udp_order_literal_bytes_fresh_settings_and_durable_original(
    native_link, compressed, extended, diagram_class
):
    peer, _, _, native, _ = native_link
    body, plan = await order_review(
        native_link, compressed=compressed, extended=extended, diagram_class=diagram_class
    )
    real_slot(peer.files, 0, struct.pack(">f", 45))
    original = copy.deepcopy(peer.files)
    merged, _ = ParameterApplication(original[3], original[11], original[12]).compile()
    literal = MoiIdentity(merged).data.replace(
        b"\x21\x00\x21\x01\x21\x02\x21\x03\x2f", b"\x21\x01\x21\x00\x21\x02\x21\x03\x2f", 1
    )

    def durable():
        (receipt,) = native.storage.receipts()
        assert receipt["pending"] and receipt["intent"]["change_kind"] == "execution-order"
        folder = native.storage.directory / receipt["intent"]["backup_id"]
        assert (folder / "reviewed-application.bin").is_file()
        assert native.storage.load(receipt["intent"]["backup_id"])[1] == original
        assert any(r["stage"] == "dispatch-application-block" for r in receipt["events"])

    peer.dispatch = durable
    result = await native.apply_order(**applying(plan))
    assert result["result"]["status"] == "verified" and not result["pending"], result
    assert result["intent"]["operation_profile"] == PROFILE
    assert result["intent"]["payload_sha256"] != plan["payload_sha256"]
    observed = MoiIdentity(peer.files[3])
    assert observed.data == literal
    assert observed.reader.diagram(REF)["execution_order"] == [1, 0, 2, 3]
    assert observed.reader.scalar(observed.reader.records[A], 3113) == 45
    assert observed.reader.scalar(observed.reader.records[B], 3113) == 17
    assert observed.reader.scalar(observed.reader.records[BOOLEAN], 3113) is True
    proof = result["result"]["preservation"]
    assert proof["selected_order"]["effective_order_verified"]
    assert proof["identity_unchanged"] and proof["other_merged_application_bytes_preserved"]
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert mutations(peer).count(("state", "end-restore")) == 1
    assert all(r[1] == 3 for r in mutations(peer) if r[0] == "write")
    assert not result["intent"].get("recovery_origin")
    verify_order_preservation(original, peer.files, body, result["intent"]["order_guard"])
    before = list(mutations(peer))
    with pytest.raises(ValueError, match="consumed"):
        await native.apply_order(**applying(plan))
    assert mutations(peer) == before
    assert native.status()["execution_order_transfer_profile"] == PROFILE
    assert native.status()["receipts"][0]["order_edit"] == body


@pytest.mark.parametrize(
    "change", ["application", "directory", "capacity", "credentials", "expired", "nonfinite", "crc"]
)
async def test_fresh_preflight_refuses_drift_before_restore(native_link, change):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link)
    if change == "application":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(
                b"Opaque metadata retained", b"Changed metadata retained"
            ),
            mtime=0,
        )
    elif change == "directory":
        peer.files[11] = peer.files[11][:-1] + bytes([peer.files[11][-1] ^ 1])
    elif change == "capacity":
        peer.application_capacity = 1
    elif change == "credentials":
        native.credentials.set("changed-backup", "changed-restore")
    elif change == "expired":
        native.plans[plan["token"]]["expires"] = time.monotonic() - 1
    elif change == "nonfinite":
        real_slot(peer.files, 0, bytes.fromhex("7fc00000"))
    else:
        peer.files[12] = peer.files[12][:-1] + bytes([peer.files[12][-1] ^ 1])
    result = await native.apply_order(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("position", [17, 22, 27, 32])
async def test_every_selected_member_nondefault_configuration_is_guarded(native_link, position):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link, configuration=True)
    real_slot(peer.files, position, (2).to_bytes(4, "big"))
    result = await native.apply_order(**applying(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"], result
    assert "configuration changed after review" in str(result)
    assert not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize(
    "change", ["device", "address", "snapshot", "record", "effective", "selection", "noop", "phase"]
)
async def test_wrong_source_route_and_invalid_order_refused_before_query(native_link, change):
    peer, _, _, native, target = native_link
    body, _ = await order_review(native_link)
    options = {**target, **body, "operation_id": "native-order-wrong-source"}
    if change in ("device", "address"):
        options[change] = "device,5137" if change == "device" else "127.0.0.1:1"
    elif change in ("snapshot", "record", "selection", "effective"):
        options[change + "_sha256"] = "f" * 64
    else:
        options["proposed_order"] = [0, 1, 2, 3] if change == "noop" else [2, 0, 1, 3]
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.preview_order(**options)
    assert peer.events == before and not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("key", ["operation_profile", "order_edit", "order_guard", "compilation"])
async def test_tampered_plan_is_refused_before_query(native_link, key):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link)
    native.plans[plan["token"]]["body"][key] = None
    before = list(peer.events)
    with pytest.raises(ValueError, match="review changed"):
        await native.apply_order(**applying(plan))
    assert peer.events == before and not mutations(peer) and not native.storage.receipts()


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_lost_ack_restart_reconciliation_never_replays_restore(native_link, mode):
    peer, bacnet, store, native, _ = native_link
    _, plan = await order_review(native_link)
    peer.mode = mode
    result = await native.apply_order(**applying(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1
    before = list(mutations(peer))
    peer.mode = "normal"
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        if mode == "drop-end":
            verified = await restarted.reconcile(
                operation_id="native-order-readback", receipt_id=result["intent"]["id"]
            )
            assert not verified["pending"] and verified["latest_readback"]["status"] == "verified"
            assert verified["latest_readback"]["preservation"]["selected_order"]["after"] == [
                1,
                0,
                2,
                3,
            ]
        else:
            assert restarted.has_pending()
        assert mutations(peer) == before
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "mode", ["bad-crc", "changed-saved", "changed-native", "retained-original"]
)
async def test_ack_requires_complete_native_and_saved_readback(native_link, mode):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link)
    initial, original = peer.files[3], peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) != "end-restore":
            return
        if mode == "bad-crc":
            self.files[12] = self.files[12][:-1] + bytes([self.files[12][-1] ^ 1])
        elif mode == "changed-saved":
            real_slot(self.files, 0, struct.pack(">f", 99))
        elif mode == "retained-original":
            self.files[3] = initial
        else:
            self.files[3] = gzip.compress(
                gzip.decompress(self.files[3]).replace(
                    b"Opaque metadata retained", b"Changed metadata retained"
                ),
                mtime=0,
            )

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)
    result = await native.apply_order(**applying(plan))
    assert result["result"]["protocol_accepted"]
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1


async def test_original_recovery_is_distinct_from_new_order(native_link):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link)
    image, _ = ParameterApplication(peer.files[3], peer.files[11], peer.files[12]).compile()
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            self.files[3] = image

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)
    result = await native.apply_order(**applying(plan))
    assert not result["pending"] and result["result"]["status"] == "recovered_original", result
    assert result["result"]["proposed_change_verified"] is False
    assert MoiIdentity(peer.files[3]).reader.diagram(REF)["execution_order"] == [0, 1, 2, 3]
    assert mutations(peer).count(("state", "start-restore")) == 1


async def test_routed_order_retains_station_and_device(native_link):
    peer, _, _, native, target = native_link
    address, port = target["address"].rsplit(":", 1)
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
    )
    routed = {"address": "3001:7", "device": "device,5136", "router": proxy.endpoint, "dnet": 3001}
    try:
        _, plan = await order_review(native_link, target=routed)
        result = await native.apply_order(**applying(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert result["intent"]["target"] == {k: v for k, v in routed.items() if k != "device"}
        assert not proxy.errors and mutations(peer).count(("state", "start-restore")) == 1
    finally:
        transport.close()


@pytest.mark.parametrize("key", ["operation_profile", "order_edit", "order_guard"])
async def test_malformed_evidence_is_refused_before_readback(native_link, key):
    peer, _, _, native, _ = native_link
    _, plan = await order_review(native_link)
    before = list(peer.events)
    with pytest.raises(ValueError):
        await native.verify(None, {**plan, key: None})
    assert peer.events == before and not mutations(peer)


async def test_endpoint_profiles_and_confirmations_are_separate(native_link):
    peer, _, _, native, target = native_link
    body, plan = await order_review(native_link)
    with pytest.raises(ValueError, match="different native transfer"):
        await native.apply_wire(
            **{k: v for k, v in applying(plan).items() if k != "order_change_confirmed"},
            wire_change_confirmed=True,
        )
    plan = await native.preview_order(**target, **body, operation_id="native-order-preview-new")
    with pytest.raises(ValueError, match="Confirm"):
        await native.apply_order(**applying(plan, order_change_confirmed=False))
    http = FastAPI()
    http.include_router(native_application_router(native))
    with TestClient(http) as client:
        for value in (1, "true", None):
            assert (
                client.post(
                    BASE + "/apply", json=applying(plan, order_change_confirmed=value)
                ).status_code
                == 422
            )
        assert (
            client.post(
                BASE + "/preview",
                json={**target, **body, "operation_id": "native-http-unknown", "new_instance": 20},
            ).status_code
            == 422
        )
    assert not mutations(peer)


def test_session_token_and_strict_api_schema(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE + "/apply", json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        request = applying({"token": "a" * 32, "review_sha256": "b" * 64})
        for change in (
            {"order_change_confirmed": 1},
            {"application_transfer_confirmed": "true"},
            {"wire_change_confirmed": True},
        ):
            assert (
                client.post(BASE + "/apply", headers=headers, json=request | change).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]


@pytest.mark.parametrize(
    "change",
    [
        "profile",
        "width-bool",
        "width-float",
        "width-large",
        "permutation",
        "noop",
        "diagram",
        "extra",
    ],
)
def test_guard_schema_and_edit_are_bound(tmp_path, change):
    _, service, _, query = setup(tmp_path)
    edit = proposal(service, query)
    files = service.records.storage.load(query["capture_id"])[1]
    _, report = compile_order(files, edit)
    guard = copy.deepcopy(report["order_guard"])
    if change == "profile":
        guard["profile"] += "future"
    elif change.startswith("width"):
        guard["payload_widths"][0] = {"width-bool": True, "width-float": 1.0, "width-large": 5}[
            change
        ]
    elif change == "permutation":
        guard["original_order"][1] = 0
    elif change == "noop":
        edit["proposed_order"] = guard["original_order"]
    elif change == "diagram":
        guard["diagram_ref"] += "different"
    else:
        guard["unexpected"] = True
    with pytest.raises(ValueError):
        validate_order_evidence(edit, guard)


def test_fresh_requires_guard_and_current_preview_proof(tmp_path):
    _, service, _, query = setup(tmp_path)
    edit = proposal(service, query)
    files = service.records.storage.load(query["capture_id"])[1]
    with pytest.raises(ValueError, match="requires its reviewed"):
        compile_order(files, edit, fresh=True)
    for key in ("effective_sha256", "effective_record_sha256", "selection_sha256"):
        with pytest.raises(ValueError, match="effective native order changed"):
            compile_order(files, {**edit, key: "f" * 64})
    output, report = compile_order(files, edit)
    assert report["order_compilation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "order_compilation_sha256"}
    )
    assert sha(output) == report["compiled_sha256"]


@pytest.mark.parametrize("ref", [REF, None, 7, "", "x" * 513])
async def test_recorded_order_ledger_keeps_original_evidence_without_field_access(
    tmp_path, monkeypatch, ref
):
    from bms_tool.change_ledger import LedgerQuery

    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Reading an order receipt must not access the field interface")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    storage = app.state.native_applications.storage
    intent = storage.intent(
        {
            "id": "a" * 32,
            "target": {"address": "3001:7", "router": "127.0.0.1:47809", "dnet": 3001},
            "identity": {"device": "device,5136"},
            "old_instance": 5136,
            "new_instance": 5136,
            "change_kind": "execution-order",
            "order_edit": {"diagram_ref": ref},
        }
    )
    before = storage.receipt(intent["id"])
    report = await app.state.change_ledger.read(LedgerQuery(source="native"))
    (row,) = report["rows"]
    assert row["label"] == "Native execution-order transfer"
    assert row["native_change_kind"] == "execution-order" and row["pending"]
    assert row["object"] == (REF if ref == REF else "")
    if ref != REF:
        assert row["native_reference_issue"]
    assert report["read_only"] and report["field_requests"] == 0
    assert storage.receipt(intent["id"]) == before
