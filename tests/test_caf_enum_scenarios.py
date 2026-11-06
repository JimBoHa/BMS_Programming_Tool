"""Opt-in numeric input stimuli, version isolation and exact startup-copy checks."""

import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.caf import CafArchive
from bms_tool.caf_scenarios import CafInputScenarios, CafScenarioStore
from bms_tool.caf_simulation import CafSimulationProfile
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_caf_enum_simulation import source


def enum_scenario(**options):
    adapter = CafInputScenarios(CafArchive(source(**options)), version=2)
    scenario = adapter.template()
    identity = next(row["id"] for row in adapter.inputs if row["native_type"] == "enum")
    scenario.update(
        duration=2,
        dt=1,
        events=[{"time": 1, "values": {identity: {"value": "2", "quality": "good"}}}],
    )
    return adapter, scenario, identity


def test_default_version1_contract_template_preview_and_startup_remain_exact():
    # Public authored golden witness captured from the prior version-1 adapter.
    # The independent prior-source comparison is retained in local qualification.
    after = CafInputScenarios(CafArchive(source()))
    scenario = after.template()
    scenario.update(duration=1, dt=1)
    snapshot = {
        "contract": after.contract(),
        "template": after.template(),
        "preview": after.preview(scenario),
        "startup": after.startup_profile(scenario, 0),
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
    assert (
        hashlib.sha256(encoded).hexdigest()
        == "ce6026553eb09404c1b2bc22caac386732485950b14fd6287785b2d84b828722"
    )


@pytest.mark.parametrize("cdata", [False, True])
@pytest.mark.parametrize("value", ["0", "65536", "4294967295"])
def test_enum_hold_and_startup_mutate_only_the_selected_saved_input_leaf(cdata, value):
    adapter, scenario, identity = enum_scenario(cdata=cdata)
    scenario["events"][0]["values"][identity]["value"] = value
    assert [r["class_id"] for r in adapter.inputs] == ["526", "530", "528"]
    row = adapter.inputs[-1]
    assert row["enum_representation"] == {
        "attributes": {"set": "113"},
        "maximum_code": 4294967295,
        "enum_semantics_verified": False,
    }
    trace = adapter.preview(scenario)
    assert [r["inputs"][identity]["value"] for r in trace["frames"]] == ["1", value, value]
    profile = adapter.startup_profile(scenario, 1)
    assert profile["version"] == 2
    output, changes = CafSimulationProfile(adapter.archive, profile_version=2).apply(profile)
    expected = adapter.archive.xml.replace(
        b"<![CDATA[1]]>" if cdata else b'<enum set="113">1</enum>',
        f"<![CDATA[{value}]]>".encode() if cdata else f'<enum set="113">{value}</enum>'.encode(),
        1,
    )
    assert CafArchive(output).xml == expected
    assert len(changes) == 1 and changes[0]["ref"] == "8-1/528_4"
    assert adapter.archive.original == source(cdata=cdata)


@pytest.mark.parametrize("value", ["01", "+1", "-1", "1.0", " 1", "4294967296", "NaN", 1, False])
def test_enum_samples_require_canonical_uint32_text(value):
    adapter, scenario, identity = enum_scenario()
    scenario["events"][0]["values"][identity]["value"] = value
    with pytest.raises(ValueError):
        adapter.validate(scenario)


@pytest.mark.parametrize(
    "options",
    [
        {"cid": 529},
        {"version": "2.0"},
        {"attributes": 'set="113" opaque="unknown"'},
        {"code": "01"},
    ],
)
def test_output_or_unqualified_enum_records_cannot_become_inputs(options):
    adapter = CafInputScenarios(CafArchive(source(**options)), version=2)
    assert [r["class_id"] for r in adapter.inputs] == ["526", "530"]


def test_missing_set_stays_missing_and_quality_cannot_be_encoded_as_native_startup():
    adapter, scenario, identity = enum_scenario(attributes="")
    assert adapter.inputs[-1]["enum_representation"]["attributes"] == {}
    scenario["events"][0]["values"][identity]["quality"] = "open-circuit"
    assert adapter.preview(scenario)["frames"][1]["inputs"][identity]["quality"] == "open-circuit"
    with pytest.raises(ValueError, match="all-good"):
        adapter.startup_profile(scenario, 1)


def test_store_versions_reopen_separately_and_cannot_overwrite_each_other(tmp_path):
    modern, scenario, _ = enum_scenario()
    legacy = CafInputScenarios(modern.archive)
    store = CafScenarioStore(Store(tmp_path))
    old = store.save(legacy, legacy.template())
    new = store.save(modern, scenario)
    assert [r["id"] for r in store.list(legacy)] == [old["id"]]
    assert [r["id"] for r in store.list(modern)] == [new["id"]]
    with pytest.raises(ValueError):
        store.save(modern, scenario, old["id"], old["revision"])
    with pytest.raises(ValueError):
        store.load(legacy, new["id"])
    with pytest.raises(ValueError):
        store.delete(legacy, new["id"], new["revision"])
    restarted = CafScenarioStore(Store(tmp_path))
    assert restarted.load(legacy, old["id"]) == old
    assert restarted.load(modern, new["id"]) == new


def test_unknown_stored_version_is_not_silently_hidden(tmp_path):
    adapter, scenario, _ = enum_scenario()
    store = CafScenarioStore(Store(tmp_path))
    saved = store.save(adapter, scenario)
    scenario["version"] = 3
    content = json.dumps(scenario).encode()
    with store.store.connect() as db:
        db.execute(
            "UPDATE caf_local_scenarios SET content=?,sha256=? WHERE id=?",
            (content, hashlib.sha256(content).hexdigest(), saved["id"]),
        )
    with pytest.raises(ValueError):
        store.list(adapter)


@pytest.mark.parametrize("fault", ["set", "authority", "source", "version"])
def test_exact_original_enum_representation_and_version_cannot_be_substituted(fault):
    adapter, scenario, _ = enum_scenario()
    if fault == "set":
        scenario["inputs"][-1]["enum_representation"]["attributes"]["set"] = "999"
    if fault == "authority":
        scenario["inputs"][-1]["enum_representation"]["enum_semantics_verified"] = True
    if fault == "source":
        scenario["source_sha256"] = "0" * 64
    if fault == "version":
        scenario["version"] = 1
    with pytest.raises(ValueError):
        adapter.validate(scenario)


def test_all_versioned_api_paths_and_matching_native_startup_profile(tmp_path):
    adapter, scenario, _ = enum_scenario()
    with TestClient(create_app(tmp_path)) as client:
        client.headers["X-Studio-Token"] = client.get("/api/session").json()["token"]
        assert (
            client.post(
                "/api/caf", files={"file": ("enum.caf", adapter.archive.original)}
            ).status_code
            == 200
        )
        base = "/api/caf/" + adapter.archive.hash

        def url(path=""):
            return base + "/local-scenarios" + path + "?scenario_version=2"

        assert client.get(base + "/local-scenarios").json()["template"]["version"] == 1
        assert client.get(url()).json()["template"]["version"] == 2
        saved = client.post(
            url("/save"), json={"scenario": scenario, "id": None, "expected_revision": 0}
        ).json()
        assert client.get(url("/" + saved["id"])).json() == saved
        assert client.get(base + "/local-scenarios").json()["saved"] == []
        assert (
            client.post(url("/validate"), json={"scenario": scenario}).json()["scenario"]
            == scenario
        )
        assert client.post(url("/preview"), json={"scenario": scenario}).status_code == 200
        response = client.post(url("/startup-profile"), json={"scenario": scenario, "time": 1})
        assert response.status_code == 200 and response.json()["profile"]["version"] == 2
        profile = response.json()["profile"]
        output = client.post(base + "/simulation?profile_version=2", json={"profile": profile})
        assert output.status_code == 200
        assert CafArchive(output.content).xml == adapter.archive.xml.replace(
            b'<enum set="113">1</enum>', b'<enum set="113">2</enum>'
        )
        assert (
            client.post(base + "/local-scenarios/preview", json={"scenario": scenario}).status_code
            == 422
        )
        assert (
            client.request(
                "DELETE", url("/" + saved["id"]), json={"expected_revision": saved["revision"]}
            ).status_code
            == 200
        )
        assert client.get(url()).json()["saved"] == []
