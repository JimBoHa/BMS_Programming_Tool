"""Actual source prerequisites remain local evidence, never a transfer plan."""

import copy

import pytest
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_batch_transfer_capabilities import PROFILE
from bms_tool.native_default_batch import NativeDefaultBatch
from bms_tool.native_default_batch_transfer import compile_batch_defaults

from .test_moi_enum_defaults import REF as ENUM
from .test_moi_wire_sources import C, D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_batch_capabilities import source
from .test_native_default_batch import SAVED_ENUM, batch_files
from .test_native_wire_compiler import BOOLEAN


def analyze(records, query):
    return records.capabilities(query | {"capability_profile": PROFILE})


def test_actual_transfer_compiler_excludes_unfixed_enum_and_preserves_literal_native_bytes(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Source preflight must not stage a local export review or transfer")

    monkeypatch.setattr(NativeDefaultBatch, "preview", forbidden)
    monkeypatch.setattr(NativeDefaultBatch, "export", forbidden)
    files = batch_files()
    storage, records, snapshot, query = source(tmp_path, files)
    folder = storage.directory / snapshot["id"]
    original = {p.name: p.read_bytes() for p in folder.iterdir()}
    before = records.capabilities(
        query | {"capability_profile": "native-backup-operation-capabilities/20"}
    )
    report = analyze(records, query)
    projected = copy.deepcopy(report)
    projected["capability_profile"] = "native-backup-operation-capabilities/20"
    projected["operations"].pop()
    del projected["qualification"]["typed_default_batch_transfer"]
    assert projected == before
    e = report["qualification"]["typed_default_batch_transfer"]
    assert e["status"] == "source-qualified" and e["error"] is None
    assert (e["field_count"], e["candidate_count"], e["selected_count"], e["compile_attempts"]) == (
        5,
        4,
        4,
        1,
    )
    assert (
        next(f for f in e["fields"] if f["record_ref"] == ENUM)["prerequisite"]
        == "requires-fixed-enum-slot"
    )
    w = e["witness"]
    assert [c["record_ref"] for c in w["request"]["changes"]] == [C, D, BOOLEAN, SAVED_ENUM]
    assert w["transfer_profile"] == "native-effective-default-batch-transfer/1"
    output, compilation = compile_batch_defaults(files, w["request"])
    assert compilation == w["compilation"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    native = MoiIdentity(merged)
    literal = bytearray(native.data)
    for ref, replacement in {
        C: "44000000002f",
        D: "44000000002f",
        BOOLEAN: "102f",
        SAVED_ENUM: "9200002f",
    }.items():
        p = native.reader.records[ref]["properties"][3113]
        a, b = p["value_start_offset"], p["value_end_offset"]
        assert b - a == len(bytes.fromhex(replacement))
        literal[a:b] = bytes.fromhex(replacement)
    assert MoiIdentity(output).data == bytes(literal)
    assert compilation["compiled_native_sha256"] == sha(bytes(literal))
    assert len(compilation["batch_guard"]["fields"]) == 4
    assert compilation["parameter_transfer_qualification"]["model_inventory_used"] is False
    assert all(
        report[k] is False
        for k in ("can_apply", "controller_queries", "field_actions", "current_identity_verified")
    )
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == original


@pytest.mark.parametrize("profile", range(11, 21))
def test_old_profiles_and_api_default_remain_independent(tmp_path, profile):
    _, records, _, query = source(tmp_path)
    requested = query | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
    before = records.capabilities(requested)
    analyze(records, query)
    assert records.capabilities(requested) == before
    assert (
        records.capabilities(query)["capability_profile"]
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
def test_source_prerequisites_do_not_claim_that_a_captured_transport_is_ready(tmp_path, config):
    _, records, _, query = source(tmp_path, connector_config=config)
    report = analyze(records, query)
    assert report["operations"][-1]["status"] == "source-qualified"
    assert report["current_identity_verified"] is report["field_actions"] is False


@pytest.mark.parametrize("fault", ["unknown-saved", "crc", "device", "vendor", "unverified"])
def test_unqualified_captures_withhold_transfer_prerequisites(tmp_path, fault):
    files, metadata = batch_files(), {}
    if fault == "unknown-saved":
        files[11] = b"Authored unsupported saved directory"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "device":
        metadata["device"] = "device,5137"
    elif fault == "vendor":
        metadata["identity"] = {
            "object-name": "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 99,
        }
    else:
        metadata["source_identity_matches"] = False
    _, records, _, query = source(tmp_path, files, **metadata)
    report = analyze(records, query)
    e = report["qualification"]["typed_default_batch_transfer"]
    assert e["status"] == "unsupported-source" and e["error"]
    assert e["source"] is e["field_count"] is e["witness"] is None
    assert (
        e["fields"] == []
        and e["candidate_count"] == e["selected_count"] == e["compile_attempts"] == 0
    )
    assert report["operations"][0]["status"] == "source-qualified"


@pytest.mark.parametrize("fault", ["refusal", "output-hash", "native-hash", "changed-count"])
def test_one_failed_transfer_probe_does_not_claim_all_subsets_are_unsupported(
    tmp_path, monkeypatch, fault
):
    import bms_tool.native_default_batch_transfer as transfer

    calls = []

    def altered(files, edit):
        calls.append(copy.deepcopy(edit))
        if fault == "refusal":
            raise ValueError("Authored bounded transfer refusal")
        output, compilation = compile_batch_defaults(files, edit)
        key = {
            "output-hash": "compiled_sha256",
            "native-hash": "compiled_native_sha256",
            "changed-count": "changed_count",
        }[fault]
        compilation[key] = 0 if key == "changed_count" else "0" * 64
        return output, compilation

    monkeypatch.setattr(transfer, "compile_batch_defaults", altered)
    _, records, _, query = source(tmp_path)
    report = analyze(records, query)
    e = report["qualification"]["typed_default_batch_transfer"]
    assert e["status"] == "not-evaluated" and e["error"] and e["witness"] is None
    assert e["source"] is not None and (
        e["candidate_count"],
        e["selected_count"],
        e["compile_attempts"],
    ) == (4, 4, 1)
    assert len(calls) == 1 and report["qualification"]["typed_default_batch"]["witness"] is not None


def test_only_first_sixteen_actual_candidate_fields_are_compiled(tmp_path):
    _, records, _, query = source(tmp_path, batch_files(extra=20))
    e = analyze(records, query)["qualification"]["typed_default_batch_transfer"]
    assert (e["field_count"], e["candidate_count"], e["selected_count"], e["compile_attempts"]) == (
        25,
        24,
        16,
        1,
    )
    assert len(e["witness"]["request"]["changes"]) == 16


@pytest.mark.parametrize("kind", ["boolean", "enum"])
def test_transfer_prerequisites_do_not_require_real_defaults_or_connections(tmp_path, kind):
    from .test_moi_effective_enum import enum_files
    from .test_native_boolean_copies import boolean_files

    files = enum_files(saved=0) if kind == "enum" else boolean_files(real_signals=False)
    _, records, _, query = source(
        tmp_path,
        files,
        identity={
            "object-name": "Authored controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        },
    )
    e = analyze(records, query)["qualification"]["typed_default_batch_transfer"]
    assert e["status"] == "source-qualified" and e["selected_count"] == (1 if kind == "enum" else 2)
    assert {c["kind"] for c in e["witness"]["request"]["changes"]} == {kind}


@pytest.mark.parametrize("kind", ["empty", "unfixed-enum"])
def test_readable_source_without_candidates_keeps_precise_prerequisite_evidence(tmp_path, kind):
    from .test_moi_effective_enum import enum_files
    from .test_moi_parameters import parameters_source

    files = (
        enum_files(slot=False)
        if kind == "unfixed-enum"
        else dict(zip((3, 11, 12), parameters_source(), strict=True))
    )
    _, records, _, query = source(
        tmp_path,
        files,
        identity={
            "object-name": "Authored controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        },
    )
    e = analyze(records, query)["qualification"]["typed_default_batch_transfer"]
    assert e["status"] == "unsupported-source" and e["error"]
    assert e["source"] is not None and e["field_count"] == (1 if kind == "unfixed-enum" else 0)
    assert (
        e["candidate_count"] == e["selected_count"] == e["compile_attempts"] == 0
        and e["witness"] is None
    )
    if kind == "unfixed-enum":
        assert e["fields"][0]["prerequisite"] == "requires-fixed-enum-slot"


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_original_file_integrity_is_required_before_preflight(tmp_path, file_id):
    storage, records, snapshot, query = source(tmp_path)
    (storage.directory / snapshot["id"] / f"file-{file_id}.bin").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="integrity"):
        analyze(records, query)


def test_http_requires_session_and_explicit_profile_without_opening_an_interface(tmp_path):
    from bms_tool.app import create_app
    from bms_tool.native_batch_transfer_capabilities import batch_transfer_capabilities
    from fastapi.testclient import TestClient

    _, _, _, query = source(tmp_path)
    path = "/api/bacnet/controller/native-application/inspection/capabilities"
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(path, json=query | {"capability_profile": PROFILE}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(path, json=query | {"capability_profile": PROFILE}, headers=headers)
        assert (
            result.status_code == 200
            and result.json()["operations"][-1]["status"] == "source-qualified"
        )
        for extra in [
            {"controller_write": True},
            {"token": "a" * 32},
            {"capability_profile": "native-backup-operation-capabilities/999"},
        ]:
            assert (
                client.post(
                    path, json=query | {"capability_profile": PROFILE} | extra, headers=headers
                ).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
    with pytest.raises(ValueError, match="explicit"):
        batch_transfer_capabilities(None, None, None, records=None, capability_profile="future")


async def test_actual_captured_preflight_after_disconnect_makes_no_plan_journal_or_peer_request(
    native_link, monkeypatch
):
    from bms_tool.native_applications import NativeApplications

    peer, bacnet, _, native, target = native_link
    peer.files = batch_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    capture = await native.capture(**target, operation_id="capture-batch-transfer-prerequisites")
    snapshot, files = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = copy.deepcopy(peer.events)

    def forbidden(*args, **kwargs):
        pytest.fail("Source preflight must not stage a native review or transfer")

    for method in ["preview_default_batch", "apply_default_batch"]:
        monkeypatch.setattr(NativeApplications, method, forbidden)
    report = analyze(
        NativeBackupRecords(native.storage),
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]},
    )
    assert report["operations"][-1]["status"] == "source-qualified"
    assert peer.events == before and not native.plans and not native.storage.receipts()
    assert native.storage.load(snapshot["id"])[1] == files


def test_contradictory_actual_source_refuses_before_the_transfer_compiler(tmp_path, monkeypatch):
    import bms_tool.native_default_batch_transfer as transfer

    original = NativeDefaultBatch.source

    def changed(self, query):
        result = original(self, query)
        result["fields"][0]["name"] = "Contradictory reader"
        return result

    def forbidden(*args, **kwargs):
        pytest.fail("Contradictory source must stop before transfer compilation")

    monkeypatch.setattr(NativeDefaultBatch, "source", changed)
    monkeypatch.setattr(transfer, "compile_batch_defaults", forbidden)
    _, records, _, query = source(tmp_path)
    e = analyze(records, query)["qualification"]["typed_default_batch_transfer"]
    assert (
        e["status"] == "unsupported-source" and e["compile_attempts"] == 0 and e["source"] is None
    )
