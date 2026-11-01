"""Previous-number recovery is a new reserved-number native transfer, never a replay."""

import asyncio
import copy
import struct
import types

import pytest
from bacpypes3.apdu import APDU, APCISequence, IAmRequest, WhoIsRequest
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import ObjectIdentifier
from bms_tool.native_applications import NativeApplications

from .test_native_applications import NativePeer, apply_request
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_recovery import set_saved
from .test_native_default_transfer import NativeRouter, mutations, real_slot
from .test_native_instance_recovery import rekey
from .test_native_signal_compiler import signal_files


class InstanceRouter(NativeRouter):
    """Extend the confirmed-service peer with actual bounded routed discovery."""

    def __init__(self, upstream):
        super().__init__(upstream)
        self.discovery_clients = {}
        self.discovery_requests = []
        self.discovery_responses = []

    def datagram_received(self, frame, source):
        npdu = frame[4:]
        if source != self.upstream and npdu[:6] == b"\x01\x20\x0b\xb9\x00\xff":
            try:
                assert frame[:2] == b"\x81\x0a" and int.from_bytes(frame[2:4], "big") == len(frame)
                apdu = npdu[6:]
                request = APCISequence.decode(APDU.decode(PDU(apdu)))
                assert isinstance(request, WhoIsRequest)
                low, high = (
                    request.deviceInstanceRangeLowLimit,
                    request.deviceInstanceRangeHighLimit,
                )
                assert low is not None and high is not None and 0 <= low == high <= 4194302
                self.discovery_clients[int(low)] = source
                while len(self.discovery_clients) > 16:
                    self.discovery_clients.pop(next(iter(self.discovery_clients)))
                payload = b"\x01\x00" + apdu
                forwarded = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
                self.discovery_requests.append(
                    {
                        "candidate": int(low),
                        "frame": frame.hex(),
                        "apdu": apdu.hex(),
                        "forwarded": forwarded.hex(),
                    }
                )
                self.transport.sendto(forwarded, self.upstream)
            except Exception as error:
                self.errors.append(repr(error))
            return
        if source == self.upstream and npdu[:4] == b"\x01\x00\x10\x00":
            try:
                assert frame[:2] == b"\x81\x0a" and int.from_bytes(frame[2:4], "big") == len(frame)
                apdu = npdu[2:]
                reply = APCISequence.decode(APDU.decode(PDU(apdu)))
                assert isinstance(reply, IAmRequest) and reply.iAmDeviceIdentifier[0] == 8
                candidate = int(reply.iAmDeviceIdentifier[1])
                recipient = self.discovery_clients.pop(candidate)
                payload = b"\x01\x08\x0b\xb9\x01\x07" + apdu
                forwarded = b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload
                self.discovery_responses.append(
                    {
                        "candidate": candidate,
                        "frame": frame.hex(),
                        "apdu": apdu.hex(),
                        "forwarded": forwarded.hex(),
                    }
                )
                self.transport.sendto(forwarded, recipient)
            except Exception as error:
                self.errors.append(repr(error))
            return
        return super().datagram_received(frame, source)


def controller_storage(peer, *, rekey_bindings=True):
    original_who_is = peer.do_WhoIsRequest

    async def who_is(self, request):
        self.events.append(
            (
                "who-is",
                request.deviceInstanceRangeLowLimit,
                request.deviceInstanceRangeHighLimit,
                self.instance,
            )
        )
        await original_who_is(request)

    peer.do_WhoIsRequest = types.MethodType(who_is, peer)

    async def restored(self, request):
        previous = self.instance
        await NativePeer.do_ReinitializeDeviceRequest(self, request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            if rekey_bindings:
                self.files[11] = rekey(self.files[11], previous, self.instance)
            self.device_object.objectIdentifier = ObjectIdentifier((8, self.instance))

    peer.do_ReinitializeDeviceRequest = types.MethodType(restored, peer)


async def test_owned_instance_router_forwards_actual_who_is_and_wraps_actual_i_am(native_link):
    from bms_tool.device_instance import DeviceInstances
    from bms_tool.native_applications import NativePreview

    peer, _, _, service, target = native_link
    controller_storage(peer)
    host, port = target["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: InstanceRouter((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    try:
        options = NativePreview(
            address="3001:7",
            router=proxy.endpoint,
            dnet=3001,
            device="device,5136",
            operation_id="actual-routed-collision",
            capture_id="0" * 32,
            new_instance=5136,
        )
        occupied = await DeviceInstances._collision(service.instances, options)
        assert occupied["devices"] and occupied["devices"][0]["device"] == "device,5136", occupied
        assert len(proxy.discovery_requests) == len(proxy.discovery_responses) == 1
        assert (
            bytes.fromhex(proxy.discovery_requests[0]["forwarded"])[6:].hex()
            == proxy.discovery_requests[0]["apdu"]
        )
        assert (
            bytes.fromhex(proxy.discovery_responses[0]["forwarded"])[10:].hex()
            == proxy.discovery_responses[0]["apdu"]
        )
        options.new_instance = 5336
        unused = await DeviceInstances._collision(service.instances, options)
        assert not unused["devices"]
        assert len(proxy.discovery_requests) == 2 and len(proxy.discovery_responses) == 1
        assert ("who-is", 5136, 5136, 5136) in peer.events and (
            "who-is",
            5336,
            5336,
            5136,
        ) in peer.events
        assert not proxy.errors
    finally:
        transport.close()
        await asyncio.sleep(0.02)


async def recovery_review(link, *, target=None, rekey_post=True):
    peer, _, _, service, direct = link
    target = target or direct
    peer.files = signal_files()
    controller_storage(peer, rekey_bindings=rekey_post)
    capture = await service.capture(**target, operation_id="capture-before-instance")
    plan = await service.preview(
        **target,
        operation_id="review-instance-forward",
        capture_id=capture["id"],
        new_instance=5336,
    )
    parent = await service.apply(**apply_request(plan))
    assert parent["result"]["status"] == "verified", parent
    current_target = target | {"device": "device,5336"}
    capture = await service.capture(**current_target, operation_id="capture-instance-recovery")
    prepared = service.instance_recovery.prepare(
        {
            "receipt_id": parent["intent"]["id"],
            "capture_id": capture["id"],
            "snapshot_sha256": capture["snapshot_evidence_sha256"],
        }
    )
    proposal = prepared["proposal"] | {"recovery_origin_sha256": prepared["origin_sha256"]}
    plan = await service.preview_instance_recovery(
        **current_target, operation_id="review-instance-recovery", **proposal
    )
    return parent, capture, prepared, proposal, plan, current_target


@pytest.mark.parametrize("routed", [False, True])
async def test_new_previous_instance_transfer_checks_collision_and_preserves_fresh_settings(
    native_link, routed
):
    peer, _, _, service, target = native_link
    transport = proxy = None
    checked = []
    original_collision = service.instances._collision

    async def collision(options):
        checked.append(options.new_instance)
        return await original_collision(options)

    service.instances._collision = collision
    if routed:
        host, port = target["address"].split(":")
        transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: NativeRouter((host, int(port))), local_addr=("127.0.0.1", 0)
        )
        target = target | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        parent, _, prepared, _, plan, _ = await recovery_review(native_link, target=target)
        assert checked == [5336, 5336, 5136]
        peer.files = set_saved(peer.files, 17.5, second=True)
        real_slot(peer.files, 4, struct.pack(">f", 9.25))
        fresh = copy.deepcopy(peer.files)
        start = len(mutations(peer))
        result = await service.apply(**apply_request(plan))
        assert result["result"]["status"] == "verified", result
        assert checked == [5336, 5336, 5136, 5136]
        assert result["intent"]["id"] != parent["intent"]["id"]
        assert result["intent"]["recovery_origin"] == prepared["origin"]
        assert service.storage.load(result["intent"]["backup_id"])[1] == fresh
        assert result["intent"]["old_instance"] == 5336 and result["intent"]["new_instance"] == 5136
        assert peer.instance == 5136 and peer.metadata["object-name"] == "Authored controller"
        from bms_tool.moi_identity import MoiIdentity

        parsed = MoiIdentity(peer.files[3])
        assert parsed.reader.scalar(parsed.root, 900) == 9.25
        assert parsed.reader.scalar(parsed.reader.records["controller/signal-11"], 3113) == 17.5
        assert result["result"]["preservation"]["application_identical_except_instance"]
        assert service.storage.receipt(parent["intent"]["id"]) == parent
        changes = mutations(peer)[start:]
        assert (
            changes.count(("state", "start-restore"))
            == changes.count(("state", "end-restore"))
            == 1
        )
        assert all(row[1] == 3 for row in changes if row[0] == "write")
        with pytest.raises(ValueError, match="consumed"):
            await service.apply(**apply_request(plan))
        assert mutations(peer)[start:] == changes
        if proxy:
            assert not proxy.errors and len(proxy.requests) == len(proxy.responses)
    finally:
        if transport:
            transport.close()
            await asyncio.sleep(0.02)


@pytest.mark.parametrize(
    "change", ["number", "hash", "parent", "missing", "name", "ordinary-route"]
)
async def test_changed_or_cross_kind_proposal_refuses_before_network(native_link, change):
    peer, _, _, service, _ = native_link
    _, _, _, proposal, _, target = await recovery_review(native_link)
    proposal = dict(proposal)
    if change == "number":
        proposal["new_instance"] = 5137
    elif change == "hash":
        proposal["recovery_origin_sha256"] = "0" * 64
    elif change == "parent":
        proposal["recovery_parent_receipt"] = "0" * 32
    elif change == "missing":
        del proposal["snapshot_sha256"]
    elif change == "name":
        proposal["new_name"] = "Different name"
    before = list(peer.events)
    with pytest.raises(ValueError):
        await (
            service.preview if change == "ordinary-route" else service.preview_instance_recovery
        )(**target, operation_id="reject-instance-recovery", **proposal)
    assert peer.events == before


@pytest.mark.parametrize(
    "change",
    ["collision", "directory", "parent-pending", "verified-backup", "allocation-confirmation"],
)
async def test_recovery_apply_rechecks_fresh_evidence_and_reservation_before_restore(
    native_link, change
):
    peer, _, store, service, _ = native_link
    parent, _, prepared, _, plan, _ = await recovery_review(native_link)
    request = apply_request(plan)
    if change == "collision":

        async def occupied(options):
            return {
                "devices": [{"device": "device,5136"}],
                "scope": "Authored new collision",
                "limitation": "Unavailable number",
            }

        service.instances._collision = occupied
    elif change == "directory":
        peer.files[11] += b"changed"
    elif change == "parent-pending":
        with store.connect() as db:
            db.execute(
                "UPDATE application_transfers SET pending=1 WHERE id=?", (parent["intent"]["id"],)
            )
    elif change == "verified-backup":
        (
            service.storage.directory
            / prepared["origin"]["verified_after_capture_id"]
            / "file-3.bin"
        ).unlink()
    else:
        request["allocation_confirmed"] = False
    start = len(mutations(peer))
    try:
        result = await service.apply(**request)
    except ValueError:
        result = None
    if result:
        assert result["result"]["status"] == "not_sent", result
    assert not any(
        row[0] == "write" or row == ("state", "start-restore") for row in mutations(peer)[start:]
    )


async def test_lost_recovery_commit_reads_back_after_restart_without_original_ancestor_files(
    native_link,
):
    peer, bacnet, store, service, _ = native_link
    parent, _, prepared, _, plan, _ = await recovery_review(native_link)
    peer.mode = "drop-end"
    start = len(mutations(peer))
    uncertain = await service.apply(**apply_request(plan))
    assert uncertain["pending"] and uncertain["result"]["may_have_applied"]
    restored = mutations(peer)[start:]
    (service.storage.directory / parent["intent"]["backup_id"] / "file-3.bin").unlink()
    (
        service.storage.directory / prepared["origin"]["verified_after_capture_id"] / "file-3.bin"
    ).unlink()
    await service.close()
    restarted = NativeApplications(bacnet, store, service.instances, request_timeout=0.1, gap=0)
    try:
        result = await restarted.reconcile(
            receipt_id=uncertain["intent"]["id"], operation_id="readback-instance-restart"
        )
        assert not result["pending"] and result["latest_readback"]["status"] == "verified", result
        assert [
            row
            for row in mutations(peer)[start:]
            if row[0] == "write" or row[1] in ("start-restore", "end-restore")
        ] == restored
    finally:
        await restarted.close()


async def test_fresh_unmatched_root_value_cannot_activate_only_after_the_number_changes(
    native_link,
):
    peer, _, _, service, _ = native_link
    _, _, _, _, plan, _ = await recovery_review(native_link, rekey_post=False)
    real_slot(peer.files, 4, struct.pack(">f", 9.25))
    start = len(mutations(peer))
    result = await service.apply(**apply_request(plan))
    assert result["result"]["status"] == "not_sent", result
    assert not any(
        row[0] == "write" or row == ("state", "start-restore") for row in mutations(peer)[start:]
    )
