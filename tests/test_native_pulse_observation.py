"""Decode the observation drawing and exercise its reviewed transfer on a UDP peer."""

import pytest
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_inline_monitor import compile_monitor
from bms_tool.native_inline_monitor_transfer import (
    ClockMonitorReview,
    MonitorApply,
    review,
    validate_review,
)
from pydantic import ValidationError

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_monitor import ROOT, observation_peer
from .test_native_inline_register import station


@pytest.mark.parametrize("model", ["FX-PCV1630-0", "MS-VMA1630-0"])
@pytest.mark.parametrize("activity", [False, True])
def test_two_rising_edges_reach_only_internal_timer_outputs(model, activity):
    files = station(model)
    options = dict(sample_register=True, activity_input=activity, register_source="supply-airflow")
    prior, existing = compile_monitor(files, 2020, **options)
    assert (prior, existing) == compile_monitor(files, 2020, pulse_witness=False, **options)
    candidate, report = compile_monitor(files, 2020, pulse_witness=True, **options)
    app = MoiIdentity(candidate)
    graph = app.reader.diagram(ROOT, retained_activity_refs=True)
    original = MoiIdentity(prior).reader.diagram(ROOT, retained_activity_refs=True)
    read = app.reader.scalar
    assert graph["connections"][:-7] == original["connections"]

    # File offsets follow the growing root drawing. Compare each block's identity,
    # execution position and original record bytes independently of its new offset.
    def block_ids(blocks):
        return [(b["index"], b["ref"], b["object"], b["sha256"]) for b in blocks]

    assert block_ids(graph["blocks"][:-6]) == block_ids(original["blocks"])
    assert report["new_records"] == existing["new_records"] + 28
    assert report["new_blocks"] == existing["new_blocks"] + 6
    assert report["points"] == existing["points"]
    old_register = existing["sampling_register"]
    pulse = report["sampling_register"]["retriggerable_timer"]
    assert report["sampling_register"] == {**old_register, "retriggerable_timer": pulse}
    refs = [b["ref"] for b in graph["blocks"][-6:]]

    def ports(ref):
        return {
            read(value, 3365): value
            for name, value in app.reader.records.items()
            if name.rpartition(".")[0] == ref
        }

    for ref, trigger in zip(refs[:2], [48, 46], strict=True):
        parent = app.reader.records[ref]
        assert (parent["class_id"], read(parent, 3670), read(parent, 518)) == (560, 30, 5)
        assert (read(ports(ref)[50084], 3113), read(ports(ref)[637], 3113)) == (trigger, 0)
    either, timer, active, remaining = refs[2:]
    assert (read(app.reader.records[either], 3670), read(app.reader.records[either], 518)) == (
        25,
        2,
    )
    assert read(app.reader.records[timer], 1184) == pulse["update_seconds"] == 1
    assert read(ports(timer)[518], 3113) == 1
    assert read(ports(timer)[1080], 3113) == pulse["duration_seconds"] == 5
    assert pulse["trigger_countdowns"] == [48, 46]
    assert read(ports(active)[85], 75) == pulse["active"]
    assert read(ports(remaining)[85], 75) == pulse["remaining"]
    assert [read(app.reader.records[ref], 3670) for ref in [active, remaining]] == [81, 79]
    wires = [
        (v["source_ref"], v["source_port"], v["target_ref"], v["target_port"])
        for v in graph["connections"][-7:]
    ]
    clock, clock_port = wires[0][:2]
    if activity:
        assert clock == existing["register_input_activity"]["reference"] and clock_port == 8000
    else:
        assert read(app.reader.records[clock], 3670) == 62 and clock_port == 1081
    assert wires == [
        (clock, clock_port, refs[0], 50083),
        (clock, clock_port, refs[1], 50083),
        (refs[0], 85, either, 7000),
        (refs[1], 85, either, 7001),
        (either, 85, timer, 513),
        (timer, 85, active, 513),
        (timer, 1081, remaining, 513),
    ]


def test_observation_requires_a_boolean_and_enabled_register():
    files = station()
    for value in [True, 1, "yes"]:
        with pytest.raises(ValueError, match="requires an enabled sample register"):
            compile_monitor(files, 2020, pulse_witness=value)
    with pytest.raises(ValidationError):
        ClockMonitorReview(
            pulse_witness="yes",
            device="device,123",
            first_instance=2020,
            operation_id="strict-option",
            capture_id="a" * 32,
            snapshot_sha256="b" * 64,
        )


async def test_udp_review_reconstructs_observations_and_restores_the_original(native_link):
    peer, _, _, service, target = native_link
    observation_peer(peer, "", first_instance=2020, allocated_count=67)
    original = station()
    peer.files = original.copy()
    baseline, _ = ParameterApplication(original[3], original[11], original[12]).compile()
    cap = await service.capture(**target, operation_id="capture-timing-original")
    opts = ClockMonitorReview(
        **target,
        operation_id="review-pulse-drawing",
        first_instance=2020,
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        sample_register=True,
        pulse_witness=True,
    )
    plan = await review(service, opts)
    assert len(set(peer.clearance_reads)) == plan["live_review"]["confirmed_absent"] == 67
    assert "retriggerable" in plan["scope"]
    body = {key: val for key, val in plan.items() if key not in {"token", "review_sha256"}}
    with pytest.raises(ValueError, match="exact monitor review"):
        validate_review(
            {
                "body": body,
                "digest": seal(body),
                "options": opts.model_copy(update={"pulse_witness": False}),
            }
        )
    req = MonitorApply(
        operation_id="install-pulse-drawing",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        monitor_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(req, default_edit=False, inline_kind="inline-monitor")
    assert receipt["result"]["status"] == "verified", receipt["result"]
    assert receipt["result"]["preservation"]["native_graph_verified"]
    assert receipt["result"]["preservation"]["runtime_sampling_verified"] is False
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_reviewed(req, default_edit=False, inline_kind="inline-monitor")
    restoration = await service.preview_snapshot_restore(
        **target,
        operation_id="review-timing-original",
        restore_capture_id=cap["id"],
        restore_snapshot_sha256=cap["snapshot_evidence_sha256"],
    )
    restored = await service.apply_snapshot_restore(
        operation_id="restore-timing-original",
        token=restoration["token"],
        review_sha256=restoration["review_sha256"],
        historical_application_confirmed=True,
        application_transfer_confirmed=True,
    )
    assert restored["result"]["status"] == "verified", restored["result"]
    assert MoiIdentity(peer.files[3]).data == MoiIdentity(baseline).data
