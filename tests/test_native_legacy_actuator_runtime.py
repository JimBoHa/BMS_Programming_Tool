"""Version-scoped changing seconds state cannot excuse application/configuration edits."""

import copy

import pytest
from bms_tool.application_preservation import verify_preservation
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc

from .test_native_applications import apply_request, review
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_parameter_qualification import actuator_parameters


def snapshots(*, acs=60, dmcs=60, current=123457, cid=251, pid=978):
    archive, static, dynamic = actuator_parameters(acs, dmcs)
    app = MoiIdentity(archive)
    data, directory = bytearray(archive), bytearray(static)
    record = app.records[1]
    data[record["offset"] : record["offset"] + 2] = cid.to_bytes(2, "little")
    data[record["offset"] + 6 : record["offset"] + 10] = (cid << 22 | 2131).to_bytes(4, "big")
    directory[6:8] = pid.to_bytes(2, "big")
    directory[10:12] = cid.to_bytes(2, "big")
    before = {3: bytes(data), 11: bytes(directory), 12: dynamic}
    merged, _ = ParameterApplication(before[3], before[11], before[12]).compile()
    editor = MoiIdentity(merged)
    query = dict(source_sha256=editor.source_sha256, expected_instance=5136, new_instance=5336)
    plan = editor.preview(**query)
    output, _ = editor.export(**query, plan_sha256=plan["plan_sha256"])
    payload = current.to_bytes(4, "big")
    after = {3: output, 11: before[11], 12: payload + bytes([header_crc(payload) ^ 255])}
    return before, after


def test_native_60_actuator_state_can_advance_with_exact_configuration_preservation():
    before, after = snapshots()
    proof = verify_preservation(before, after, old_instance=5136, new_instance=5336)
    assert proof["application_identical_except_instance"]
    assert proof["saved_application_parameters_verified"] == 1
    row = proof["runtime_counter_changes"][0]
    assert (row["class"], row["property"]) == (251, 978)
    assert (row["application_value"], row["current_saved_value"]) == (123456, 123457)
    assert proof["device_calculated_changes"] == []


@pytest.mark.parametrize(
    "options",
    [{"acs": 62, "dmcs": 62}, {"acs": 102, "dmcs": 102}, {"dmcs": 62}, {"cid": 250}, {"pid": 979}],
)
def test_exception_does_not_extend_to_other_versions_classes_or_properties(options):
    before, after = snapshots(**options)
    with pytest.raises(ValueError, match="current saved parameter differs"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


def test_decreasing_actuator_seconds_state_requires_review():
    before, after = snapshots(current=123455)
    with pytest.raises(ValueError, match="seconds state decreased"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


def test_counter_advance_cannot_hide_changed_application_bytes():
    before, after = snapshots()
    after[3] = after[3].replace(b"controller/actuator", b"controller/changedx")
    with pytest.raises(ValueError, match="Non-identity application bytes changed"):
        verify_preservation(before, after, old_instance=5136, new_instance=5336)


async def test_owned_udp_transfer_verifies_a_legacy_state_advance_without_rewriting_pss(
    native_link, monkeypatch
):
    peer, _, _, service, _ = native_link
    peer.files = dict(zip((3, 11, 12), actuator_parameters(60, 60), strict=True))
    original = copy.deepcopy(peer.files)
    handle = peer.do_ReinitializeDeviceRequest

    async def advance_state(request):
        await handle(request)
        if str(request.reinitializedStateOfDevice) == "end-restore":
            payload = (123457).to_bytes(4, "big")
            peer.files[12] = payload + bytes([header_crc(payload) ^ 255])

    monkeypatch.setattr(peer, "do_ReinitializeDeviceRequest", advance_state)
    _, plan = await review(native_link)
    receipt = await service.apply(**apply_request(plan))
    assert receipt["result"]["status"] == "verified", receipt
    assert not receipt["pending"]
    assert (
        receipt["result"]["preservation"]["runtime_counter_changes"][0]["current_saved_value"]
        == 123457
    )
    assert peer.files[11] == original[11]
    assert all(e[1] == 3 for e in peer.events if e[0] == "write")
    assert [e for e in peer.events if e == ("state", "end-restore")] == [("state", "end-restore")]
