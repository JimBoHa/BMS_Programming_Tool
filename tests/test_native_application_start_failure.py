"""Read back an interrupted observation from an authored UDP controller."""

from types import MethodType

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.basetypes import DateTime, TimeStamp
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import Date, ObjectIdentifier, Time, Unsigned
from bms_tool import native_inline_shadow as shadow
from bms_tool.moi_identity import MoiIdentity, sha

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_monitor import observation_peer
from .test_native_inline_sequence import authored_source


@pytest.mark.parametrize(
    "scenario",
    [
        "complete",
        "short-blocks",
        "last-byte",
        "early-eof",
        "unacknowledged",
        "different-model",
        "new-restart",
        "no-date",
    ],
)
async def test_acknowledged_archive_and_original_are_bound_without_field_writes(
    native_link, scenario
):
    peer, _, _, service, target = native_link
    observation_peer(peer, "")
    peer.files = authored_source(catalog=True)
    donor = await service.capture(**target, operation_id="capture-library")
    peer.files = authored_source()
    cap = await service.capture(**target, operation_id="capture-original")
    original, files = service.storage.load(cap["id"])
    selection = {
        "sampling_mode": "elapsed-phase",
        "first_instance": 200,
        "prototype_capture_id": donor["id"],
        "prototype_sha256": donor["snapshot_evidence_sha256"],
    }
    failed, compilation = shadow.compile_shadow(service, original["identity"], selection, files)
    parent = service.storage.intent(
        {
            "id": "f" * 32,
            "target": cap["target"],
            "identity": cap["identity"],
            "old_name": cap["identity"]["object-name"],
            "new_name": cap["identity"]["object-name"],
            "old_instance": peer.instance,
            "new_instance": peer.instance,
            "connector_config": service.bacnet.config,
            "change_kind": shadow.KIND,
            "operation_profile": shadow.PROFILE,
            "sequence_observation_confirmed": True,
            "backup_id": cap["id"],
            "compilation": compilation,
            "sequence_selection": selection,
            "payload_sha256": sha(failed),
            "native_payload_sha256": sha(MoiIdentity(failed).data),
        }
    )
    service.storage.event(
        parent["id"],
        "application-file-acknowledged",
        {"file": 3, "bytes": len(failed), "sha256": sha(failed)},
    )
    if scenario != "unacknowledged":
        service.storage.event(parent["id"], "ack-end-restore", {})
    service.storage.finish(
        parent["id"],
        {
            "status": "unknown",
            "may_have_applied": True,
            "protocol_accepted": True,
            "intent_sha256": parent["evidence_sha256"],
        },
    )

    peer.files[3] = (
        failed[:-1] + bytes([failed[-1] ^ 1]) if scenario == "last-byte" else failed
    ) + b"unused storage"
    reported_size = len(peer.files[3])
    if scenario == "early-eof":
        peer.files[3] = failed[:-1]
    if scenario == "short-blocks":
        read_file = peer.do_AtomicReadFileRequest

        async def smaller_blocks(self, req):
            access = req.accessMethod.streamAccess
            access.requestedOctetCount = min(113, int(access.requestedOctetCount))
            await read_file(req)

        peer.do_AtomicReadFileRequest = MethodType(smaller_blocks, peer)
    peer.instance = 1
    peer.metadata.update(
        {"system-status": 2, "object-name": "No Application", "application-software-version": ""}
    )
    if scenario == "different-model":
        peer.metadata["model-name"] = "unrelated"
    previous = peer.do_ReadPropertyRequest
    dates = []

    async def read(self, req):
        prop = str(req.propertyIdentifier)
        if req.objectIdentifier == ObjectIdentifier((10, 3)) and prop == "file-size":
            value = Unsigned(reported_size)
        elif prop == "last-restore-time":
            dates.append(1)
            value = TimeStamp(
                dateTime=DateTime(
                    date=Date("2020-01-03"),
                    time=Time(
                        "03:04:05" if len(dates) == 1 or scenario != "new-restart" else "03:06:07"
                    ),
                )
            )
            if scenario == "no-date":
                value = TimeStamp(sequenceNumber=0)
        else:
            return await previous(req)
        await self.response(
            ReadPropertyACK(
                context=req,
                objectIdentifier=req.objectIdentifier,
                propertyIdentifier=req.propertyIdentifier,
                propertyValue=Any(value),
            )
        )

    peer.do_ReadPropertyRequest = MethodType(read, peer)
    old_events = list(peer.events)
    result = await service.reconcile(receipt_id=parent["id"], operation_id="inspect-failed-start")
    assert result["pending"] and result["result"]["status"] == "unknown"
    actual = result["latest_readback"]
    assert actual["status"] == "unknown"
    if scenario in ("unacknowledged", "different-model"):
        assert "application_start" not in actual
    else:
        details = actual["application_start"]
        assert details["read_only"] and actual["read_only"]
        assert actual["backup_effects"]["possible_state_commands"] == []
        if scenario not in ("complete", "short-blocks"):
            assert details["status"] == "unconfirmed" and "original_export_sha256" not in details
        else:
            assert details["status"] == "image_present_application_not_running", details
            assert details["image_sha256"] == sha(failed) and details["compared_bytes"] == len(
                failed
            )
            out, report = service.restore_source(
                {
                    "restore_capture_id": details["original_capture_id"],
                    "restore_snapshot_sha256": details["original_snapshot_sha256"],
                }
            )
            assert (
                report["identity"] == original["identity"]
                and sha(out) == details["original_export_sha256"]
            )
    assert all(e[0] not in ("state", "write") for e in peer.events[len(old_events) :])
