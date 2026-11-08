"""Real authored peers, independent previous images and durable typed lineage."""

import asyncio
import copy
import struct
from contextlib import asynccontextmanager

import pytest
from bms_tool.app import create_app
from bms_tool.moi_execution_order import MoiExecutionOrder
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_applications import NativeApplications, native_application_router
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_order_recovery_proposal import NativeOrderRecoveryProposal
from bms_tool.native_order_recovery_transfer import (
    PROFILE,
    validate_plan,
    validate_recorded_lineage,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from .test_moi_wire_sources import REF
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_order_transfer import applying, order_review


@asynccontextmanager
async def selected_target(link, routed):
    target = link[4]
    transport = None
    try:
        if routed:
            address, port = target["address"].rsplit(":", 1)
            transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
                lambda: NativeRouter((address, int(port))), local_addr=("127.0.0.1", 0)
            )
            target = {
                "address": "3001:7",
                "device": "device,5136",
                "router": proxy.endpoint,
                "dnet": 3001,
            }
        yield target
        if routed:
            assert not proxy.errors
    finally:
        if transport:
            transport.close()


async def original_and_proposal(link, target=None, *, historical=False, **formats):
    peer, _, _, native, original_target = link
    target = target or original_target
    _, original_plan = await order_review(link, target=target, **formats)
    if historical:
        peer.mode = "drop-end"
    parent = await native.apply_order(**applying(original_plan))
    if historical:
        assert parent["pending"]
        peer.mode = "normal"
        await native.reconcile(
            operation_id="original-order-historical-readback", receipt_id=parent["intent"]["id"]
        )
        native.storage.event(parent["intent"]["id"], "readback", {"status": "unknown"})
        parent = native.storage.receipt(parent["intent"]["id"])
    assert not parent["pending"]
    capture = await native.capture(**target, operation_id="capture-current-previous-order")
    snapshot, _ = native.storage.load(capture["id"])
    prepared = NativeOrderRecoveryProposal(NativeBackupRecords(native.storage)).prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
        }
    )
    arguments = {
        **target,
        **prepared["proposal"],
        "operation_id": "review-previous-native-order",
        "recovery_parent_receipt": parent["intent"]["id"],
        "recovery_origin_sha256": prepared["origin_sha256"],
    }
    return parent, prepared, arguments


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
async def test_previous_order_uses_new_restore_independent_full_image_and_fresh_saved_values(
    native_link, routed, historical, compressed, extended, diagram_class
):
    peer, _, _, native, _ = native_link
    async with selected_target(native_link, routed) as target:
        parent, prepared, args = await original_and_proposal(
            native_link,
            target,
            historical=historical,
            compressed=compressed,
            extended=extended,
            diagram_class=diagram_class,
        )
        immutable = copy.deepcopy(native.storage.receipt(parent["intent"]["id"]))
        plan = await native.preview_order(**args)
        assert plan["recovery_profile"] == PROFILE
        assert plan["recovery_origin"] == prepared["origin"]
        assert plan["recovery_origin_sha256"] == seal(plan["recovery_origin"])
        assert plan["review_sha256"] != parent["intent"]["review_sha256"]
        real_slot(peer.files, 0, struct.pack(">f", 47))
        _, original = native.storage.load(parent["intent"]["backup_id"])
        expected, _ = ParameterApplication(original[3], peer.files[11], peer.files[12]).compile()
        sent = mutations(peer).count(("state", "start-restore"))
        result = await native.apply_order(
            **applying(plan, operation_id="apply-previous-native-order")
        )
        assert result["result"]["status"] == "verified" and not result["pending"]
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert result["intent"]["recovery_profile"] == PROFILE
        assert result["intent"]["target"] == {
            "address": target["address"],
            "router": target.get("router"),
            "dnet": target.get("dnet"),
        }
        assert MoiIdentity(peer.files[3]).data == MoiIdentity(expected).data
        assert MoiExecutionOrder(peer.files[3]).inspect(REF)["original_order"] == [0, 1, 2, 3]
        assert result["result"]["preservation"]["selected_order"]["after"] == [0, 1, 2, 3]
        assert mutations(peer).count(("state", "start-restore")) == sent + 1
        assert native.storage.receipt(parent["intent"]["id"]) == immutable
        assert validate_recorded_lineage(result["intent"]) == prepared["origin"]
        row = next(r for r in native.status()["receipts"] if r["id"] == result["intent"]["id"])
        assert row["recovery_parent_receipt"] == parent["intent"]["id"]
        before = copy.deepcopy(peer.events)
        with pytest.raises(ValueError):
            await native.apply_order(**applying(plan, operation_id="replay-previous-native-order"))
        assert peer.events == before


@pytest.mark.parametrize(
    "fault",
    ["unpaired", "origin", "parent", "proposal", "snapshot", "source", "pending", "parent-proof"],
)
async def test_bad_previous_request_refuses_before_any_peer_query(native_link, monkeypatch, fault):
    peer, _, _, native, _ = native_link
    parent, _, args = await original_and_proposal(native_link)
    if fault == "unpaired":
        args.pop("recovery_origin_sha256")
    elif fault == "origin":
        args["recovery_origin_sha256"] = "a" * 64
    elif fault == "parent":
        args["recovery_parent_receipt"] = "a" * 32
    elif fault == "proposal":
        args["proposed_order"] = [0, 1, 3, 2]
    elif fault == "snapshot":
        args["snapshot_sha256"] = "a" * 64
    elif fault == "source":
        args["source_sha256"] = "a" * 64
    else:
        changed = copy.deepcopy(parent)
        if fault == "pending":
            changed["pending"] = True
        else:
            changed["result"]["native_sha256"] = "a" * 64
            changed["result"]["evidence_sha256"] = seal(
                {k: v for k, v in changed["result"].items() if k != "evidence_sha256"}
            )
        original = native.storage.receipt
        monkeypatch.setattr(
            native.storage,
            "receipt",
            lambda key, **kw: (
                copy.deepcopy(changed) if key == parent["intent"]["id"] else original(key, **kw)
            ),
        )
    events = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.preview_order(**args)
    assert peer.events == events


@pytest.mark.parametrize("flag", ["order_change_confirmed", "application_transfer_confirmed"])
async def test_each_new_confirmation_is_required_before_queries(native_link, flag):
    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    plan = await native.preview_order(**args)
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.apply_order(
            **applying(plan, operation_id="unconfirmed-previous-order", **{flag: False})
        )
    assert peer.events == before


async def test_original_evidence_is_rederived_before_durable_intent(native_link):
    peer, _, _, native, _ = native_link
    parent, _, args = await original_and_proposal(native_link)
    plan = await native.preview_order(**args)
    file = native.storage.directory / parent["intent"]["backup_id"] / "file-3.bin"
    raw = file.read_bytes()
    sent, count = mutations(peer).count(("state", "start-restore")), len(native.storage.receipts())
    try:
        file.write_bytes(b"Changed original order evidence")
        result = await native.apply_order(
            **applying(plan, operation_id="refuse-changed-original-order")
        )
        assert result["result"]["status"] == "not_sent" and result["intent"] is None
        assert len(native.storage.receipts()) == count
        assert mutations(peer).count(("state", "start-restore")) == sent
    finally:
        file.write_bytes(raw)


@pytest.mark.parametrize("routed", [False, True])
async def test_lost_ack_restart_readback_keeps_lineage_without_original_parent_files(
    native_link, routed
):
    peer, bacnet, store, native, _ = native_link
    restarted = None
    file = None
    raw = None
    async with selected_target(native_link, routed) as target:
        try:
            parent, prepared, args = await original_and_proposal(native_link, target)
            plan = await native.preview_order(**args)
            peer.mode = "drop-end"
            result = await native.apply_order(
                **applying(plan, operation_id="lose-previous-order-ack")
            )
            assert result["pending"] and result["result"]["status"] == "unknown"
            sent = copy.deepcopy(mutations(peer))
            peer.mode = "normal"
            await native.close()
            file = native.storage.directory / parent["intent"]["backup_id"] / "file-3.bin"
            raw = file.read_bytes()
            file.unlink()
            restarted = NativeApplications(
                bacnet, store, native.instances, request_timeout=0.1, gap=0
            )
            checked = await restarted.reconcile(
                operation_id="readback-previous-order-restart", receipt_id=result["intent"]["id"]
            )
            assert not checked["pending"] and checked["latest_readback"]["status"] == "verified"
            assert checked["intent"]["recovery_origin"] == prepared["origin"]
            assert checked["latest_readback"]["preservation"]["selected_order"]["after"] == [
                0,
                1,
                2,
                3,
            ]
            assert mutations(peer) == sent
        finally:
            if file is not None and raw is not None:
                file.write_bytes(raw)
            if restarted is not None:
                await restarted.close()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "scope",
        "profile",
        "extra",
        "self-parent",
        "proof-time",
        "proof-kind",
        "origin-hash",
    ],
)
async def test_tampered_recorded_lineage_is_refused(native_link, fault):
    _, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    plan = await native.preview_order(**args)
    body = copy.deepcopy(native.plans[plan["token"]]["body"])
    if fault == "missing":
        body.pop("recovery_scope")
    elif fault == "scope":
        body["recovery_scope"] += " unknown"
    elif fault == "profile":
        body["recovery_profile"] += " unknown"
    elif fault == "extra":
        body["recovery_unknown"] = True
    elif fault == "self-parent":
        body["id"] = body["recovery_origin"]["parent_receipt_id"]
    elif fault == "proof-time":
        body["recovery_origin"]["verified_proof"]["time"] = "2026-01-01T00:00:00"
    elif fault == "proof-kind":
        body["recovery_origin"]["verified_proof"]["kind"] = "latest-unverified"
    else:
        body["recovery_origin_sha256"] = "a" * 64
    with pytest.raises(ValueError):
        validate_plan(body, native.plans[plan["token"]]["options"])


async def test_ordinary_review_cannot_acquire_even_valid_recovery_metadata(native_link):
    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    recovered = await native.preview_order(**args)
    original = dict(args)
    original.pop("recovery_parent_receipt")
    original.pop("recovery_origin_sha256")
    original["operation_id"] = "ordinary-order-review-no-lineage"
    plan = await native.preview_order(**original)
    stored = native.plans[plan["token"]]
    for key in ("recovery_profile", "recovery_scope", "recovery_origin", "recovery_origin_sha256"):
        stored["body"][key] = recovered[key]
    stored["digest"] = seal(stored["body"])
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError, match="ordinary"):
        await native.apply_order(**applying({**plan, "review_sha256": stored["digest"]}))
    assert peer.events == before


@pytest.mark.parametrize("fault", ["missing", "profile", "origin", "binding"])
async def test_resealed_retained_plan_cannot_bypass_lineage_before_queries(native_link, fault):
    peer, _, _, native, _ = native_link
    _, _, args = await original_and_proposal(native_link)
    plan = await native.preview_order(**args)
    stored = native.plans[plan["token"]]
    if fault == "missing":
        stored["body"].pop("recovery_origin")
    elif fault == "profile":
        stored["body"]["recovery_profile"] += "future"
    elif fault == "origin":
        stored["body"]["recovery_origin_sha256"] = "a" * 64
    else:
        stored["options"].recovery_parent_receipt = "a" * 32
    stored["digest"] = seal(stored["body"])
    before = copy.deepcopy(peer.events)
    with pytest.raises(ValueError):
        await native.apply_order(**applying({**plan, "review_sha256": stored["digest"]}))
    assert peer.events == before


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("mode", ["drop-start", "drop-block"])
async def test_early_lost_ack_keeps_durable_uncertainty_and_never_replays(
    native_link, routed, mode
):
    peer, bacnet, store, native, _ = native_link
    async with selected_target(native_link, routed) as target:
        _, prepared, args = await original_and_proposal(native_link, target)
        plan = await native.preview_order(**args)
        before = mutations(peer).count(("state", "start-restore"))
        peer.mode = mode
        receipt = await native.apply_order(
            **applying(plan, operation_id="lose-early-previous-order-ack")
        )
        assert receipt["pending"] and receipt["result"]["status"] == "unknown"
        assert receipt["intent"]["recovery_origin"] == prepared["origin"]
        assert mutations(peer).count(("state", "start-restore")) == before + 1
        sent = copy.deepcopy(mutations(peer))
        await native.close()
        restarted = NativeApplications(bacnet, store, native.instances, request_timeout=0.1, gap=0)
        try:
            assert restarted.has_pending()
            with pytest.raises(ValueError):
                await restarted.apply_order(
                    **applying(plan, operation_id="replay-early-order-after-restart")
                )
            assert mutations(peer) == sent
        finally:
            await restarted.close()


async def test_real_router_preview_apply_and_full_app_session_guards(native_link):
    peer, _, store, native, _ = native_link
    parent, prepared, args = await original_and_proposal(native_link)
    base = "/api/bacnet/controller/native-application/execution-order/transfer"
    before = copy.deepcopy(peer.events)
    with TestClient(create_app(store.directory)) as client:
        assert client.post(base + "/preview", json=args).status_code == 403
        token = client.get("/api/session").json()["token"]
        assert (
            client.post(
                base + "/preview",
                json=args | {"can_apply": True},
                headers={"X-Studio-Token": token},
            ).status_code
            == 422
        )
    assert peer.events == before
    http = FastAPI()
    http.include_router(native_application_router(native))
    async with AsyncClient(
        transport=ASGITransport(app=http), base_url="http://testserver"
    ) as client:
        response = await client.post(base + "/preview", json=args)
        assert response.status_code == 200, response.text
        plan = response.json()
        assert plan["recovery_origin"] == prepared["origin"]
        before = copy.deepcopy(peer.events)
        for flag in ("order_change_confirmed", "application_transfer_confirmed"):
            invalid = await client.post(base + "/apply", json=applying(plan, **{flag: 1}))
            assert invalid.status_code == 422
        assert peer.events == before
        result = await client.post(
            base + "/apply", json=applying(plan, operation_id="http-previous-order-apply")
        )
        assert result.status_code == 200, result.text
        receipt = result.json()
        assert receipt["result"]["status"] == "verified"
        assert receipt["intent"]["recovery_origin"]["parent_receipt_id"] == parent["intent"]["id"]
