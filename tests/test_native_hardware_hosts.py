"""Actual native/CAF host evidence controls occupancy; root naming is not SA wiring."""

import copy
import io
import zipfile

import pytest
from bacpypes3.primitivedata import CharacterString, Null, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.hardware_survey import analyze_archive, enrich_report, relocation_plan
from bms_tool.native_hardware_hosts import input_host
from fastapi.testclient import TestClient

from .test_hardware_survey import authored_archive, native_record, survey_from_archive

MODULES = [
    {"sa_mac": 4, "item_reference": "controller/module", "configured_model": "FX-PCX3711-0"},
    {"sa_mac": 7, "item_reference": "controller/binary", "configured_model": "FX-PCX3721-0"},
]


def resolve(reference="controller/0_56", **options):
    props = {32527: reference, **options.pop("props", {})}
    return input_host(
        props,
        options.pop("present", set(props)),
        options.pop("modules", MODULES),
        "controller",
        sa_records_present=options.pop("sa", True),
    )


def test_root_child_with_sa_modules_stays_unknown_and_cannot_release_capacity():
    raw = authored_archive(root_input_ref=True)
    original = bytes(raw)
    archive = analyze_archive(raw)
    point = next(p for p in archive["inputs"] if p["object"] == "analog-input,56")
    assert point["host"]["kind"] == "unknown" and point["sa_mac"] is None
    assert "does not establish a local host" in point["errors"][0]["error"]
    assert not archive["inventory"]["complete"]
    assert archive["modules"] and all(c["status"] == "unverified" for c in archive["candidates"])
    report = enrich_report(survey_from_archive(archive), archive)
    assert (
        report["archive_comparison"]["unresolved"]
        and not report["archive_comparison"]["configured_models_applied"]
    )
    assert relocation_plan(archive, "binary-input,55", 7, 16)["status"] == "blocked"
    assert raw == original


def test_no_sa_records_retains_local_root_inference_and_exact_other_host_forms():
    host, error = resolve(modules=[], sa=False)
    assert error is None and host["kind"] == "local-configured"
    host, error = resolve("controller/module.0_56")
    assert error is None and host["kind"] == "sa" and host["sa_mac"] == 4
    host, error = resolve(props={3645: 7})
    assert error is None and host["kind"] == "sa" and host["sa_mac"] == 7
    assert "unique configured module" in host["evidence"]
    host, error = resolve("controller/module.0_56", props={3645: 4})
    assert error is None and host["sa_mac"] == 4


@pytest.mark.parametrize(
    "case",
    [
        "orphan",
        "duplicate-mac",
        "duplicate-ref",
        "nested-ambiguous",
        "conflict",
        "bool",
        "float",
        "null",
        "zero",
        "negative",
        "oversized",
        "unknown-encoding",
        "device-reference",
        "bad-prefix",
        "bad-root",
    ],
)
def test_conflicting_or_unknown_host_evidence_never_becomes_a_local_assignment(case):
    options = {}
    reference = "controller/0_56"
    if case == "orphan":
        options["props"] = {3645: 8}
    if case == "duplicate-mac":
        options = {
            "props": {3645: 4},
            "modules": MODULES + [{"sa_mac": 4, "item_reference": "other"}],
        }
    if case == "duplicate-ref":
        reference = "controller/module.0_56"
        options["modules"] = MODULES + [{"sa_mac": 5, "item_reference": "controller/module"}]
    if case == "nested-ambiguous":
        reference = "controller/module.child.0_56"
        options["modules"] = MODULES + [{"sa_mac": 5, "item_reference": "controller/module.child"}]
    if case == "conflict":
        reference = "controller/module.0_56"
        options["props"] = {3645: 7}
    if case in ("bool", "float", "null", "zero", "negative", "oversized"):
        options["props"] = {
            3645: {
                "bool": True,
                "float": 4.0,
                "null": None,
                "zero": 0,
                "negative": -1,
                "oversized": 255,
            }[case]
        }
    if case == "unknown-encoding":
        options["present"] = {32527, 3645}
    if case == "device-reference":
        options["props"] = {2577: "opaque", 3645: 4}
    if case == "bad-prefix":
        reference = "controller/modulex.0_56"
    if case == "bad-root":
        reference = "controllerx/0_56"
        options.update(modules=[], sa=False)
    original = copy.deepcopy(options)
    host, error = resolve(reference, **options)
    assert host["kind"] == "unknown" and error and options == original


def test_invalid_configured_module_does_not_make_root_inputs_local():
    raw = authored_archive(root_input_ref=True).replace(
        Unsigned(4).encode().encode().pduData, Unsigned(0).encode().encode().pduData, 1
    )
    archive = analyze_archive(raw)
    assert any("valid MAC address" in e["error"] for e in archive["errors"])
    assert (
        next(p for p in archive["inputs"] if p["object"] == "analog-input,56")["host"]["kind"]
        == "unknown"
    )
    assert not archive["inventory"]["complete"] and all(
        c["status"] == "unverified" for c in archive["candidates"]
    )


@pytest.mark.parametrize(
    "value", [Unsigned(4), Unsigned(8), Null(())], ids=["matching", "orphan", "null"]
)
def test_native_explicit_address_is_resolved_only_to_a_unique_recorded_module(value):
    point = native_record(
        240,
        99,
        [
            (75, ObjectIdentifier(("analog-input", 99))),
            (31, CharacterString("UI IN2")),
            (519, Unsigned(2)),
            (3645, value),
            (32527, CharacterString("8-1/0_99")),
        ],
    )
    archive = analyze_archive(authored_archive() + point)
    p = next(p for p in archive["inputs"] if p["object"] == "analog-input,99")
    if isinstance(value, Unsigned) and int(value) == 4:
        assert p["host"]["kind"] == "sa" and p["sa_mac"] == 4 and not p["errors"]
    else:
        assert p["host"]["kind"] == "unknown" and p["errors"]
        assert not archive["inventory"]["complete"] and all(
            c["status"] == "unverified" for c in archive["candidates"]
        )


@pytest.mark.parametrize("explicit", [False, True])
def test_caf_root_reference_and_explicit_sa_binding_use_the_same_resolver(explicit):
    from bms_tool.caf import NS

    def prop(pid, leaf):
        return f'<property id="{pid}"><data>{leaf}</data></property>'

    xml = (
        f'<objects xmlns="{NS}"><object classid="194" ref="controller" objectid="1">'
        + prop(75, '<BACoid id="8">123</BACoid>')
        + prop(70, "<string>FX-PCG2611-0</string>")
        + '</object><object classid="598" ref="controller/module" objectid="2">'
        + prop(2858, "<unsignedByte>4</unsignedByte>")
        + prop(3676, "<string>FX-PCX3711-0</string>")
        + '</object><object classid="240" ref="controller/0_56" objectid="56">'
        + prop(75, '<BACoid id="0">56</BACoid>')
        + prop(31, "<string>UI IN1</string>")
        + prop(519, "<unsignedByte>1</unsignedByte>")
        + (prop(3645, "<unsignedByte>4</unsignedByte>") if explicit else "")
        + "</object></objects>"
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("authored.xml", xml)
    archive = analyze_archive(stream.getvalue(), "authored.caf")
    point = archive["inputs"][0]
    assert point["host"]["kind"] == ("sa" if explicit else "unknown")
    assert archive["inventory"]["complete"] is explicit
    assert all(
        c["status"] == ("candidate" if explicit else "unverified") for c in archive["candidates"]
    )


def test_archive_api_retains_ambiguous_evidence_and_exact_source_after_restart(
    tmp_path, monkeypatch
):
    raw = authored_archive(root_input_ref=True)
    app = create_app(tmp_path)

    def forbidden(*a, **k):
        pytest.fail("Offline host analysis accessed a field or write path")

    for name in ("require", "connect", "_read", "release", "disconnect"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(
            "/api/bacnet/hardware/archive", files={"file": ("ambiguous.moi", raw)}, headers=headers
        )
        assert result.status_code == 200, result.text
        value = result.json()
        identifier = value["id"]
        assert (
            not value["inventory"]["complete"]
            and not client.get("/api/session").json()["field_network_open"]
        )
    with TestClient(create_app(tmp_path)) as client:
        saved = client.get("/api/bacnet/hardware/archives/" + identifier).json()
        assert saved == value
        response = client.get(
            "/api/bacnet/hardware/archives/" + identifier + "/export?format=source"
        )
        assert response.status_code == 200 and response.content == raw
