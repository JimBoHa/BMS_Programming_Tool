"""Independent complete-image oracles and real authored direct/routed transfers."""

import copy
import gzip
import struct
import types

import pytest
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Integer,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_applications import NativeApplications, native_application_router
from bms_tool.native_snapshot_restore import (
    PROFILE,
    current_guard,
    fresh_current,
    reconstruct_intent,
    source,
    validate_evidence,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import mutations, real_slot
from .test_native_order_recovery_transfer import selected_target


def literal_saved_image(*, modules=1, real=3.5):
    rows = [
        native_record(
            470,
            5136,
            [
                (32527, encoded(CharacterString("controller"))),
                (75, encoded(ObjectIdentifier((8, 5136)))),
                (2390, encoded(CharacterString("Authored controller"))),
                (70, encoded(CharacterString("UNLISTED-MODEL"))),
                (4128, encoded(Unsigned(62))),
                (4129, encoded(Unsigned(62))),
                (900, encoded(Real(real))),
                (901, encoded(Unsigned(70000))),
                (902, encoded(Integer(-300))),
                (903, encoded(Boolean(True))),
                (904, encoded(CharacterString("saved"))),
            ],
        )
    ]
    for index in range(modules):
        rows.append(
            native_record(
                200 + index,
                40 + index,
                [
                    (32527, encoded(CharacterString(f"controller/module-{index}"))),
                    (
                        65000,
                        encoded(CharacterString("Preserve unknown expansion properties exactly")),
                    ),
                ],
            )
        )
    rows.append(native_record(127, 1, [(65001, encoded(CharacterString("opaque footer")))]))
    return struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(rows)) + b"".join(
        struct.pack("<H", len(row) + 2) + row for row in rows
    )


def files(*, modules=1, compressed=True):
    return dict(
        zip((3, 11, 12), parameters_source(modules=modules, compressed=compressed), strict=True)
    )


def saved_request(capture):
    return {
        "restore_capture_id": capture["id"],
        "restore_snapshot_sha256": capture["evidence_sha256"],
    }


def apply_request(plan, **changes):
    return {
        "operation_id": "apply-retained-app",
        "token": plan["token"],
        "review_sha256": plan["review_sha256"],
        "historical_application_confirmed": True,
        "application_transfer_confirmed": True,
        **changes,
    }


def consume_historical_storage(peer, historical, *, corrupt=False):
    original = peer.do_ReinitializeDeviceRequest

    async def state(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            # Independent authored firmware outcome: application values become
            # saved defaults. The actual wire payload remains the received File3.
            self.files[11], self.files[12] = historical[11], historical[12]
            if corrupt:
                real_slot(self.files, 4, struct.pack(">f", 99))

    peer.do_ReinitializeDeviceRequest = types.MethodType(state, peer)


async def prepared(link, target=None, *, compressed=True, desired_modules=1, current_modules=4):
    peer, _, _, native, initial = link
    target = target or initial
    historical = files(modules=desired_modules, compressed=compressed)
    peer.files = copy.deepcopy(historical)
    old = await native.capture(**target, operation_id="capture-retained-app")
    old, _ = native.storage.load(old["id"])
    peer.files = files(modules=current_modules, compressed=compressed)
    real_slot(peer.files, 4, struct.pack(">f", 22.5))
    consume_historical_storage(peer, historical)
    plan = await native.preview_snapshot_restore(
        **target, **saved_request(old), operation_id="review-retained-app"
    )
    return old, historical, plan


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("routed", [False, True])
async def test_complete_saved_image_uses_literal_oracle_new_backup_and_one_native_restore(
    native_link, compressed, routed
):
    peer, _, _, native, _ = native_link
    async with selected_target(native_link, routed) as target:
        old, historical, plan = await prepared(native_link, target, compressed=compressed)
        original = copy.deepcopy(native.storage.load(old["id"]))
        before = copy.deepcopy(peer.files)
        assert plan["capture_id"] != old["id"]
        assert plan["compilation"]["difference"]["removed_records"] == 3
        assert plan["compilation"]["difference"]["changed_existing_records"] == 1
        assert plan["restore_source"]["request"] == saved_request(old)
        assert not mutations(peer)
        validate_evidence({k: v for k, v in plan.items() if k not in ("token", "review_sha256")})

        def durable_before_block():
            (receipt,) = native.storage.receipts()
            intent = receipt["intent"]
            assert receipt["pending"] and intent["operation_profile"] == PROFILE
            assert intent["backup_id"] not in (old["id"], plan["capture_id"])
            assert native.storage.load(intent["backup_id"])[1] == before
            payload = reconstruct_intent(native.storage, intent)
            assert MoiIdentity(payload).data == literal_saved_image()
            assert (
                native.storage.directory / intent["backup_id"] / "reviewed-application.bin"
            ).read_bytes() == payload

        # Inspect durable state at the first block, before the authored peer adds it.
        def first_block():
            if not peer.stage:
                durable_before_block()

        peer.dispatch = first_block
        result = await native.apply_snapshot_restore(**apply_request(plan))
        assert result["result"]["status"] == "verified" and not result["pending"], result
        assert MoiIdentity(peer.files[3]).data == literal_saved_image()
        assert native.storage.load(old["id"]) == original
        assert original[1] == historical
        assert result["intent"]["review_capture_id"] == plan["capture_id"]
        assert result["intent"]["restore_source"]["request"] == saved_request(old)
        assert result["result"]["preservation"]["effective_saved_application_values_verified"]
        assert result["result"]["preservation"]["non_application_runtime_restored"] is False
        assert mutations(peer).count(("state", "start-restore")) == 1
        assert mutations(peer).count(("state", "end-restore")) == 1
        assert all(row[1] == 3 for row in mutations(peer) if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await native.apply_snapshot_restore(**apply_request(plan))
        assert mutations(peer).count(("state", "start-restore")) == 1


@pytest.mark.parametrize("compressed", [False, True])
async def test_offline_reconstruction_and_exact_source_evidence_need_no_controller(
    native_link, compressed
):
    _, bacnet, _, native, _ = native_link
    old, _, _ = await prepared(native_link, compressed=compressed)
    await native.close()
    bacnet.close()
    output, report = source(native.storage, saved_request(old))
    assert MoiIdentity(output).data == literal_saved_image()
    assert report["evidence_sha256"] == seal(
        {k: v for k, v in report.items() if k != "evidence_sha256"}
    )
    assert report["compilation"]["compiled_sha256"] == sha(output)
    assert report["compilation"]["saved_application_parameters"] == 7
    assert report["controller_queries"] is report["field_actions"] is report["can_apply"] is False


@pytest.mark.parametrize(
    "change", ["setting", "application", "directory", "CRC", "capacity", "credentials", "original"]
)
async def test_fresh_or_historical_drift_never_starts_restore(native_link, change):
    peer, _, _, native, _ = native_link
    old, _, plan = await prepared(native_link)
    if change == "setting":
        real_slot(peer.files, 4, struct.pack(">f", 23))
    elif change == "application":
        peer.files[3] = files(modules=5)[3]
    elif change == "directory":
        peer.files[11] += b"\x00"
    elif change == "CRC":
        peer.files[12] = bytes([peer.files[12][0] ^ 1]) + peer.files[12][1:]
    elif change == "capacity":
        peer.application_capacity = 1
    elif change == "credentials":
        native.credentials.set("changed", "changed")
    else:
        path = native.storage.directory / old["id"] / "file-3.bin"
        path.write_bytes(path.read_bytes() + b"altered")
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert result["result"]["status"] == "not_sent", result
    assert result["intent"] is None and not mutations(peer)


async def test_large_retained_program_restores_added_records_across_multiple_real_blocks(
    native_link,
):
    peer, _, _, native, _ = native_link
    old, _, plan = await prepared(
        native_link, compressed=False, desired_modules=100, current_modules=1
    )
    assert plan["compilation"]["difference"]["added_records"] == 99
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert result["result"]["status"] == "verified", result
    assert MoiIdentity(peer.files[3]).data == literal_saved_image(modules=100)
    assert len([row for row in mutations(peer) if row[0] == "write"]) > 10
    assert native.storage.load(old["id"])[1][3] != peer.files[3]


@pytest.mark.parametrize(
    "mode", ["drop-start", "drop-block", "drop-end", "wrong-service", "trailing-ack"]
)
async def test_lost_native_ack_is_durable_and_never_replays_after_restart(native_link, mode):
    peer, bacnet, store, native, _ = native_link
    _, _, plan = await prepared(native_link)
    peer.mode = mode
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert result["intent"]["restore_source"] == plan["restore_source"]
    assert mutations(peer).count(("state", "start-restore")) == 1
    if mode != "drop-end":
        assert ("state", "end-restore") not in mutations(peer)
    sent = copy.deepcopy(mutations(peer))
    await native.close()
    restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
    try:
        assert restarted.has_pending()
        with pytest.raises(ValueError, match="consumed"):
            await restarted.apply_snapshot_restore(**apply_request(plan))
        assert mutations(peer) == sent
        if mode == "drop-end":
            peer.mode = "normal"
            readback = await restarted.reconcile(
                operation_id="readback-retained-image", receipt_id=result["intent"]["id"]
            )
            assert (
                not readback["pending"] and readback["latest_readback"]["status"] == "verified"
            ), readback
            assert MoiIdentity(peer.files[3]).data == literal_saved_image()
            assert mutations(peer) == sent
    finally:
        await restarted.close()


@pytest.mark.parametrize(
    "flag", ["historical_application_confirmed", "application_transfer_confirmed"]
)
async def test_restore_needs_both_explicit_confirmations_before_any_field_request(
    native_link, flag
):
    peer, _, _, native, _ = native_link
    _, _, plan = await prepared(native_link)
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="Confirm"):
        await native.apply_snapshot_restore(**apply_request(plan, **{flag: False}))
    assert peer.events == before and not native.storage.receipts()


@pytest.mark.parametrize(
    "mode", ["mismatch", "not-operational", "changed-saved-setting", "bad-saved-value"]
)
async def test_ack_without_complete_application_saved_values_and_operational_status_stays_pending(
    native_link, mode
):
    peer, _, _, native, _ = native_link
    _, historical, plan = await prepared(native_link)
    if mode == "bad-saved-value":
        consume_historical_storage(peer, historical, corrupt=True)
    else:
        peer.mode = mode
        if mode == "changed-saved-setting":
            # Preserve the independent storage outcome, then change its saved String.
            real = peer.do_ReinitializeDeviceRequest

            async def changed(self, request):
                await real(request)
                if str(request.reinitializedStateOfDevice) == "end-restore":
                    self.files[11] = self.files[11].replace(b"saved", b"other")

            peer.do_ReinitializeDeviceRequest = types.MethodType(changed, peer)
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    assert mutations(peer).count(("state", "start-restore")) == 1
    assert mutations(peer).count(("state", "end-restore")) == 1


def with_counter(*, object_type=3, pid=15, legacy=False, version=62):
    data = files(modules=1)
    native = gzip.decompress(data[3])
    if version != 62:
        assert native.count(b"\x21\x3e") == 2
        native = native.replace(b"\x21\x3e", bytes([0x21, version]))
        dynamic = bytearray(data[12])
        for at in (0, 2):
            payload = bytes([version])
            dynamic[at : at + 2] = payload + bytes([header_crc(payload) ^ 255])
        data[12] = bytes(dynamic)
    cid, instance, property_id = (251, 77, 978) if legacy else (777, 77, pid)
    row = native_record(
        cid,
        instance,
        [
            (32527, encoded(CharacterString("controller/counter"))),
            (75, encoded(ObjectIdentifier((object_type, instance)))),
            (property_id, encoded(Unsigned(7))),
        ],
    )
    native = (
        native[:10]
        + (int.from_bytes(native[10:14], "little") + 1).to_bytes(4, "little")
        + native[14:]
    )
    data[3] = gzip.compress(native + struct.pack("<H", len(row) + 2) + row, mtime=0)
    body = ((object_type << 22) | instance).to_bytes(4, "big") + property_id.to_bytes(2, "big")
    body += (
        bytes([0x6F, 2]) + cid.to_bytes(2, "big") + len(data[12]).to_bytes(2, "big") + b"\x12\x34"
    )
    data[11] += (len(body) + 2).to_bytes(2, "big") + body
    payload = (7).to_bytes(4, "big")
    data[12] += payload + bytes([header_crc(payload) ^ 255])
    return data


@pytest.mark.parametrize("kind", ["binary-COS", "binary-elapsed", "legacy60"])
def test_only_qualified_counter_advances_can_cross_the_current_configuration_guard(kind):
    before = with_counter(
        pid=33 if kind == "binary-elapsed" else 15,
        legacy=kind == "legacy60",
        version=60 if kind == "legacy60" else 62,
    )
    after = copy.deepcopy(before)
    real_slot(after, -5, (8).to_bytes(4, "big"))
    first, second = fresh_current(before, after)
    assert first["counter_count"] == second["counter_count"] == 1
    assert first["saved_configuration_sha256"] == second["saved_configuration_sha256"]
    assert first["counter_values_sha256"] != second["counter_values_sha256"]
    real_slot(after, -5, (6).to_bytes(4, "big"))
    with pytest.raises(ValueError, match="configuration changed"):
        fresh_current(before, after)


@pytest.mark.parametrize("kwargs", [{"object_type": 2}, {"legacy": True, "version": 62}])
def test_counter_looking_name_or_unqualified_release_keeps_exact_setting_guard(kwargs):
    before = with_counter(**kwargs)
    after = copy.deepcopy(before)
    assert current_guard(before)[0]["counter_count"] == 0
    real_slot(after, -5, (8).to_bytes(4, "big"))
    with pytest.raises(ValueError, match="configuration changed"):
        fresh_current(before, after)


@pytest.mark.parametrize("kind", ["binary-COS", "binary-elapsed", "legacy60"])
@pytest.mark.parametrize("advance", [True, False])
async def test_current_counter_changes_are_qualified_during_real_restore(
    native_link, kind, advance
):
    peer, _, _, native, target = native_link
    historical = with_counter(
        pid=33 if kind == "binary-elapsed" else 15,
        legacy=kind == "legacy60",
        version=60 if kind == "legacy60" else 62,
    )
    peer.files = copy.deepcopy(historical)
    captured = await native.capture(**target, operation_id="counter-historical-capture")
    captured, _ = native.storage.load(captured["id"])
    real_slot(peer.files, 4, struct.pack(">f", 22.5))
    real_slot(peer.files, -5, (8).to_bytes(4, "big"))
    consume_historical_storage(peer, historical)
    plan = await native.preview_snapshot_restore(
        **target, **saved_request(captured), operation_id="counter-current-review"
    )
    real_slot(peer.files, -5, (9 if advance else 7).to_bytes(4, "big"))
    result = await native.apply_snapshot_restore(**apply_request(plan))
    if not advance:
        assert result["result"]["status"] == "not_sent" and not mutations(peer), result
        return
    assert result["result"]["status"] == "verified" and not result["pending"], result
    c = result["intent"]["compilation"]
    assert c["reviewed_current_guard"]["counter_count"] == 1
    assert (
        c["reviewed_current_guard"]["counter_values_sha256"]
        != c["prewrite_guard"]["counter_values_sha256"]
    )
    assert mutations(peer).count(("state", "start-restore")) == 1
    # The desired payload deliberately contains the historical application counter.
    saved = ParameterApplication(peer.files[3], peer.files[11], peer.files[12])
    assert saved.compile()[1]["changed_parameters"] == []
    app = MoiIdentity(peer.files[3])
    cid, pid = (251, 978) if kind == "legacy60" else (777, 33 if kind == "binary-elapsed" else 15)
    (counter,) = [
        r
        for r in app.records
        if int.from_bytes(app.data[r["offset"] + 6 : r["offset"] + 10], "big") == (cid << 22 | 77)
    ]
    assert app.reader.scalar(counter, pid) == 7
    assert (peer.files[11], peer.files[12]) == (historical[11], historical[12])


@pytest.mark.parametrize("route", ["source", "export", "preview", "apply"])
def test_all_restore_HTTP_actions_require_the_real_application_session(tmp_path, route):
    with TestClient(create_app(tmp_path)) as client:
        path = "/api/bacnet/controller/native-application/application-restore/" + route
        assert client.post(path, json={}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(path, json={"can_apply": True}, headers=headers).status_code == 422
        assert client.app.state.bacnet.status()["connected"] is False


async def test_real_HTTP_source_export_review_confirm_and_exact_receipt(native_link):
    peer, _, _, native, target = native_link
    old, _, _ = await prepared(native_link)
    http = FastAPI()
    http.include_router(native_application_router(native))
    base = "/api/bacnet/controller/native-application/application-restore"
    async with AsyncClient(
        transport=ASGITransport(app=http), base_url="http://testserver"
    ) as client:
        before = copy.deepcopy(peer.events)
        response = await client.post(base + "/source", json=saved_request(old))
        assert response.status_code == 200, response.text
        document = response.json()
        exported = await client.post(
            base + "/export",
            json=saved_request(old) | {"source_evidence_sha256": document["evidence_sha256"]},
        )
        assert exported.status_code == 200
        assert MoiIdentity(exported.content).data == literal_saved_image()
        assert exported.headers["x-bms-artifact-sha256"] == sha(exported.content)
        assert exported.headers["x-bms-restore-source"] == old["id"]
        assert exported.headers["x-bms-restore-snapshot"] == old["evidence_sha256"]
        assert exported.headers["x-bms-restore-review"] == document["evidence_sha256"]
        assert peer.events == before
        plan_response = await client.post(
            base + "/preview",
            json=target | saved_request(old) | {"operation_id": "HTTP-restoration-preview"},
        )
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()
        before = copy.deepcopy(peer.events)
        for flag in ["historical_application_confirmed", "application_transfer_confirmed"]:
            result = await client.post(base + "/apply", json=apply_request(plan, **{flag: 1}))
            assert result.status_code == 422
        assert peer.events == before
        result = await client.post(base + "/apply", json=apply_request(plan))
        assert result.status_code == 200, result.text
        receipt = result.json()
        assert receipt["result"]["status"] == "verified", receipt
        downloaded = await client.get(
            "/api/bacnet/controller/native-application/receipts/" + receipt["intent"]["id"]
        )
        assert downloaded.status_code == 200
        assert downloaded.json() == receipt


@pytest.mark.parametrize(
    "field", ["firmware-revision", "model-name", "application-software-version", "object-name"]
)
async def test_live_identity_mismatch_refuses_before_backup(native_link, field):
    peer, _, _, native, target = native_link
    old, _, _ = await prepared(native_link)
    peer.metadata[field] = "Changed identity"
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="identity|identities"):
        await native.preview_snapshot_restore(
            **target, **saved_request(old), operation_id="mismatched-restore-identity"
        )
    assert not any(row[0] == "state" for row in peer.events[len(before) :])
    assert not mutations(peer)


@pytest.mark.parametrize(
    "wrong",
    [
        "source-request",
        "source-scope",
        "source-seal",
        "current-guard",
        "capture",
        "payload",
        "lineage",
        "plan-seal",
    ],
)
async def test_altered_restore_review_cannot_dispatch(native_link, wrong):
    peer, _, _, native, _ = native_link
    _, _, plan = await prepared(native_link)
    internal = native.plans[plan["token"]]
    body = internal["body"]
    if wrong == "source-request":
        body["restore_source"]["request"]["restore_capture_id"] = "f" * 32
    elif wrong == "source-scope":
        body["restore_source"]["scope"] = "Wrong scope"
    elif wrong == "source-seal":
        body["restore_source"]["evidence_sha256"] = "f" * 64
    elif wrong == "current-guard":
        body["compilation"]["reviewed_current_guard"]["counter_count"] = True
    elif wrong == "capture":
        body["capture_id"] = "f" * 32
    elif wrong == "payload":
        body["payload_sha256"] = "f" * 64
    elif wrong == "lineage":
        body["recovery_profile"] = "invented-recovery"
    else:
        body["scope"] = "Changed outer review"
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.apply_snapshot_restore(**apply_request(plan))
    assert peer.events == before and not native.storage.receipts()


async def test_owning_review_expires_or_retires_before_dispatch(native_link):
    import time

    peer, _, _, native, _ = native_link
    _, _, plan = await prepared(native_link)
    native.plans[plan["token"]]["expires"] = time.monotonic() - 1
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert result["result"]["status"] == "not_sent" and not mutations(peer)


async def test_unchanged_current_program_never_creates_a_restore_plan(native_link):
    peer, _, _, native, target = native_link
    peer.files = files(modules=1)
    captured = await native.capture(**target, operation_id="capture-current-equals-retained")
    captured, _ = native.storage.load(captured["id"])
    with pytest.raises(ValueError, match="already matches"):
        await native.preview_snapshot_restore(
            **target, **saved_request(captured), operation_id="review-unnecessary-restoration"
        )
    assert not native.plans and not mutations(peer)


@pytest.mark.parametrize("wrong", ["address", "device", "router", "network"])
async def test_foreign_route_is_rejected_before_current_controller_reads(native_link, wrong):
    peer, _, _, native, initial = native_link
    old, _, _ = await prepared(native_link)
    native.plans.clear()
    target = {**initial, "router": None, "dnet": None}
    if wrong == "address":
        target["address"] = "127.0.0.1:47899"
    elif wrong == "device":
        target["device"] = "device,99"
    else:
        target.update(address="3001:7", router=initial["address"], dnet=3001)
        if wrong == "router":
            target["router"] = "127.0.0.1:47899"
        else:
            target.update(address="3002:7", dnet=3002)
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="original controller route"):
        await native.preview_snapshot_restore(
            **target, **saved_request(old), operation_id="foreign-retained-review"
        )
    assert peer.events == before and not native.plans


async def test_same_firmware_identity_does_not_allow_native_release_migration(native_link):
    peer, _, _, native, target = native_link
    historical = files()
    peer.files = copy.deepcopy(historical)
    old = await native.capture(**target, operation_id="version-historical-capture")
    old, _ = native.storage.load(old["id"])
    peer.files = with_counter(legacy=True, version=60)
    with pytest.raises(ValueError, match="native format disagree"):
        await native.preview_snapshot_restore(
            **target, **saved_request(old), operation_id="wrong-format-review"
        )
    assert not native.plans and not mutations(peer)


@pytest.mark.parametrize("role", ["historical", "reviewed-current"])
async def test_original_files_are_revalidated_after_the_last_capacity_reply(native_link, role):
    peer, _, _, native, _ = native_link
    old, _, plan = await prepared(native_link)
    original = native.files.exchange
    changed = False

    async def exchange(*args, **kwargs):
        nonlocal changed
        reply = await original(*args, **kwargs)
        request = args[1]
        if int(getattr(request, "propertyIdentifier", -1)) == 3380:
            capture_id = old["id"] if role == "historical" else plan["capture_id"]
            path = native.storage.directory / capture_id / "file-3.bin"
            path.write_bytes(path.read_bytes() + b"late drift")
            changed = True
        return reply

    native.files.exchange = exchange
    result = await native.apply_snapshot_restore(**apply_request(plan))
    assert changed and result["result"]["status"] == "not_sent", result
    assert not mutations(peer) and not native.storage.receipts()
