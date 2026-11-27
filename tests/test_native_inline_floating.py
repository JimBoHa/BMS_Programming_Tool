"""Retain an external two-terminal actuator when reviewing a saved inline application."""

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inline_monitor import compile_monitor
from bms_tool.native_inline_monitor_transfer import MonitorApply, MonitorReview
from bms_tool.native_inline_monitor_transfer import review as review_monitor
from bms_tool.native_inline_sequence_62 import LegacyInlineSequenceCompiler
from bms_tool.native_inline_shadow import ShadowReview, reconstruct, review
from bms_tool.native_inputs import archive, encoded, raw_property

from .test_controller_application import native_record
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_monitor import observation_peer
from .test_native_inline_sequence import authored_source


def floating_source(model="FX-PCV1630-0", overrides=None):
    files = authored_source(model=model)
    old = MoiIdentity(files[3])
    props = {
        75: ObjectIdentifier((1, 16)),
        32527: CharacterString("controller/valve"),
        2390: CharacterString("HTG-O"),
        31: CharacterString("BO OUT2,BO OUT3"),
        117: Enumerated(98),
        519: Unsigned(2),
        990: Unsigned(2),
        991: Unsigned(3),
        3478: Real(83),
    }
    props.update(overrides or {})
    valve = native_record(251, 16, [(k, encoded(v)) for k, v in props.items() if v is not None])
    rows = [
        valve if r["class_id"] == 241 else old.data[r["offset"] : r["end_offset"]]
        for r in old.records
    ]
    return {**files, 3: archive(old, rows)}


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0"])
def test_floating_draft_preserves_actuator_damper_and_existing_wires(model):
    files = floating_source(model)
    donor = authored_source(model=model, catalog=True, wide=True)
    p = LegacyInlineSequenceCompiler(files, donor[3], 300)
    p.body()
    draft, report = p.export(shadow=True)
    wiring = report["valve_wiring"]
    assert wiring["output_type"] == "floating"
    assert wiring["floating_valve"] == {"terminals": [2, 3], "stroke_seconds": 83}
    assert report["points"]["valve"] == "analog-output,16"
    assert {k: v["default"] for k, v in report["new_avs"].items()} == {
        "VLV-LOCKOUT-CFM": 30,
        "MAX-DA-T": 125,
    }
    before, after = p.application, MoiIdentity(draft)
    for row in [p.physical["valve"], p.physical["damper"]]:
        assert after.reader.records[before.reader.scalar(row, 32527)]["sha256"] == row["sha256"]
    original_wires = before.reader.diagram(p.rootref)["connections"]
    assert after.reader.diagram(p.rootref)["connections"][: len(original_wires)] == original_wires
    assert report["old_wires_replaced"] == 0
    assert report["production_transfer_qualified"] is False
    with pytest.raises(ValueError, match="proportional inline valve"):
        compile_monitor(files, 300)


@pytest.mark.parametrize(
    "override",
    [
        {990: Unsigned(3), 991: Unsigned(3), 31: CharacterString("BO OUT3,BO OUT3")},
        {991: Unsigned(7), 31: CharacterString("BO OUT2,BO OUT7")},
        {31: CharacterString("BO OUT3,BO OUT2")},
        {519: Unsigned(1)},
        {519: Enumerated(2)},
        {75: ObjectIdentifier((0, 16))},
        {32527: CharacterString("other/valve")},
        {117: Enumerated(5)},
        {3478: Real(0)},
        {3478: Real(-1)},
        {3478: None},
        {3478: Unsigned(83)},
    ],
)
def test_floating_draft_rejects_unverified_terminal_pair_or_stroke(override):
    files = floating_source(overrides=override)
    donor = authored_source(catalog=True, wide=True)
    with pytest.raises(ValueError, match="floating valve|I/O property"):
        LegacyInlineSequenceCompiler(files, donor[3], 300)
    with pytest.raises(ValueError, match="floating valve|I/O property"):
        compile_monitor(files, 300, allow_floating=True)


@pytest.mark.parametrize(
    "change", ["none", "terminal order", "stroke before apply", "terminal label"]
)
async def test_floating_monitor_validates_live_wiring_and_recovers_original(native_link, change):
    peer, _, _, native, target = native_link
    binding = {
        31: CharacterString("BO OUT2,BO OUT3"),
        990: Unsigned(2),
        991: Unsigned(3),
        3478: Real(83),
    }
    observation_peer(peer, "", floating=binding)
    original = floating_source()
    peer.files = dict(original)
    capture = await native.capture(**target, operation_id="capture-floating-monitor")
    options = MonitorReview(
        **target,
        operation_id="review-floating-monitor",
        capture_id=capture["id"],
        snapshot_sha256=capture["snapshot_evidence_sha256"],
        first_instance=100,
    )
    if change == "terminal order":
        binding[990], binding[991] = binding[991], binding[990]
    if change == "terminal label":
        binding[31] = CharacterString("BO OUT3,BO OUT2")
    if change in ("terminal order", "terminal label"):
        with pytest.raises(ValueError, match="terminal"):
            await review_monitor(native, options)
        assert ("state", "start-restore") not in peer.events
        return

    plan = await review_monitor(native, options)
    assert plan["compilation"]["floating_valve"] == {"terminals": [2, 3], "stroke_seconds": 83}
    if change == "stroke before apply":
        binding[3478] = Real(84)
    receipt = await native.apply_reviewed(
        MonitorApply(
            operation_id="apply-floating-monitor",
            token=plan["token"],
            review_sha256=plan["review_sha256"],
            monitor_confirmed=True,
            application_transfer_confirmed=True,
        ),
        default_edit=False,
        inline_kind="inline-monitor",
    )
    if change == "stroke before apply":
        assert receipt["result"]["status"] == "not_sent"
        assert ("state", "start-restore") not in peer.events
        return

    assert receipt["result"]["status"] == "verified", receipt["result"]
    assert receipt["result"]["diagnostic_execution"]["status"] == "advancing"
    before, after = MoiIdentity(original[3]), MoiIdentity(peer.files[3])
    for ref in ("controller/valve", "controller/damper"):
        assert before.reader.records[ref]["sha256"] == after.reader.records[ref]["sha256"]
    original_wires = before.reader.diagram(plan["compilation"]["root"])["connections"]
    assert after.reader.diagram(plan["compilation"]["root"])["connections"][:-1] == original_wires
    restore = await native.preview_snapshot_restore(
        **target,
        operation_id="review-floating-original",
        restore_capture_id=capture["id"],
        restore_snapshot_sha256=capture["snapshot_evidence_sha256"],
    )
    restored = await native.apply_snapshot_restore(
        operation_id="restore-floating-original",
        token=restore["token"],
        review_sha256=restore["review_sha256"],
        historical_application_confirmed=True,
        application_transfer_confirmed=True,
    )
    assert restored["result"]["status"] == "verified"
    assert restored["result"]["preservation"]["effective_saved_application_values_verified"]
    assert peer.files[11] == original[11] and peer.files[12] == original[12]
    assert peer.events.count(("state", "start-restore")) == 2


def test_heat_sink_cannot_bind_to_integral_damper_with_same_percent_units():
    files = floating_source()
    capture = MoiIdentity(files[3])
    rows = []
    for row in capture.records:
        if row["class_id"] != 251:
            rows.append(capture.data[row["offset"] : row["end_offset"]])
            continue
        instance = 17 if capture.reader.scalar(row, 2390) == "HTG-O" else 16
        fields = [(k, raw_property(capture, row, k)[:-1]) for k in row["properties"] if k != 75]
        fields.append((75, encoded(ObjectIdentifier((1, instance)))))
        rows.append(native_record(251, instance, fields))
    donor = authored_source(catalog=True, wide=True)
    compiler = LegacyInlineSequenceCompiler({**files, 3: archive(capture, rows)}, donor[3], 300)
    with pytest.raises(ValueError, match="heat sink must reference"):
        compiler.body()


async def test_floating_draft_review_works_disconnected_and_cannot_reconstruct_a_transfer(
    native_link,
):
    peer, _, _, service, target = native_link
    observation_peer(peer, "")
    peer.files = authored_source(catalog=True, wide=True)
    donor = await service.capture(**target, operation_id="capture-primitives")
    peer.files = floating_source()
    capture = await service.capture(**target, operation_id="capture-inline")
    options = ShadowReview(
        **target,
        operation_id="review-floating",
        capture_id=capture["id"],
        snapshot_sha256=capture["snapshot_evidence_sha256"],
        first_instance=300,
        prototype_capture_id=donor["id"],
        prototype_sha256=donor["snapshot_evidence_sha256"],
    )
    await service.bacnet.disconnect()
    before = list(peer.events)
    draft = await review(service, options)
    assert draft["compilation"]["valve_wiring"]["floating_valve"]["terminals"] == [2, 3]
    assert draft["can_apply"] is draft["controller_queries"] is False
    assert "token" not in draft and not service.plans
    with pytest.raises(ValueError, match="offline-only"):
        reconstruct(
            service,
            {
                "sequence_selection": draft["selection"],
                "sequence_observation_confirmed": True,
                "operation_profile": draft["operation_profile"],
            },
        )
    assert peer.events == before
