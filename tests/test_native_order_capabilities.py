"""Actual, bounded order witnesses with no controller or transfer authority."""

import copy

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_order_capabilities import LIMITS, PROFILE
from bms_tool.native_order_transfer import compile_order
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF
from .test_native_execution_order import IDENTITY, many_source, setup
from .test_native_wire_compiler import wire_files


def analyze(service, snapshot):
    return service.records.capabilities(
        {
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "capability_profile": PROFILE,
        }
    )


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
def test_actual_literal_witness_and_old_report_projection_are_exact(
    tmp_path, compressed, extended, diagram_class
):
    files = wire_files(compressed=compressed, extended=extended, diagram_class=diagram_class)
    storage, service, snapshot, query = setup(tmp_path, files)
    folder = storage.directory / snapshot["id"]
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    before = service.records.capabilities(
        {
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "capability_profile": "native-backup-operation-capabilities/14",
        }
    )
    report = analyze(service, snapshot)
    projected = copy.deepcopy(report)
    projected["capability_profile"] = "native-backup-operation-capabilities/14"
    projected["operations"] = projected["operations"][:-2]
    del projected["qualification"]["execution_order"]
    assert projected == before
    evidence = report["qualification"]["execution_order"]
    assert evidence["status"] == "source-qualified" and evidence["error"] is None
    assert evidence["limits"] == LIMITS
    assert (
        evidence["diagram_count"],
        evidence["examined_diagrams"],
        evidence["compile_attempts"],
    ) == (1, 1, 1)
    w = evidence["witness"]
    assert w["record"] == {
        "ref": REF,
        "record_sha256": query["record_sha256"],
        "class_id": diagram_class,
    }
    assert w["request"]["proposed_order"] == [1, 0, 2, 3]
    output, review = service.preview(w["request"])
    assert review == w["review"]
    field_output, compilation = compile_order(files, w["request"])
    assert field_output == output and compilation == w["transfer_compilation"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    literal = MoiIdentity(merged).data.replace(
        b"\x21\x00\x21\x01\x21\x02\x21\x03\x2f", b"\x21\x01\x21\x00\x21\x02\x21\x03\x2f", 1
    )
    assert MoiIdentity(output).data == literal and compilation["compiled_native_sha256"] == sha(
        literal
    )
    assert report["operations"][-2]["status"] == "source-qualified"
    assert report["operations"][-1]["status"] == "preflight-required"
    assert all(
        report[k] is False
        for k in ("can_apply", "controller_queries", "field_actions", "current_identity_verified")
    )
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original
    assert not storage.receipts()


@pytest.mark.parametrize("profile", range(11, 22))
def test_previous_profiles_and_default_remain_independent(tmp_path, profile):
    _, service, snapshot, _ = setup(tmp_path)
    q = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    request = q | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
    before = service.records.capabilities(request)
    analyze(service, snapshot)
    assert service.records.capabilities(request) == before
    assert (
        service.records.capabilities(q)["capability_profile"]
        == "native-backup-operation-capabilities/12"
    )


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"transport": "mstp", "serial_port": "authored-none"},
        {"local_address": "127.0.0.1:47819", "bbmd_address": "127.0.0.1:47820"},
    ],
)
def test_local_witness_remains_useful_without_captured_plain_ipv4(tmp_path, config):
    _, service, snapshot, _ = setup(tmp_path, connector_config=config)
    report = analyze(service, snapshot)
    assert report["qualification"]["execution_order"]["status"] == "source-qualified"
    assert report["operations"][-2]["status"] == "source-qualified"
    assert report["operations"][-1]["status"] == "transport-unavailable"
    assert not report["can_apply"] and not report["controller_queries"]


@pytest.mark.parametrize(
    "metadata",
    [
        {"source_identity_matches": False},
        {"identity": {**IDENTITY, "vendor-identifier": 5.0}},
        {"identity": {**IDENTITY, "vendor-identifier": 1}},
    ],
)
def test_unqualified_identity_never_produces_a_witness(tmp_path, metadata):
    _, service, snapshot, _ = setup(tmp_path, **metadata)
    report = analyze(service, snapshot)
    e = report["qualification"]["execution_order"]
    assert e["status"] == "source-mismatch" and e["witness"] is None
    assert e["compile_attempts"] == e["examined_diagrams"] == 0
    assert report["operations"][-1]["status"] == "source-mismatch"


@pytest.mark.parametrize("kind", ["chain", "single", "unsupported", "oversize"])
def test_no_bounded_witness_does_not_claim_no_other_program_is_possible(
    tmp_path, kind, monkeypatch
):
    files = (
        wire_files(wires=[(0, 85, 1, 7000), (1, 85, 2, 7000), (2, 85, 3, 7000)])
        if kind == "chain"
        else wire_files()
    )
    if kind == "single":
        files[3] = many_source(1)
    if kind == "unsupported":
        files[11] = b"Unknown saved schema"
    if kind == "oversize":
        monkeypatch.setitem(LIMITS, "witness_bytes", 1)
    _, service, snapshot, _ = setup(tmp_path, files)
    e = analyze(service, snapshot)["qualification"]["execution_order"]
    assert e["status"] in ("not-evaluated", "unsupported-source") and e["error"]
    assert e["witness"] is None and e["compile_attempts"] <= LIMITS["compile_attempts"]


def test_transfer_prerequisite_failure_keeps_valid_local_compilation(tmp_path, monkeypatch):
    import bms_tool.native_order_transfer as transfer

    def refused(*args, **kwargs):
        raise ValueError("Authored omitted-field refusal")

    monkeypatch.setattr(transfer, "compile_order", refused)
    _, service, snapshot, _ = setup(tmp_path)
    r = analyze(service, snapshot)
    e = r["qualification"]["execution_order"]
    assert e["status"] == "source-qualified" and e["witness"]["transfer_compilation"] is None
    assert e["transfer_error"] == "Authored omitted-field refusal"
    assert r["operations"][-1]["status"] == "unsupported-source"


def test_disagreeing_transfer_output_never_qualifies(tmp_path, monkeypatch):
    import bms_tool.native_order_transfer as transfer

    original = transfer.compile_order

    def changed(*args, **kwargs):
        output, report = original(*args, **kwargs)
        return output + b"changed", report

    monkeypatch.setattr(transfer, "compile_order", changed)
    _, service, snapshot, _ = setup(tmp_path)
    e = analyze(service, snapshot)["qualification"]["execution_order"]
    assert e["witness"]["transfer_compilation"] is None
    assert "disagree" in e["transfer_error"]


def test_analysis_does_not_call_any_field_or_plan_service(tmp_path, monkeypatch):
    from bms_tool.native_applications import NativeApplications

    def forbidden(*args, **kwargs):
        pytest.fail("Capability analysis attempted a field/plan action")

    for name in ("preview_order", "apply_order", "capture", "reconcile", "retain_plan"):
        monkeypatch.setattr(NativeApplications, name, forbidden)
    storage, service, snapshot, _ = setup(tmp_path)
    assert (
        analyze(service, snapshot)["qualification"]["execution_order"]["status"]
        == "source-qualified"
    )
    assert not storage.receipts()


def test_http_requires_token_and_never_opens_field_interface(tmp_path):
    storage, service, snapshot, _ = setup(tmp_path)
    before = storage.load(snapshot["id"])
    with TestClient(create_app(tmp_path)) as client:
        q = {
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "capability_profile": PROFILE,
        }
        url = "/api/bacnet/controller/native-application/inspection/capabilities"
        assert client.post(url, json=q).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(url, json=q, headers=headers)
        assert (
            response.status_code == 200
            and response.json()["qualification"]["execution_order"]["status"] == "source-qualified"
        )
        assert client.post(url, json=q | {"can_apply": True}, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
    assert storage.load(snapshot["id"]) == before and not storage.receipts()
