"""Actual paired compiler witnesses stay separate from edits, transfer and transport."""

import copy
import struct
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_combined_capabilities import PROFILE
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, B, C
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_default_wire import setup
from .test_native_default_wire_transfer import combined_files


def source(tmp_path, files=None, **metadata):
    storage, _, snapshot = setup(tmp_path, files or combined_files(), **metadata)
    records = NativeBackupRecords(storage)
    request = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    return storage, records, snapshot, request


def test_actual_pair_has_two_literal_native_deltas_and_no_export_or_field_plan(tmp_path):
    files = combined_files()
    original = copy.deepcopy(files)
    storage, service, snapshot, request = source(tmp_path, files)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    evidence = report["qualification"]["combined_default_wire"]
    assert evidence["status"] == "source-qualified" and evidence["error"] is None
    assert evidence["pair_attempts"] == 1 and evidence["pair_limit"] == 16
    witness = evidence["witness"]
    assert set(witness) == {"signal", "source", "selection", "edit", "compilation"}
    assert witness["edit"]["record_ref"] == C and witness["edit"]["source_ref"] == B
    assert witness["edit"]["value_text"] == "0"
    compilation = witness["compilation"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    native = MoiIdentity(merged)
    expected = bytearray(native.data)
    offset = native.reader.records[C]["properties"][3113]["value_start_offset"] + 1
    expected[offset : offset + 4] = struct.pack(">f", 0)
    offset = native.reader.records[REF]["properties"][3118]["value_start_offset"] + 2
    expected[offset] = 1
    assert compilation["compiled_native_sha256"] == sha(bytes(expected))
    assert compilation["selected_default"]["changed"] and compilation["selected_wire"]["changed"]
    assert evidence["transfer_qualification"]["model_inventory_used"] is False
    assert report["operations"][-2]["status"] == "source-qualified"
    assert report["operations"][-1]["status"] == "preflight-required"
    assert report["read_only"] and not any(
        report[k]
        for k in ("controller_queries", "field_actions", "can_apply", "current_identity_verified")
    )
    assert not {"review_sha256", "token", "export", "payload"}.intersection(witness)
    assert storage.load(snapshot["id"])[1] == original and not storage.receipts()


@pytest.mark.parametrize("profile", range(11, 19))
def test_all_explicit_previous_profiles_and_default_are_unchanged(tmp_path, profile):
    _, service, _, request = source(tmp_path)
    old = service.capabilities(
        request | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
    )
    extended = service.capabilities(request | {"capability_profile": PROFILE})
    assert (
        service.capabilities(
            request | {"capability_profile": f"native-backup-operation-capabilities/{profile}"}
        )
        == old
    )
    if profile == 18:
        projected = copy.deepcopy(extended)
        del projected["qualification"]["combined_default_wire"]
        projected["operations"] = projected["operations"][:-2]
        projected["capability_profile"] = "native-backup-operation-capabilities/18"
        assert projected == old and len(extended["operations"]) == 36
    assert (
        service.capabilities(request)["capability_profile"]
        == "native-backup-operation-capabilities/12"
    )


@pytest.mark.parametrize(
    "config",
    [
        {"transport": "mstp", "serial_port": "authored-none"},
        {"local_address": "127.0.0.1:47819", "bbmd_address": "127.0.0.1:47820"},
        {},
    ],
)
def test_local_pair_is_independent_of_captured_transfer_transport(tmp_path, config):
    _, service, _, request = source(tmp_path, connector_config=config)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    assert report["operations"][-2]["status"] == "source-qualified"
    assert report["operations"][-1]["status"] == "transport-unavailable"


@pytest.mark.parametrize("fault", ["unknown-saved", "crc", "identity", "vendor", "unverified"])
def test_source_faults_withhold_joint_witness_without_hiding_readable_archive(tmp_path, fault):
    files = combined_files()
    metadata = {}
    if fault == "unknown-saved":
        files[11] = b"Authored unsupported saved directory"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault == "identity":
        metadata["identity"] = {
            "object-name": "Different name",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        }
    elif fault == "vendor":
        metadata["identity"] = {
            "object-name": "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 99,
        }
    else:
        metadata["source_identity_matches"] = False
    _, service, _, request = source(tmp_path, files, **metadata)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    assert report["operations"][0]["status"] == "source-qualified"
    evidence = report["qualification"]["combined_default_wire"]
    assert evidence["witness"] is None and evidence["error"]
    assert evidence["transfer_qualification"] is None
    assert report["operations"][-2]["status"] == "unsupported-source"
    assert report["operations"][-1]["status"] in ("unsupported-source", "source-mismatch")


def test_transfer_type_failure_does_not_demote_a_valid_local_pair(tmp_path, monkeypatch):
    from bms_tool import native_combined_capabilities as combined

    def refuse(*args):
        raise ValueError("Authored missing native storage-type qualification")

    monkeypatch.setattr(combined, "qualify_parameter_additions", refuse)
    _, service, _, request = source(tmp_path)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    evidence = report["qualification"]["combined_default_wire"]
    assert evidence["witness"] is not None and evidence["transfer_qualification"] is None
    assert evidence["transfer_error"] == "Authored missing native storage-type qualification"
    assert [r["status"] for r in report["operations"][-2:]] == [
        "source-qualified",
        "unsupported-source",
    ]


def test_failed_pair_probe_is_not_a_claim_that_every_pair_is_impossible(tmp_path, monkeypatch):
    from bms_tool.moi_default_wire import EffectiveDefaultWireCompiler

    def refuse(*args, **kwargs):
        raise ValueError("Authored pair is unqualified")

    monkeypatch.setattr(EffectiveDefaultWireCompiler, "compile", refuse)
    _, service, _, request = source(tmp_path)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    evidence = report["qualification"]["combined_default_wire"]
    assert evidence["status"] == "not-evaluated" and evidence["pair_attempts"] == 2
    assert evidence["witness"] is None and evidence["transfer_qualification"] is None
    assert [r["status"] for r in report["operations"][-2:]] == ["not-evaluated", "not-evaluated"]


def test_actual_seventeen_additional_fields_do_not_exceed_the_paired_search_budget(
    tmp_path, monkeypatch
):
    import gzip

    from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real
    from bms_tool.moi_default_wire import EffectiveDefaultWireCompiler

    from .test_controller_application import encoded, native_record

    files = combined_files()
    data = bytearray(MoiIdentity(files[3]).data)
    data[10:14] = (int.from_bytes(data[10:14], "little") + 17).to_bytes(4, "little")
    for index in range(100, 117):
        record = native_record(
            526,
            index,
            [
                (32527, encoded(CharacterString(f"controller/additional_{index}"))),
                (75, encoded(ObjectIdentifier(("analog-value", index)))),
                (2390, encoded(CharacterString(f"Authored field {index}"))),
                (3113, encoded(Real(3.5))),
            ],
        )
        data.extend(struct.pack("<H", len(record) + 2) + record)
    files[3] = gzip.compress(data, mtime=123)
    attempts = []

    def refuse(*args, **kwargs):
        attempts.append(kwargs["record_ref"])
        raise ValueError("Authored pair inspection refusal")

    monkeypatch.setattr(EffectiveDefaultWireCompiler, "compile", refuse)
    _, service, _, request = source(tmp_path, files)
    report = service.capabilities(request | {"capability_profile": PROFILE})
    evidence = report["qualification"]["combined_default_wire"]
    assert len(attempts) == len(set(attempts)) == evidence["pair_attempts"] == 16
    assert evidence["status"] == "not-evaluated" and evidence["witness"] is None


def test_actual_http_is_token_admitted_closed_and_does_not_open_an_interface(tmp_path):
    _, _, _, request = source(tmp_path)
    app = create_app(tmp_path)
    path = "/api/bacnet/controller/native-application/inspection/capabilities"
    with TestClient(app) as client:
        assert client.post(path, json=request | {"capability_profile": PROFILE}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            path, json=request | {"capability_profile": PROFILE}, headers=headers
        )
        assert (
            response.status_code == 200
            and response.json()["operations"][-2]["status"] == "source-qualified"
        )
        for extra in [
            {"controller_write": True},
            {"capability_profile": "native-backup-operation-capabilities/21"},
        ]:
            assert (
                client.post(
                    path, json=request | {"capability_profile": PROFILE} | extra, headers=headers
                ).status_code
                == 422
            )
        assert not client.get("/api/session").json()["field_network_open"]


async def test_captured_pair_is_analyzed_after_disconnect_without_another_peer_request(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = combined_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    capture = await native.capture(**target, operation_id="capture-for-combined-capabilities")
    snapshot, files = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = list(seen)
    report = NativeBackupRecords(native.storage).capabilities(
        {
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
            "capability_profile": PROFILE,
        }
    )
    assert [r["status"] for r in report["operations"][-2:]] == [
        "source-qualified",
        "preflight-required",
    ]
    assert "ReinitializeDeviceRequest" in before and "AtomicReadFileRequest" in before
    assert seen == before and not native.storage.receipts()
    assert native.storage.load(snapshot["id"])[1] == files
