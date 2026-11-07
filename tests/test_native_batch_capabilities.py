"""Local batch evidence uses actual saved native fields and grants no field plan."""

import copy
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_default_batch import EffectiveDefaultBatchCompiler
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_batch_capabilities import PROFILE, batch_capabilities
from bms_tool.native_default_batch import NativeDefaultBatch
from fastapi.testclient import TestClient

from .test_moi_enum_defaults import REF as ENUM
from .test_moi_wire_sources import C, D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_batch import SAVED_ENUM, batch_files
from .test_native_wire_compiler import BOOLEAN, setup


def source(tmp_path, files=None, **metadata):
    storage, _, snapshot = setup(tmp_path, files or batch_files(), **metadata)
    query = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    return storage, NativeBackupRecords(storage), snapshot, query


def analyze(records, query):
    return records.capabilities(query | {"capability_profile": PROFILE})


def test_actual_five_change_witness_has_literal_native_bytes_and_no_review_or_mutation(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Capability analysis must not issue a local export review.")

    monkeypatch.setattr(NativeDefaultBatch, "preview", forbidden)
    monkeypatch.setattr(NativeDefaultBatch, "export", forbidden)
    files = batch_files()
    original = copy.deepcopy(files)
    storage, records, snapshot, query = source(tmp_path, files)
    folder = storage.directory / snapshot["id"]
    before_files = {p.name: p.read_bytes() for p in folder.iterdir()}
    report = analyze(records, query)
    e = report["qualification"]["typed_default_batch"]
    assert e["status"] == "source-qualified" and e["error"] is None
    assert (e["field_limit"], e["field_count"], e["selected_count"], e["compile_attempts"]) == (
        16,
        5,
        5,
        1,
    )
    w = e["witness"]
    assert set(w) == {"source", "request", "compilation"}
    assert w["source"] == NativeDefaultBatch(records).source(query)
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    native = MoiIdentity(merged)
    expected = bytearray(native.data)
    literals = {
        C: bytes.fromhex("44000000002f"),
        D: bytes.fromhex("44000000002f"),
        BOOLEAN: bytes.fromhex("102f"),
        ENUM: bytes.fromhex("91002f"),
        SAVED_ENUM: bytes.fromhex("9200002f"),
    }
    for ref, replacement in literals.items():
        p = native.reader.records[ref]["properties"][3113]
        a, b = p["value_start_offset"], p["value_end_offset"]
        assert b - a == len(replacement)
        expected[a:b] = replacement
    c = w["compilation"]
    assert c["compiled_native_sha256"] == sha(bytes(expected))
    assert c["edit_count"] == c["changed_count"] == 5
    assert c["both_orders_identical"] and c["other_merged_bytes_preserved"]
    assert len(c["independent"]) == len(c["forward"]) == len(c["reverse"]) == 5
    assert report["operations"][-1]["status"] == "source-qualified"
    assert report["read_only"] and not any(
        report[k]
        for k in ["controller_queries", "field_actions", "can_apply", "current_identity_verified"]
    )
    assert not {"review_sha256", "token", "payload", "plan"}.intersection(w)
    assert files == original and storage.load(snapshot["id"])[1] == original
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before_files
    assert not storage.receipts()


@pytest.mark.parametrize("profile", range(11, 20))
def test_explicit_old_profiles_and_default_keep_their_independent_contract(tmp_path, profile):
    _, records, _, query = source(tmp_path)
    old = records.capabilities(
        query | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
    )
    report = analyze(records, query)
    assert (
        records.capabilities(
            query | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
        )
        == old
    )
    if profile == 19:
        projected = copy.deepcopy(report)
        projected["capability_profile"] = "native-backup-operation-capabilities/19"
        projected["operations"] = projected["operations"][:-1]
        del projected["qualification"]["typed_default_batch"]
        assert projected == old and len(report["operations"]) == 37
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
def test_local_batch_is_independent_of_captured_field_transport(tmp_path, config):
    _, records, _, query = source(tmp_path, connector_config=config)
    report = analyze(records, query)
    assert report["operations"][-1]["status"] == "source-qualified"
    assert report["qualification"]["typed_default_batch"]["selected_count"] == 5


@pytest.mark.parametrize("fault", ["unknown-saved", "crc", "device", "vendor", "unverified"])
def test_readable_but_unqualified_sources_do_not_receive_a_batch_witness(tmp_path, fault):
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
    e = report["qualification"]["typed_default_batch"]
    assert e["status"] == "unsupported-source" and e["error"]
    assert e["witness"] is None and e["field_count"] is None
    assert e["compile_attempts"] == e["selected_count"] == 0
    assert report["operations"][0]["status"] == "source-qualified"


@pytest.mark.parametrize("fault", ["refusal", "output-hash", "native-hash", "changed-count"])
def test_one_failed_bounded_probe_is_not_a_claim_that_every_batch_is_impossible(
    tmp_path, monkeypatch, fault
):
    original = EffectiveDefaultBatchCompiler.compile
    calls = []

    def altered(self, changes):
        calls.append(copy.deepcopy(changes))
        if fault == "refusal":
            raise ValueError("Authored unsupported first batch")
        output, report = original(self, changes)
        report[
            {
                "output-hash": "compiled_sha256",
                "native-hash": "compiled_native_sha256",
                "changed-count": "changed_count",
            }[fault]
        ] = 0 if fault == "changed-count" else "0" * 64
        return output, report

    monkeypatch.setattr(EffectiveDefaultBatchCompiler, "compile", altered)
    storage, records, _, query = source(tmp_path, batch_files(extra=20))
    e = analyze(records, query)["qualification"]["typed_default_batch"]
    assert e["status"] == "not-evaluated" and e["error"] and e["witness"] is None
    assert e["field_count"] == 25 and e["selected_count"] == 16
    assert e["compile_attempts"] == len(calls) == 1 and len(calls[0]) == 16
    assert len({c["record_ref"] for c in calls[0]}) == 16 and not storage.receipts()


def test_successful_witness_is_also_bounded_to_sixteen_actual_fields(tmp_path):
    _, records, _, query = source(tmp_path, batch_files(extra=20))
    e = analyze(records, query)["qualification"]["typed_default_batch"]
    assert e["status"] == "source-qualified" and e["field_count"] == 25
    assert e["selected_count"] == e["witness"]["compilation"]["changed_count"] == 16


@pytest.mark.parametrize("kind", ["boolean", "enum"])
def test_batch_support_does_not_require_real_defaults_or_a_native_connection(tmp_path, kind):
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
    report = analyze(records, query)
    e = report["qualification"]["typed_default_batch"]
    assert report["qualification"]["effective_real_default_count"] == 0
    assert e["status"] == "source-qualified" and e["selected_count"] == (1 if kind == "enum" else 2)
    assert {row["kind"] for row in e["witness"]["source"]["fields"]} == {kind}
    if kind == "enum":
        assert e["witness"]["request"]["changes"][0]["value"] == 1


def test_contradictory_actual_source_withholds_the_witness_before_compilation(
    tmp_path, monkeypatch
):
    original = NativeDefaultBatch.source

    def changed(self, query):
        source = original(self, query)
        source["effective_sha256"] = "0" * 64
        return source

    monkeypatch.setattr(NativeDefaultBatch, "source", changed)
    _, records, _, query = source(tmp_path)
    e = analyze(records, query)["qualification"]["typed_default_batch"]
    assert e["status"] == "unsupported-source" and e["witness"] is None
    assert e["compile_attempts"] == 0 and e["field_count"] is None


def test_empty_typed_source_remains_readable_without_claiming_batch_support(tmp_path):
    from .test_moi_parameters import parameters_source
    from .test_native_signal_compiler import retained

    storage, records, _, _ = source(tmp_path)
    files = dict(zip((3, 11, 12), parameters_source(), strict=True))
    snapshot = retained(storage, files)
    report = analyze(
        records, {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    e = report["qualification"]["typed_default_batch"]
    assert e["status"] == "unsupported-source" and e["field_count"] == 0
    assert e["selected_count"] == e["compile_attempts"] == 0 and e["witness"] is None
    assert report["operations"][0]["status"] == "source-qualified"


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_changed_original_files_block_the_whole_analysis(tmp_path, file_id):
    storage, records, snapshot, query = source(tmp_path)
    (storage.directory / snapshot["id"] / f"file-{file_id}.bin").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="integrity"):
        analyze(records, query)


def test_http_requires_token_and_explicit_profile_and_creates_no_interface(tmp_path):
    _, _, _, query = source(tmp_path)
    path = "/api/bacnet/controller/native-application/inspection/capabilities"
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(path, json=query | {"capability_profile": PROFILE}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        r = client.post(path, json=query | {"capability_profile": PROFILE}, headers=headers)
        assert r.status_code == 200 and r.json()["operations"][-1]["status"] == "source-qualified"
        for extra in [
            {"controller_write": True},
            {"capability_profile": "native-backup-operation-capabilities/22"},
        ]:
            assert (
                client.post(
                    path, json=query | {"capability_profile": PROFILE} | extra, headers=headers
                ).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]
    with pytest.raises(ValueError, match="explicit"):
        batch_capabilities(None, None, None, records=None, capability_profile="legacy")


async def test_captured_batch_analysis_works_after_disconnect_without_another_peer_request(
    native_link,
):
    peer, bacnet, _, native, target = native_link
    peer.files = batch_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    seen, original = [], peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    capture = await native.capture(**target, operation_id="capture-for-typed-batch-capabilities")
    snapshot, files = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = list(seen)
    report = analyze(
        NativeBackupRecords(native.storage),
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]},
    )
    assert report["operations"][-1]["status"] == "source-qualified"
    assert "AtomicReadFileRequest" in before and "ReinitializeDeviceRequest" in before
    assert seen == before and not native.storage.receipts()
    assert native.storage.load(snapshot["id"])[1] == files
