"""Authored read-only observation, quality and screening behavior."""

import json
import math
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from bms_tool.airflow_observer import (
    load_config,
    matched_demand,
    metrics,
    observed_seconds,
    point_value,
    read_group,
    read_records,
    recover_tail,
    render_report,
    reversals,
    run,
    startup_ready,
)


def field(value):
    return {"status": "ok", "value": value}


def point(value=50, name="Observed", flags=None):
    return {
        "object": "analog-value,41",
        "identity_verified": True,
        "properties": {
            "object-name": field(name),
            "present-value": field(value),
            "reliability": field({"value": 0}),
            "status-flags": field(flags or [0, 0, 0, 0]),
            "out-of-service": field(False),
        },
    }


@pytest.mark.parametrize("change", ["name", "identity", "reliability", "service", "timeout", "nan"])
def test_unqualified_values_cannot_be_used_for_tuning(change):
    p = point()
    if change == "name":
        p["properties"]["object-name"] = field("Other")
    elif change == "identity":
        p["identity_verified"] = False
    elif change == "reliability":
        p["properties"]["reliability"] = field(7)
    elif change == "service":
        p["properties"]["out-of-service"] = field(True)
    elif change == "timeout":
        p["properties"]["present-value"] = {"status": "timeout"}
    else:
        p["properties"]["present-value"] = field(math.nan)
    assert not point_value(p, "Observed")["quality_ok"]


def test_software_override_flags_are_retained_and_damper_overrides_excluded_from_screen():
    value = point_value(point(flags=[0, 0, 1, 0]), "Observed")
    assert value["quality_ok"] and value["override_flag"]
    data = records(oscillating=True)
    for record in data:
        record["points"]["Box.damper"]["override_flag"] = True
    assert not metrics(data, "Box")["possible_hunting"]


def test_startup_requires_real_fan_proof_and_qualified_pressure():
    cfg = {"startup_fans": ["A", "B"], "startup_pressure": "P", "startup_min_static": 0.05}
    p = {
        "A": {"value": 0, "quality_ok": True},
        "B": {"value": 1, "quality_ok": True},
        "P": {"value": 0.5, "quality_ok": True},
    }
    assert startup_ready(p, cfg)
    p["P"]["quality_ok"] = False
    assert not startup_ready(p, cfg)
    p["P"].update(quality_ok=True, value=0)
    assert not startup_ready(p, cfg)


def records(*, oscillating=False, moving_setpoint=False):
    start = datetime(2030, 1, 4, tzinfo=UTC)
    out = []
    for i in range(121):
        wave = math.sin(i * math.pi / 8)
        value = 60 + (25 * wave if oscillating else 0.2 * wave)
        out.append(
            {
                "utc": (start + timedelta(seconds=30 * i)).isoformat(),
                "group": "authored",
                "source": "authored peer",
                "airflow_available": True,
                "points": {
                    "Box.damper": {
                        "value": 40 + (20 * wave if oscillating else 0.1 * wave),
                        "quality_ok": True,
                    },
                    "Box.flow": {"value": value, "quality_ok": True},
                    "Box.flow_sp": {
                        "value": 60 + (i if moving_setpoint else 0),
                        "quality_ok": True,
                    },
                },
            }
        )
    return out


def test_hunting_screen_requires_large_reversals_and_error_crossings_at_stable_request():
    assert metrics(records(oscillating=True), "Box")["possible_hunting"]
    assert not metrics(records(), "Box")["possible_hunting"]
    assert not metrics(records(oscillating=True, moving_setpoint=True), "Box")["possible_hunting"]
    assert reversals([40, 41, 39, 40]) == 0
    data = records(oscillating=True)
    for r in data:
        r["airflow_available"] = False
    assert not metrics(data, "Box")["possible_hunting"]


def test_request_band_comparison_requires_healthy_automatic_damper_samples():
    data = records()
    bins = matched_demand(data, ["Box"], None)["Box"]
    assert bins[60]["samples"] == 121
    for record in data:
        record["points"]["Box.damper"]["override_flag"] = True
    assert not matched_demand(data, ["Box"], None)["Box"]


def test_observation_never_counts_missing_time_or_air_handler_off_as_good_coverage():
    data = records()
    assert observed_seconds(data, "Box.damper", None, require_air=True) == 3600
    assert observed_seconds(data[:2] + data[10:], "Box.damper", None, require_air=True) == 3330
    for r in data:
        r["airflow_available"] = False
    assert observed_seconds(data, "Box.damper", None, require_air=True) == 0
    data = records()
    data[1]["points"]["Box.flow"]["quality_ok"] = False
    assert observed_seconds(data[:3], "Box.damper", None, required_aliases=["Box.flow"]) == 0


async def test_reader_uses_only_existing_properties_api_and_does_not_follow_renamed_points():
    class Reader:
        async def properties(self, **request):
            if request["object_ids"] == ["device,400"]:
                return {
                    "identity_verified": True,
                    "objects": [{"properties": {"object-name": field("Peer")}}],
                }
            return {"identity_verified": True, "objects": [point(name="Changed")], "errors": []}

    group = {
        "name": "owned",
        "target": {"address": "127.0.0.1:47999", "device": "device,400"},
        "source": "authored peer",
        "expected_device_name": "Peer",
        "points": [
            {"alias": "Box.damper", "object": "analog-value,41", "expected_name": "Observed"}
        ],
    }
    result = await read_group(Reader(), group)
    assert result["points"]["Box.damper"]["value"] is None
    assert not result["points"]["Box.damper"]["quality_ok"]


async def test_compact_object_ids_match_canonical_reader_identifiers():
    class Reader:
        async def properties(self, **request):
            if request["object_ids"] == ["device,400"]:
                return {
                    "identity_verified": True,
                    "objects": [{"properties": {"object-name": field("Peer")}}],
                }
            return {"identity_verified": True, "objects": [point()]}

    group = {
        "name": "owned",
        "source": "authored",
        "target": {"address": "127.0.0.1:47999", "device": "device,400"},
        "expected_device_name": "Peer",
        "points": [{"alias": "Box.damper", "object": "2,41", "expected_name": "Observed"}],
    }
    result = await read_group(Reader(), group)
    assert result["points"]["Box.damper"]["value"] == 50
    assert result["points"]["Box.damper"]["quality_ok"]


def test_interrupted_append_is_preserved_and_not_treated_as_a_measurement(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text('{"value": 1}\n{"val')
    assert read_records(path) == [{"value": 1}]
    fragment = recover_tail(path)
    assert path.read_text() == '{"value": 1}\n'
    assert fragment and (tmp_path / fragment).read_text() == '{"val'
    with path.open("a") as stream:
        stream.write('{"value": 2}\n')
    assert len(read_records(path)) == 2


def config(tmp_path):
    aliases = ["Box.damper", "Box.flow", "Box.flow_sp", "AHU.fan", "AHU.static"]
    return {
        "timezone": "UTC",
        "collection_from": "2030-01-01T06:00:00+00:00",
        "startup_deadline": "2030-01-01T10:00:00+00:00",
        "hard_stop": "2030-01-01T18:00:00+00:00",
        "minimum_monitor_seconds": 600,
        "checkpoint_seconds": 600,
        "startup_confirmations": 2,
        "startup_min_static": 0.05,
        "startup_fans": ["AHU.fan"],
        "startup_pressure": "AHU.static",
        "target_name": "Box",
        "reference_names": [],
        "limits": ["Authored test"],
        "output_directory": str(tmp_path / "report"),
        "groups": [
            {
                "name": "authored",
                "interval_seconds": 30,
                "source": "authored",
                "target": {"address": "127.0.0.1:47999", "device": "device,400"},
                "expected_device_name": "Peer",
                "points": [
                    {"alias": alias, "object": f"analog-value,{i}", "expected_name": alias}
                    for i, alias in enumerate(aliases)
                ],
            }
        ],
    }


def test_configuration_rejects_unbounded_duration_and_ambiguous_group_names(tmp_path):
    path = tmp_path / "config.json"
    cfg = config(tmp_path)
    path.write_text(json.dumps(cfg))
    assert load_config(path)["target_name"] == "Box"
    cfg["minimum_monitor_seconds"] = 0
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="bounded"):
        load_config(path)
    cfg = config(tmp_path)
    cfg["groups"].append(cfg["groups"][0])
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="distinct"):
        load_config(path)


@pytest.mark.skipif(os.name != "posix", reason="The optional observer uses POSIX process locking.")
async def test_expired_window_never_opens_a_field_connection(tmp_path, monkeypatch):
    import bms_tool.airflow_observer as module

    cfg = config(tmp_path)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(module, "utc", lambda: datetime(2030, 1, 2, tzinfo=UTC))

    def forbidden(*args):
        raise AssertionError("An expired job must not construct BACnet.")

    monkeypatch.setattr(module, "Bacnet", forbidden)
    await run(path, tmp_path / "state")
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["status"] == "incomplete" and "window ended" in state["reason"]


@pytest.mark.skipif(os.name != "posix", reason="The optional observer uses POSIX process locking.")
async def test_scheduled_observer_completes_only_after_startup_and_actual_coverage(
    tmp_path, monkeypatch
):
    import bms_tool.airflow_observer as module

    now = datetime(2030, 1, 1, 6, tzinfo=UTC)
    ticks = 0
    calls = []

    async def advance(seconds):
        nonlocal ticks
        ticks += seconds

    class Network:
        def __init__(self, store):
            self.store = store

        async def connect(self, **options):
            calls.append("connect")

        async def disconnect(self):
            calls.append("disconnect")

    async def sample(reader, group):
        values = {
            "Box.damper": 40,
            "Box.flow": 60,
            "Box.flow_sp": 60,
            "AHU.fan": 1,
            "AHU.static": 0.5,
        }
        return {
            "utc": (now + timedelta(seconds=ticks)).isoformat(),
            "group": group["name"],
            "source": "authored",
            "errors": [],
            "points": {key: {"value": value, "quality_ok": True} for key, value in values.items()},
        }

    cfg = config(tmp_path)
    cfg["interface"] = {}
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg))
    monkeypatch.setattr(module, "utc", lambda: now + timedelta(seconds=ticks))
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: ticks))
    monkeypatch.setattr(module.asyncio, "sleep", advance)
    monkeypatch.setattr(module, "Bacnet", Network)
    monkeypatch.setattr(module, "ControllerWorkspace", lambda *args: None)
    monkeypatch.setattr(module, "read_group", sample)
    await run(path, tmp_path / "state")
    state = json.loads((tmp_path / "state" / "state.json").read_text())
    assert state["status"] == "complete"
    assert state["observed_target_seconds"] >= 600 and ticks >= 600
    assert calls == ["connect", "disconnect"]
    checks = read_records(tmp_path / "report" / "checkins.jsonl")
    assert len(checks) >= 2
    await run(path, tmp_path / "state")
    assert calls == ["connect", "disconnect"]


def test_report_keeps_incomplete_observation_and_raw_values_explicit(tmp_path):
    cfg = {
        "target_name": "Box",
        "reference_names": [],
        "timezone": "UTC",
        "limits": ["Authored test; no physical acceptance."],
    }
    state = {"status": "incomplete", "observed_target_seconds": 30}
    render_report(cfg, state, records()[:2], tmp_path)
    text = (tmp_path / "report.html").read_text()
    assert "incomplete" in text and "not PID-tuning instructions" in text
    assert (tmp_path / "samples.csv").read_text().count("Box.damper") == 2
