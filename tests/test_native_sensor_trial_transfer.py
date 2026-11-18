"""Isolated UDP qualification of trial admission, transfers, observations and recovery."""

import copy
import types

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.basetypes import StatusFlags
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import Boolean, Enumerated, ObjectIdentifier, Real, TagList, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inputs import raw_property
from bms_tool.native_sensor_trial import source_app
from bms_tool.native_sensor_trial_transfer import (
    SensorApply,
    SensorPreview,
    SensorReceipt,
    SensorTrials,
)

from .test_native_applications import native_link as native_link
from .test_native_sensor_trial import edit_for, sensor_source


def install_sensor_peer(link):
    peer, _, _, native, _ = link
    peer.files = sensor_source()
    peer.sensor_online = {205}
    peer.next_object = 3000000
    peer.sensor_fault = ""
    peer.sensor_review_sequence = 0
    original = peer.do_ReadPropertyRequest

    async def read(self, request):
        obj, pid = request.objectIdentifier, int(request.propertyIdentifier)
        if obj == ObjectIdentifier((307, 2)):
            if pid == 75:
                value = Any(ObjectIdentifier(obj))
            elif pid == 673:
                value = Any(Boolean(self.sensor_fault != "port-disabled"))
            elif pid == 81:
                value = Any(Boolean(self.sensor_fault == "port-out-of-service"))
            elif pid == 1036:
                value = Any(Unsigned(205 if self.sensor_fault == "external-comtest" else 0))
            else:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
        elif int(obj[0]) == 8 and pid == 787:
            value = Any(Unsigned(self.next_object))
        elif int(obj[0]) in (0, 627, 910):
            app = MoiIdentity(self.files[3])
            row = next((r for r in app.records if app.reader.scalar(r, 75) == str(obj)), None)
            if row is None:
                if self.sensor_fault == "silent-absence":
                    return
                if self.sensor_fault == "property-absence":
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                raise ExecutionError(errorClass="object", errorCode="unknown-object")
            mac = app.reader.scalar(row, 2858)
            if int(obj[0]) == 0:
                parent = next(
                    r
                    for r in app.records
                    if r["class_id"] == 627
                    and app.reader.scalar(row, 32527).startswith(app.reader.scalar(r, 32527) + ".")
                )
                mac = app.reader.scalar(parent, 2858)
            if pid == 75:
                value = Any(ObjectIdentifier(obj))
            elif pid == 673:
                value = Any(Boolean(app.reader.scalar(row, 673) is not False))
            elif pid == 913:
                value = Any(
                    Boolean(
                        self.sensor_fault != "existing-online"
                        if int(obj[0]) == 910
                        else mac not in self.sensor_online
                    )
                )
            elif pid == 85:
                value = Any(Real(70.5 if mac in self.sensor_online else 0))
            elif pid == 103:
                value = Any(Enumerated(0 if mac in self.sensor_online else 12))
            elif pid == 81:
                value = Any(Boolean(self.sensor_fault == "out-of-service"))
            elif pid == 111:
                value = Any(StatusFlags([0, 0, int(self.sensor_fault == "overridden"), 0]))
            else:
                raw = raw_property(app, row, 2390 if pid == 77 else pid)
                if raw is None:
                    raise ExecutionError(errorClass="property", errorCode="unknown-property")
                value = Any(TagList.decode(PDUData(raw[:-1])))
            if self.sensor_fault == "wrong-object" and pid == 75:
                value = Any(ObjectIdentifier((0, 42)))
        else:
            return await original(request)
        await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=obj,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=value,
            )
        )

    peer.do_ReadPropertyRequest = types.MethodType(read, peer)
    return peer, native, SensorTrials(native) if native is not None else None


async def preview(link, trials, action="install", origin=None):
    peer, _, _, native, target = link
    peer.sensor_review_sequence += 1
    suffix = action + "-" + str(peer.sensor_review_sequence)
    capture = await native.capture(**target, operation_id="capture-sensor-" + suffix)
    args = {
        **target,
        "operation_id": "review-sensor-" + suffix,
        "action": action,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    if action == "install":
        args["edit"] = edit_for(peer.files, list(range(199, 207)))
    else:
        args["trial_receipt"] = origin
    return await trials.preview(SensorPreview(**args))


def confirmation(plan):
    return SensorApply(
        operation_id="apply-sensor-" + plan["request"]["action"],
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        sensor_trial_confirmed=True,
        application_transfer_confirmed=True,
    )


def receipt_request(link, receipt_id, suffix="first"):
    return SensorReceipt(**link[-1], operation_id="sensor-read-" + suffix, receipt_id=receipt_id)


async def test_install_observe_restore_all_use_real_udp_and_preserve_control_configuration(
    native_link,
):
    peer, native, trials = install_sensor_peer(native_link)
    original = copy.deepcopy(peer.files)
    plan = await preview(native_link, trials)
    assert not any(e[0] == "write" for e in peer.events)
    applied = await trials.apply(confirmation(plan))
    assert applied["result"]["status"] == "verified", applied
    assert not applied["result"]["sensor_communication_verified"]
    assert not applied["pending"]
    observation = await trials.observe(receipt_request(native_link, applied["intent"]["id"]))
    assert observation["read_only"]
    assert [r["address"] for r in observation["readings"] if r["status"] == "live"] == [205]
    assert [r["temperature"] for r in observation["readings"] if r["status"] == "live"] == [70.5]
    assert all(
        r["reliability"] == 12 for r in observation["readings"] if r["status"] == "unreliable"
    )
    with pytest.raises(ValueError, match="consumed"):
        await trials.apply(confirmation(plan))
    restore = await preview(native_link, trials, "restore", applied["intent"]["id"])
    restored = await trials.apply(confirmation(restore))
    assert restored["result"]["status"] == "verified", restored
    assert source_app(peer.files)[0].data == source_app(original)[0].data
    assert not native.has_pending()
    with pytest.raises(ValueError, match="already been restored"):
        await trials.observe(receipt_request(native_link, applied["intent"]["id"], "restored"))
    assert [e for e in peer.events if e == ("state", "start-restore")] == [
        ("state", "start-restore")
    ] * 2
    assert all(e[1] == 3 for e in peer.events if e[0] == "write")


@pytest.mark.parametrize(
    "fault",
    [
        "silent-absence",
        "property-absence",
        "existing-online",
        "wrong-object",
        "port-disabled",
        "port-out-of-service",
        "external-comtest",
    ],
)
async def test_unattributable_absence_or_working_existing_sensor_blocks_trial(native_link, fault):
    peer, _, trials = install_sensor_peer(native_link)
    peer.sensor_fault = fault
    with pytest.raises(ValueError):
        await preview(native_link, trials)
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize(
    "change", ["allocator", "firmware", "configuration", "credentials", "expired"]
)
async def test_stale_review_is_consumed_without_restore_or_file_write(native_link, change):
    peer, native, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    if change == "allocator":
        peer.next_object = 4000000
    elif change == "firmware":
        peer.metadata["firmware-revision"] = "authored-changed"
    elif change == "configuration":
        # A real saved inline field changes the effective configuration.
        peer.files[11] = peer.files[11].replace(b"saved", b"other")
    elif change == "credentials":
        native.credentials.set("authored-backup", "different-restore")
    else:
        trials.plans[plan["token"]]["expires"] = 0
    if change == "expired":
        with pytest.raises(ValueError, match="expired"):
            await trials.apply(confirmation(plan))
    else:
        result = await trials.apply(confirmation(plan))
        assert result["result"]["status"] == "not_sent", result
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


@pytest.mark.parametrize("mode", ["drop-start", "drop-block", "drop-end"])
async def test_lost_ack_retains_uncertainty_and_readback_never_replays_download(native_link, mode):
    peer, native, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    peer.mode = mode
    result = await trials.apply(confirmation(plan))
    assert result["pending"] and result["result"]["status"] == "unknown", result
    count = len([e for e in peer.events if e[0] == "write"])
    peer.mode = "normal"
    reopened = SensorTrials(native)
    readback = await reopened.readback(receipt_request(native_link, result["intent"]["id"]))
    expected = "verified" if mode == "drop-end" else "recovered_original"
    assert readback["latest_readback"]["status"] == expected
    assert not readback["pending"]
    assert len([e for e in peer.events if e[0] == "write"]) == count


async def test_cancelled_review_cannot_be_applied_and_shutdown_retires_reviews(native_link):
    _, native, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    native.cancel(plan["request"]["operation_id"])
    with pytest.raises(ValueError, match="absent"):
        await trials.apply(confirmation(plan))
    plan = await preview(native_link, trials)
    await native.close()
    assert not trials.plans


@pytest.mark.parametrize("fault", ["out-of-service", "overridden"])
async def test_out_of_service_or_overridden_temperature_never_becomes_a_valid_sensor_result(
    native_link, fault
):
    peer, _, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    result = await trials.apply(confirmation(plan))
    assert result["result"]["status"] == "verified"
    peer.sensor_fault = fault
    observed = await trials.observe(receipt_request(native_link, result["intent"]["id"]))
    assert not any(r["status"] == "live" for r in observed["readings"])


async def test_common_native_history_readback_routes_to_sensor_verification_and_survives_observation(
    native_link,
):
    peer, native, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    peer.mode = "drop-end"
    applied = await trials.apply(confirmation(plan))
    assert applied["pending"]
    peer.mode = "normal"
    receipt_id = applied["intent"]["id"]
    result = await native.reconcile(operation_id="history-sensor-readback", receipt_id=receipt_id)
    assert result["latest_readback"]["status"] == "verified" and not result["pending"]
    await trials.observe(receipt_request(native_link, receipt_id, "after-history"))
    retained = next(r for r in trials.status()["receipts"] if r["intent"]["id"] == receipt_id)
    assert retained["latest_readback"]["status"] == "verified"
    assert retained["result"]["status"] == "unknown"  # The failed attempt remains immutable.


async def test_external_allocator_change_during_fresh_backup_is_rechecked_before_restore(
    native_link,
):
    peer, _, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    original = peer.do_ReinitializeDeviceRequest

    async def change(self, request):
        await original(request)
        if str(request.reinitializedStateOfDevice) == "end-backup":
            self.next_object = 4000000

    peer.do_ReinitializeDeviceRequest = types.MethodType(change, peer)
    result = await trials.apply(confirmation(plan))
    assert result["result"]["status"] == "not_sent"
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)


async def test_review_expiring_after_final_reads_sends_no_restore_request(native_link):
    peer, _, trials = install_sensor_peer(native_link)
    plan = await preview(native_link, trials)
    retained = trials.plans[plan["token"]]
    original = peer.do_ReadPropertyRequest

    async def expire(self, request):
        if (
            request.objectIdentifier == ObjectIdentifier((10, 3))
            and int(request.propertyIdentifier) == 3380
        ):
            retained["expires"] = 0
        await original(request)

    peer.do_ReadPropertyRequest = types.MethodType(expire, peer)
    result = await trials.apply(confirmation(plan))
    assert result["result"]["status"] == "not_sent" and not result["pending"]
    assert "expired before restore dispatch" in result["result"]["errors"][0]
    assert not any(e[0] == "write" or e == ("state", "start-restore") for e in peer.events)
