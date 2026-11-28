"""Verify the optional diagnostic against independent authored records and UDP traffic."""

import pytest
from bacpypes3.primitivedata import Unsigned
from bms_tool.moi_application import _list
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.native_inline_monitor import compile_monitor
from bms_tool.native_inline_monitor_transfer import (
    ClockMonitorReview,
    MonitorApply,
    review,
    validate_review,
)
from bms_tool.native_inputs import archive
from pydantic import ValidationError

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_inline_monitor import ROOT, fixture, observation_peer
from .test_native_inline_sequence import authored_source


def station(model="FX-PCV1630-0"):
    files = fixture(model=model)
    app = MoiIdentity(files[3])
    library = MoiIdentity(authored_source(catalog=True, model=model)[3])
    original = [app.data[r["offset"] : r["end_offset"]] for r in app.records]
    prototypes = [
        library.data[r["offset"] : r["end_offset"]]
        for r in library.records
        if str(library.reader.scalar(r, 32527)).startswith("controller/library_")
    ]
    return {**files, 3: archive(app, original + prototypes)}


@pytest.mark.parametrize("model", ["FX-PCV1630-0", "MS-VMA1630-0"])
def test_register_tracks_countdown_and_feedback_without_a_connection_to_control(model):
    files = station(model)
    default = compile_monitor(files, 2020)
    assert default == compile_monitor(files, 2020, sample_register=False)
    assert "sampling_register" not in default[1]
    output, result = compile_monitor(files, 2020, sample_register=True)
    assert result["new_records"] == len(set(result["added_objects"])) == 39
    assert result["new_blocks"] == 10
    assert result["observations"] == default[1]["observations"]
    app = MoiIdentity(output)
    graph = app.reader.diagram(ROOT, retained_activity_refs=True)
    before = MoiIdentity(default[0]).reader.diagram(ROOT, retained_activity_refs=True)
    assert graph["execution_order"] == before["execution_order"] + [10, 11, 12]
    assert graph["connections"][:-5] == before["connections"]
    refs = {b["ref"]: i for i, b in enumerate(graph["blocks"])}
    rows = graph["connections"][-5:]
    assert [
        (refs[r["source_ref"]], r["source_port"], refs[r["target_ref"]], r["target_port"])
        for r in rows
    ] == [
        (8, 1081, 10, 50083),
        (10, 85, 12, 961),
        (11, 85, 12, 7000),
        (8, 1081, 12, 7001),
        (12, 85, 11, 513),
    ]
    rd = app.reader
    compare, previous, switch = [rd.records[x["ref"]] for x in graph["blocks"][-3:]]
    assert (rd.scalar(compare, 3670), rd.scalar(compare, 518)) == (32, 3)
    assert (rd.scalar(previous, 3670), rd.scalar(switch, 3670)) == (79, 14)
    assert list(_list(switch["properties"][2381]["tags"], Unsigned)) == [0, 2]
    assert rd.scalar(switch, 3122) == 1
    for item, label in [(compare, "gate"), (previous, "memory"), (switch, "output")]:
        ports = {
            rd.scalar(r, 3365): r
            for ref, r in rd.records.items()
            if ref.rpartition(".")[0] == rd.scalar(item, 32527)
        }
        assert rd.scalar(ports[85], 75) == result["sampling_register"][label]
        if label == "gate":
            assert rd.scalar(ports[50084], 3113) == 30.0
    assert len(set(result["added_objects"]) & set(default[1]["added_objects"])) == 26


def test_register_refuses_missing_primitive_library_and_non_boolean_switch():
    files = fixture()
    with pytest.raises(ValueError, match="released typed source"):
        compile_monitor(files, 2020, sample_register=True)
    with pytest.raises(ValueError, match="Boolean"):
        compile_monitor(files, 2020, sample_register="on")


async def test_register_is_bound_to_repeated_preflight_apply_and_independent_readback(native_link):
    peer, _, _, service, target = native_link
    observation_peer(peer, "", first_instance=2020, allocated_count=39)
    peer.files = station()
    cap = await service.capture(**target, operation_id="capture-register-source")
    kwargs = dict(
        **target,
        operation_id="review-register",
        first_instance=2020,
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
    )
    with pytest.raises(ValidationError):
        ClockMonitorReview(**kwargs, sample_register="yes")
    with pytest.raises(ValueError, match="first instance of 90 or higher"):
        await review(
            service, ClockMonitorReview(**{**kwargs, "first_instance": 43}, sample_register=True)
        )
    plan = await review(service, ClockMonitorReview(**kwargs, sample_register=True))
    body = {k: v for k, v in plan.items() if k not in ("token", "review_sha256")}
    with pytest.raises(ValueError, match="exact monitor review"):
        validate_review(
            {"body": body, "digest": seal(body), "options": ClockMonitorReview(**kwargs)}
        )
    assert plan["live_review"]["confirmed_absent"] == len(set(peer.clearance_reads)) == 39
    assert "gated timing register" in plan["scope"]
    apply = MonitorApply(
        operation_id="apply-register",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        monitor_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(apply, default_edit=False, inline_kind="inline-monitor")
    result = receipt["result"]
    assert result["status"] == "verified", result
    assert result["preservation"]["native_graph_verified"]
    assert result["diagnostic_execution"]["status"] == "advancing"
    assert not result["preservation"]["runtime_sampling_verified"]
    stored = MoiIdentity(peer.files[3])
    assert any(
        stored.reader.scalar(r, 75) == plan["compilation"]["sampling_register"]["output"]
        for r in stored.records
    )


@pytest.mark.parametrize("model", ["FX-PCV1630-0", "MS-VMA1630-0"])
def test_register_can_route_its_clock_through_a_typed_native_activity(model):
    from bacpypes3.primitivedata import Enumerated
    from bms_tool.native_inline_register import verify_clock_activity
    from bms_tool.native_inputs import encoded, replace_properties

    files = station(model)
    ordinary, before = compile_monitor(files, 2020, sample_register=True)
    assert compile_monitor(files, 2020, sample_register=True, activity_input=False) == (
        ordinary,
        before,
    )
    output, info = compile_monitor(files, 2020, sample_register=True, activity_input=True)
    assert info["new_records"] == 42 and info["new_blocks"] == 11
    assert info["points"] == before["points"] and info["observations"] == before["observations"]
    assert info["clock_witness"] == before["clock_witness"]
    app = MoiIdentity(output)
    nested = info["register_input_activity"]
    root = app.reader.diagram(ROOT, retained_activity_refs=True)
    activity = root["blocks"][-4]
    assert activity["object"] == nested["object"]
    graph = app.reader.diagram(activity["ref"], retained_activity_refs=True)
    assert [b["object"] for b in graph["blocks"]] == [nested["input"], nested["output"]]
    source, sink = graph["blocks"]
    assert graph["connections"] == [
        dict(
            index=0,
            source_ref=source["ref"],
            source_port=663,
            target_ref=sink["ref"],
            target_port=513,
        )
    ]
    parent = app.reader.records[activity["ref"]]
    inp, out = (app.reader.records[b["ref"]] for b in graph["blocks"])
    assert [
        (x["class_id"], app.reader.scalar(x, 3365), app.reader.scalar(x, 3670)) for x in (inp, out)
    ] == [(526, 7000, 230), (527, 8000, 233)]
    assert set(
        x["target_ref"] for x in root["connections"] if x["source_ref"] == activity["ref"]
    ) == {root["blocks"][-3]["ref"], root["blocks"][-1]["ref"]}
    assert [
        (x["source_ref"], x["source_port"], x["target_port"])
        for x in root["connections"]
        if x["target_ref"] == activity["ref"]
    ] == [(root["blocks"][-6]["ref"], 1081, 7000)]
    assert parent["class_id"] == 536
    changed = [
        replace_properties(app, r, {3365: encoded(Enumerated(8010))})
        if r["offset"] == out["offset"]
        else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    with pytest.raises(ValueError, match="activity pin"):
        verify_clock_activity(MoiIdentity(archive(app, changed)), nested)
    with pytest.raises(ValueError, match="requires an enabled"):
        compile_monitor(files, 2020, activity_input=True)


@pytest.mark.parametrize("register_source", ["countdown", "supply-airflow"])
async def test_activity_register_receipt_preserves_and_reconstructs_its_exact_graph(
    native_link, register_source
):
    peer, _, _, service, target = native_link
    observation_peer(peer, "", first_instance=2020, allocated_count=42)
    peer.files = station()
    cap = await service.capture(**target, operation_id="capture-activity-source")
    kwargs = dict(
        **target,
        operation_id="review-activity",
        first_instance=2020,
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        sample_register=True,
    )
    request = ClockMonitorReview(**kwargs, activity_input=True, register_source=register_source)
    plan = await review(service, request)
    assert len(set(peer.clearance_reads)) == plan["live_review"]["confirmed_absent"] == 42
    assert "Float activity input" in plan["scope"]
    body = {key: value for key, value in plan.items() if key not in ("token", "review_sha256")}
    alternate = "countdown" if register_source == "supply-airflow" else "supply-airflow"
    with pytest.raises(ValueError, match="exact monitor review"):
        validate_review(
            {
                "body": body,
                "digest": seal(body),
                "options": ClockMonitorReview(
                    **kwargs, activity_input=True, register_source=alternate
                ),
            }
        )
    with pytest.raises(ValueError, match="exact monitor review"):
        validate_review(
            {"body": body, "digest": seal(body), "options": ClockMonitorReview(**kwargs)}
        )
    apply = MonitorApply(
        operation_id="install-activity",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        monitor_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(apply, default_edit=False, inline_kind="inline-monitor")
    assert receipt["result"]["status"] == "verified"
    assert receipt["result"]["preservation"]["native_graph_verified"]
    assert receipt["result"]["preservation"]["runtime_sampling_verified"] is False
    assert receipt["result"]["diagnostic_execution"]["status"] == "advancing"
    from bms_tool.native_inline_register import verify_clock_activity

    verify_clock_activity(
        MoiIdentity(peer.files[3]), plan["compilation"]["register_input_activity"]
    )


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0"])
@pytest.mark.parametrize("activity", [False, True])
def test_airflow_register_changes_only_the_diagnostic_data_wire(model, activity):
    files = station(model)
    options = dict(sample_register=True, activity_input=activity)
    normal, timing = compile_monitor(files, 2020, **options)
    assert (normal, timing) == compile_monitor(files, 2020, register_source="countdown", **options)
    payload, result = compile_monitor(files, 2020, register_source="supply-airflow", **options)
    assert result["added_objects"] == timing["added_objects"]
    source = result["sampling_register"]["airflow_source"]
    assert source["object"] == result["points"]["flow"]
    assert (source["units"], source["port"]) == (84, 3505)
    app = MoiIdentity(payload)
    assert app.reader.scalar(app.reader.records[source["reference"]], 75) == source["object"]
    assert source["reference"].rpartition(".")[0] == source["parent"]
    original = MoiIdentity(normal).reader.diagram(ROOT, retained_activity_refs=True)
    graph = app.reader.diagram(ROOT, retained_activity_refs=True)
    assert graph["execution_order"] == original["execution_order"]
    switch = graph["blocks"][-1]
    assert switch["name"] == "Gated airflow sample"
    (selected,) = [
        r
        for r in graph["connections"]
        if r["target_ref"] == switch["ref"] and r["target_port"] == 7001
    ]
    assert (selected["source_ref"], selected["source_port"]) == (source["parent"], 3505)
    assert graph["connections"] == [
        {**wire, "source_ref": source["parent"], "source_port": source["port"]}
        if wire["target_ref"] == switch["ref"] and wire["target_port"] == 7001
        else wire
        for wire in original["connections"]
    ]
    with pytest.raises(ValueError, match="enabled sample register"):
        compile_monitor(files, 2020, register_source="supply-airflow")
    with pytest.raises(ValueError, match="verified supply airflow"):
        compile_monitor(files, 2020, sample_register=True, register_source="arbitrary-point")
