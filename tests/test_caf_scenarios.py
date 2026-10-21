"""Authored fixtures verify local stimuli, source guards and durable revisions."""

import copy
import hashlib
import json

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_scenarios import CafInputScenarios, CafScenarioStore
from bms_tool.caf_simulation import CafSimulationProfile
from bms_tool.storage import Conflict, Store

from tests.test_caf_simulation import make_caf, pack


def adapter():
    return CafInputScenarios(CafArchive(make_caf()))


def scenario():
    source = adapter()
    result = source.template()
    first, second = [row["id"] for row in source.inputs]
    result.update(
        name="Freeze, fault and recover",
        duration=2,
        dt=1,
        events=[
            {"time": 0, "values": {first: {"value": "-12.50", "quality": "good"}}},
            {"time": 0.25, "values": {second: {"value": "true", "quality": "open-circuit"}}},
            {
                "time": 1.5,
                "values": {
                    first: {"value": "0", "quality": "unreliable"},
                    second: {"value": "false", "quality": "good"},
                },
            },
            {"time": 2, "values": {first: {"value": "+1.25e1", "quality": "good"}}},
        ],
    )
    return result


def test_exact_input_contract_excludes_output_enum_and_unknown_blocks_and_keeps_units_raw():
    source = adapter()
    assert [row["class_id"] for row in source.inputs] == ["526", "530"]
    assert [row["initial_value"] for row in source.inputs] == ["70.000", "0"]
    assert all(
        row["unit_status"] == "unknown" and row["units_native"] is None for row in source.inputs
    )
    xml = CafArchive(make_caf()).xml.replace(
        b'<property id="2390">',
        b'<property id="117"><data><enum set="507">64</enum></data></property><property id="2390">',
        1,
    )
    unit = CafInputScenarios(CafArchive(pack(xml))).inputs[0]
    assert unit["unit_status"] == "raw-native-metadata"
    assert unit["units_native"] == {"type": "enum", "attributes": {"set": "507"}, "text": "64"}
    assert source.contract()["native_execution"] is False
    assert source.archive.original == make_caf()


def test_replay_exact_events_hold_lexical_values_and_quality_without_native_execution():
    source = adapter()
    first, second = [row["id"] for row in source.inputs]
    result = source.preview(scenario())
    frames = result["frames"]
    assert [row["time"] for row in frames] == [0, 0.25, 1, 1.5, 2]
    assert frames[0]["inputs"] == {
        first: {"value": "-12.50", "quality": "good"},
        second: {"value": "0", "quality": "good"},
    }
    assert frames[1]["inputs"][second] == {"value": "true", "quality": "open-circuit"}
    assert frames[2]["inputs"] == frames[1]["inputs"]
    assert frames[3]["inputs"][first] == {"value": "0", "quality": "unreliable"}
    assert frames[-1]["inputs"][first] == {"value": "+1.25e1", "quality": "good"}
    assert "outputs" not in result and "outputs" not in frames[0]
    assert "not executed" in result["scope"]
    assert source.archive.original == make_caf()


def test_default_initial_values_and_final_partial_frame_are_explicit():
    source = adapter()
    value = source.template() | {"duration": 1.25, "dt": 0.5}
    assert [row["time"] for row in source.preview(value)["frames"]] == [0, 0.5, 1, 1.25]
    assert all(
        sample["quality"] == "good"
        for sample in source.preview(value)["frames"][0]["inputs"].values()
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "0" * 64),
        ("profile_sha256", "0" * 64),
        ("version", True),
        ("format", "bms.caf-simulation-profile"),
    ],
)
def test_header_guards_reject_wrong_source_semantics_and_native_profile_format(field, value):
    data = scenario()
    data[field] = value
    with pytest.raises(ValueError, match="SHA-256|versioned fields"):
        adapter().validate(data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", "other"),
        ("native_type", "boolean"),
        ("class_id", "527"),
        ("initial_value", "71"),
        ("units_native", {"text": "degF"}),
        ("name", "Renamed"),
    ],
)
def test_exact_input_definitions_are_guarded_even_with_matching_hash(field, value):
    data = scenario()
    data["inputs"][0][field] = value
    with pytest.raises(ValueError, match="input guards"):
        adapter().validate(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(duration=True),
        lambda s: s.update(duration=float("nan")),
        lambda s: s.update(dt=float("inf")),
        lambda s: s.update(dt=0),
        lambda s: s.update(dt=1e-320),
        lambda s: s.update(duration=86401),
        lambda s: s.update(name=" "),
        lambda s: s.update(description="x" * 2001),
        lambda s: s.update(unexpected=True),
        lambda s: s.update(events={}),
        lambda s: s["events"].reverse(),
        lambda s: s["events"][1].update(time=0),
        lambda s: s["events"][1].update(time=-1),
        lambda s: s["events"][1].update(time=3),
        lambda s: s["events"][1].update(values={}),
        lambda s: s["events"][1].update(forces={}),
        lambda s: s["events"][1].update(
            values={"8-1/527_2::simulationProperty:3113": {"value": "3", "quality": "good"}}
        ),
    ],
)
def test_malformed_time_identity_and_resource_requests_fail_closed(mutate):
    data = scenario()
    mutate(data)
    with pytest.raises(ValueError):
        adapter().preview(data)


@pytest.mark.parametrize(
    "value,quality",
    [
        ("NaN", "good"),
        ("1e40", "good"),
        ("1e-50", "good"),
        (True, "good"),
        ("12", "normal"),
        ("12", {}),
        ("12", None),
    ],
)
def test_scalar_ranges_and_local_quality_are_checked(value, quality):
    data = scenario()
    first = data["inputs"][0]["id"]
    data["events"][0]["values"][first] = {"value": value, "quality": quality}
    with pytest.raises(ValueError):
        adapter().validate(data)


def test_boolean_input_does_not_accept_arbitrary_scalar_or_truthiness():
    data = scenario()
    second = data["inputs"][1]["id"]
    data["events"][1]["values"][second]["value"] = "2"
    with pytest.raises(ValueError, match="booleans"):
        adapter().validate(data)


def test_native_startup_export_uses_existing_editor_and_never_encodes_quality_or_trajectory():
    source = adapter()
    profile = source.startup_profile(scenario(), 2)
    content, changes = CafSimulationProfile(source.archive).apply(profile)
    assert len(changes) == 2
    values = [row["old"] for row in CafSimulationProfile(content).summary()["records"]]
    assert values == ["+1.25e1", "25.000", "false", "1", None]
    assert CafArchive(content).xml.count(b"<float>111.000</float>") == 5
    assert b"open-circuit" not in CafArchive(content).xml
    assert source.archive.original == make_caf()
    for time in (0.25, 1, 1.5):
        with pytest.raises(ValueError, match="quality encoding is unverified"):
            source.startup_profile(scenario(), time)
    with pytest.raises(ValueError, match="exact time"):
        source.startup_profile(scenario(), 0.2)


def test_empty_saved_inputs_do_not_invent_virtual_or_physical_channels():
    source = CafInputScenarios(
        CafArchive(pack(b'<objects xmlns="http://johnsoncontrols.com/MetasysIII/2002/3/Core"/>'))
    )
    assert source.contract()["inputs"] == []
    with pytest.raises(ValueError, match="no supported"):
        source.preview(source.template())


def test_persistence_restart_revalidation_optimistic_save_and_delete(tmp_path):
    source = adapter()
    store = Store(tmp_path)
    repository = CafScenarioStore(store)
    saved = repository.save(source, scenario())
    assert saved["revision"] == 1
    reopened = CafScenarioStore(Store(tmp_path)).load(source, saved["id"])
    assert reopened == saved
    assert repository.list(source)[0]["name"] == "Freeze, fault and recover"
    changed = scenario() | {"name": "Replacement"}
    updated = repository.save(source, changed, saved["id"], 1)
    assert updated["revision"] == 2 and updated["created"] == saved["created"]
    with pytest.raises(Conflict):
        repository.save(source, scenario(), saved["id"], 1)
    with pytest.raises(Conflict):
        repository.delete(source, saved["id"], 1)
    assert repository.load(source, saved["id"])["revision"] == 2
    # Same XML but different ZIP metadata is a different exact source.
    other = CafInputScenarios(
        CafArchive(make_caf().replace(b"preserve archive comment", b"modified archive comment"))
    )
    assert other.archive.xml == source.archive.xml
    assert other.profile_hash == source.profile_hash
    assert other.archive.hash != source.archive.hash
    with pytest.raises(ValueError, match="SHA-256"):
        repository.load(other, saved["id"])
    assert repository.list(other) == []
    repository.delete(source, saved["id"], 2)
    assert repository.list(source) == []
    assert source.archive.original == make_caf()


def test_stored_content_integrity_and_metadata_are_checked(tmp_path):
    store = Store(tmp_path)
    repository = CafScenarioStore(store)
    saved = repository.save(adapter(), scenario())
    with store.connect() as db:
        db.execute("UPDATE caf_local_scenarios SET content=? WHERE id=?", (b"{}", saved["id"]))
    with pytest.raises(ValueError, match="integrity"):
        repository.load(adapter(), saved["id"])
    with store.connect() as db:
        db.execute(
            "UPDATE caf_local_scenarios SET sha256=? WHERE id=?",
            (hashlib.sha256(b"{}").hexdigest(), saved["id"]),
        )
    with pytest.raises(ValueError, match="metadata"):
        repository.list(adapter())


def test_capacity_limits_are_atomic_and_replacement_subtracts_old_size(tmp_path, monkeypatch):
    import bms_tool.caf_scenarios as module

    repository = CafScenarioStore(Store(tmp_path))
    monkeypatch.setattr(module, "MAX_SCENARIOS", 1)
    saved = repository.save(adapter(), scenario())
    with pytest.raises(ValueError, match="capacity"):
        repository.save(adapter(), scenario())
    content_size = len(
        json.dumps(
            scenario(), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()
    )
    monkeypatch.setattr(module, "MAX_TOTAL_BYTES", content_size)
    assert repository.save(adapter(), copy.deepcopy(scenario()), saved["id"], 1)["revision"] == 2
    with pytest.raises(ValueError, match="capacity"):
        repository.save(adapter(), scenario() | {"description": "more bytes"}, saved["id"], 2)
    assert repository.load(adapter(), saved["id"])["revision"] == 2


def test_scenario_and_preview_bounds_reject_before_allocating_large_frames(monkeypatch):
    import bms_tool.caf_scenarios as module

    data = scenario()
    monkeypatch.setattr(module, "MAX_EVENTS", 3)
    with pytest.raises(ValueError, match="event rows"):
        adapter().validate(data)
    monkeypatch.setattr(module, "MAX_EVENTS", 2000)
    monkeypatch.setattr(module, "MAX_PREVIEW_BYTES", 100)
    with pytest.raises(ValueError, match="bounded preview"):
        adapter().preview(data)
    monkeypatch.setattr(module, "MAX_PREVIEW_BYTES", 4 * 1024 * 1024)
    monkeypatch.setattr(module, "MAX_BYTES", 100)
    with pytest.raises(ValueError, match="2 MiB"):
        adapter().validate(data)


def test_decimal_intervals_and_events_share_one_exact_frame_boundary():
    source = adapter()
    data = source.template() | {
        "duration": 0.5,
        "dt": 0.1,
        "events": [
            {"time": 0.3, "values": {source.inputs[0]["id"]: {"value": "-1", "quality": "good"}}}
        ],
    }
    frames = source.preview(data)["frames"]
    assert [row["time"] for row in frames] == [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    assert frames[3]["inputs"][source.inputs[0]["id"]]["value"] == "-1"


def test_largest_supported_input_contract_has_a_usable_bounded_new_scenario():
    xml = (
        '<objects xmlns="http://johnsoncontrols.com/MetasysIII/2002/3/Core">'
        + "".join(
            f'<object ref="8-1/526_{i}" classid="526" classVersion="1.0"><simulationProperty id="3113"><data><float>0</float></data></simulationProperty></object>'
            for i in range(256)
        )
        + "</objects>"
    )
    source = CafInputScenarios(CafArchive(pack(xml.encode())))
    template = source.template()
    assert template["dt"] > 1
    preview = source.preview(template)
    assert len(preview["frames"][0]["inputs"]) == 256
    assert preview["frames"][-1]["time"] == 60
    assert len(json.dumps(preview).encode()) < 4 * 1024 * 1024
    xml = xml.replace(
        "</objects>",
        '<object ref="8-1/526_extra" classid="526" classVersion="1.0"><simulationProperty id="3113"><data><float>0</float></data></simulationProperty></object></objects>',
    )
    with pytest.raises(ValueError, match="256 inputs"):
        CafInputScenarios(CafArchive(pack(xml.encode())))
