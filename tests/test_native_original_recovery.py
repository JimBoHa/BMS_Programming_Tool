"""Explicit readback distinguishes a recovered original from the proposed change."""

import copy
import gzip

import pytest
from bms_tool.device_instance import DeviceInstances
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_applications import NativeApplications

from .test_native_applications import apply_request, review
from .test_native_applications import native_link as native_link  # noqa: F401


async def interrupted(link, *, renaming=False):
    peer, _, _, service, target = link
    original = copy.deepcopy(peer.files)
    if renaming:
        capture = await service.capture(**target, operation_id="original-name-capture")
        plan = await service.preview(
            **target,
            operation_id="original-name-review",
            capture_id=capture["id"],
            new_instance=5136,
            new_name="Reviewed name",
        )
    else:
        _, plan = await review(link)
    peer.mode = "drop-end"
    result = await service.apply(**{**apply_request(plan), "name_change_confirmed": renaming})
    assert result["pending"] and result["result"]["status"] == "unknown"
    peer.mode = "normal"
    return original, result


def recovered(peer, original):
    merged, _ = ParameterApplication(original[3], original[11], original[12]).compile()
    peer.files = {**original, 3: merged}
    peer.instance = 5136
    peer.metadata["object-name"] = "Authored controller"
    peer.metadata["system-status"] = 0


@pytest.mark.parametrize("renaming", [False, True])
async def test_complete_original_recovery_resolves_uncertainty_without_replaying_a_restore(
    native_link, renaming
):
    peer, bacnet, store, service, target = native_link
    original, attempt = await interrupted(native_link, renaming=renaming)
    recovered(peer, original)
    before = [e for e in peer.events if e[0] == "write" or (e[0] == "state" and "restore" in e[1])]
    result = await service.reconcile(
        operation_id="verify-original-recovery", receipt_id=attempt["intent"]["id"]
    )
    row = result["latest_readback"]
    assert row["status"] == "recovered_original" and not result["pending"], result
    assert row["proposed_change_verified"] is False
    assert row["preservation"]["saved_application_parameters_verified"] == 7
    assert row["native_sha256"] == row["expected_native_sha256"]
    assert (
        row["recovery"]["original_reviewed_native_sha256"]
        == attempt["intent"]["native_payload_sha256"]
    )
    assert [
        e for e in peer.events if e[0] == "write" or (e[0] == "state" and "restore" in e[1])
    ] == before
    reopened = NativeApplications(bacnet, store, DeviceInstances(bacnet, store))
    assert (
        reopened.storage.receipt(attempt["intent"]["id"])["latest_readback"]["status"]
        == "recovered_original"
    )
    reopened.storage.available(attempt["intent"]["target"])


@pytest.mark.parametrize(
    "condition", ["different-image", "different-saved-value", "not-operational"]
)
async def test_identity_alone_or_partial_recovery_cannot_resolve_a_transfer(native_link, condition):
    peer, _, _, service, _ = native_link
    original, attempt = await interrupted(native_link, renaming=True)
    recovered(peer, original)
    if condition == "different-image":
        peer.files[3] = gzip.compress(
            gzip.decompress(peer.files[3]).replace(b"opaque footer", b"unsafe footer"), mtime=0
        )
    elif condition == "different-saved-value":
        peer.files[11] = peer.files[11].replace(b"saved", b"other")
    else:
        peer.metadata["system-status"] = 2
    result = await service.reconcile(
        operation_id="incomplete-original-readback", receipt_id=attempt["intent"]["id"]
    )
    assert result["pending"] and result["latest_readback"]["status"] == "unknown"
    assert peer.events.count(("state", "start-restore")) == 1


async def test_original_point_name_is_verified_against_its_published_name(native_link):
    from .test_native_point_names import apply_args, name_review

    peer, _, _, service, _ = native_link
    _, plan = await name_review(native_link)
    original = copy.deepcopy(peer.files)
    peer.mode = "drop-end"
    attempt = await service.apply_point_name(**apply_args(plan))
    assert attempt["pending"]
    peer.mode = "normal"
    recovered(peer, original)
    result = await service.reconcile(
        operation_id="original-point-readback", receipt_id=attempt["intent"]["id"]
    )
    assert not result["pending"] and result["latest_readback"]["status"] == "recovered_original"
    assert result["latest_readback"]["published_point_name"] == "Authored input"
