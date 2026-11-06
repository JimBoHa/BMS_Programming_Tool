"""Authored byte deltas qualify local default/wire composition, without a runtime claim."""

import struct
import types

import pytest
from bms_tool.app import create_app
from bms_tool.moi_default_wire import PROFILE, EffectiveDefaultWireCompiler
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_wire import NativeDefaultWire
from fastapi.testclient import TestClient

from .test_moi_wire_sources import REF, A, B, C
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained, slot
from .test_native_wire_compiler import BOOLEAN, wire_files
from .test_native_wire_compiler import setup as wire_setup

BASE = "/api/bacnet/controller/native-application/inspection/default-wire"
IDENTITY = {
    "object-name": "Authored native wire controller",
    "vendor-identifier": 5,
    "model-name": "UNLISTED-MODEL",
}


def setup(tmp_path, files=None, **metadata):
    storage, _, snapshot = wire_setup(tmp_path, files, **metadata)
    return storage, NativeDefaultWire(NativeBackupRecords(storage)), snapshot


def source_request(snapshot):
    return {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}


def proposal(service, snapshot, *, replacement=B, value="0.1"):
    source = service.source(source_request(snapshot))
    diagram = next(row for row in source["diagrams"] if row["ref"] == REF)
    query = source_request(snapshot) | {
        "source_sha256": source["source_sha256"],
        "effective_sha256": source["effective_sha256"],
        "diagram_ref": REF,
        "record_sha256": diagram["archive_record_sha256"],
        "wire_index": 0,
    }
    selection = service.selection(query)["selection"]
    field = next(row for row in source["fields"] if row["ref"] == C)
    return query | {
        "effective_record_sha256": selection["record_sha256"],
        "property_sha256": selection["property_sha256"],
        "old": selection["selected_wire"]["old"],
        "source_ref": replacement,
        "record_ref": C,
        "encoded_sha256": field["encoded_sha256"],
        "value_text": value,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("value", ["-0", "0.1", "3", "3.4028234663852886e38"])
@pytest.mark.parametrize("replacement", [A, B], ids=["wire-noop", "wire-change"])
def test_literal_disjoint_patches_both_orders_and_all_other_saved_bytes(
    tmp_path, compressed, extended, width, value, replacement
):
    files = wire_files(compressed=compressed, extended=extended, source_index_width=width)
    storage, service, snapshot = setup(tmp_path, files)
    original = dict(files)
    body = proposal(service, snapshot, replacement=replacement, value=value)
    output, review = service.preview(body)
    compilation = review["compilation"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(output)
    # Derive offsets and replacement bytes from authored native framing, not the
    # compiler's claimed result. Every unselected byte must remain identical.
    default_offset = before.reader.records[C]["properties"][3113]["value_start_offset"] + 1
    wire_offset = before.reader.records[REF]["properties"][3118]["value_start_offset"] + 2
    expected = bytearray(before.data)
    expected[default_offset : default_offset + 4] = struct.pack(">f", float(value))
    expected[wire_offset : wire_offset + width] = (0 if replacement == A else 1).to_bytes(
        width, "big"
    )
    assert after.data == bytes(expected)
    assert after.reader.diagram(REF)["connections"][0]["source_ref"] == replacement
    assert after.reader.scalar(after.reader.records[A], 3113) == 42
    assert after.reader.scalar(after.reader.records[B], 3113) == 17
    assert after.reader.scalar(after.reader.records[BOOLEAN], 3113) is True
    assert after.reader.records.keys() == before.reader.records.keys()
    assert compilation["both_orders_identical"] and compilation["disjoint_fields"]
    assert compilation["other_merged_bytes_preserved"] and compilation["saved_settings_merged"]
    assert compilation["selected_default"]["native_byte_offset"] == default_offset
    assert compilation["selected_wire"]["source_index_offset"] == wire_offset
    assert compilation["selected_wire"]["source_index_bytes"] == width
    independent_default = compilation["independent_default"]
    independent_wire = compilation["independent_wire"]
    assert (
        compilation["default_then_wire"]["intermediate_sha256"]
        == independent_default["compiled_sha256"]
    )
    assert (
        compilation["wire_then_default"]["intermediate_sha256"]
        == independent_wire["compiled_sha256"]
    )
    assert (
        compilation["default_then_wire"]["wire_edit"]["source_sha256"]
        == independent_default["compiled_sha256"]
    )
    assert (
        compilation["wire_then_default"]["default_edit"]["source_sha256"]
        == independent_wire["compiled_sha256"]
    )
    assert compilation["compiled_sha256"] == review["output_sha256"] == sha(output)
    assert compilation["profile"] == review["profile"] == PROFILE
    assert not any(
        review[k]
        for k in [
            "can_apply",
            "controller_write",
            "controller_queries",
            "field_transfer_enabled",
            "current_identity_verified",
        ]
    )
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert (
        seal({k: v for k, v in review.items() if k != "review_sha256"}) == review["review_sha256"]
    )
    if value == "3" and replacement == A:
        assert output == merged and output != files[3]
    if compressed:
        assert output[:10] == merged[:10]
    assert storage.load(snapshot["id"])[1] == files == original and not storage.receipts()


def test_selected_real_uses_saved_effective_value_without_remerging_over_the_edit(tmp_path):
    files = wire_files()
    files[11] += slot((2 << 22) | 12, 527, 3113, 4, len(files[12]))
    payload = struct.pack(">f", 88)
    files[12] += payload + bytes([header_crc(payload) ^ 255])
    _, service, snapshot = setup(tmp_path, files)
    body = proposal(service, snapshot, value="0.1")
    source = service.source(source_request(snapshot))
    field = next(row for row in source["fields"] if row["ref"] == C)
    assert field["archive_value"] == 3 and field["effective_value"] == 88
    output, review = service.preview(body)
    after = MoiIdentity(output)
    assert (
        after.reader.scalar(after.reader.records[C], 3113)
        == struct.unpack(">f", b"\x3d\xcc\xcc\xcd")[0]
    )
    assert review["compilation"]["selected_default"]["before_value"] == 88
    assert review["compilation"]["parameter_merge"]["matched_parameters"] == 4


@pytest.mark.parametrize(
    "field,value",
    [
        ("snapshot_sha256", "0" * 64),
        ("source_sha256", "1" * 64),
        ("effective_sha256", "2" * 64),
        ("record_sha256", "3" * 64),
        ("effective_record_sha256", "4" * 64),
        ("property_sha256", "5" * 64),
        ("encoded_sha256", "6" * 64),
        ("record_ref", A),
        ("source_ref", C),
        ("old", [1, 85, 2, 7000]),
        ("diagram_ref", "missing"),
        ("wire_index", 2),
        ("value_text", "NaN"),
        ("value_text", "1e-1000"),
        ("value_text", "3.5e38"),
        ("value_text", ""),
        ("value_text", True),
        ("wire_index", True),
        ("old", [False, 85, 2, 7000]),
        ("router", "127.0.0.1:47999"),
    ],
)
def test_original_source_tuple_type_and_numeric_faults_refuse(tmp_path, field, value):
    _, service, snapshot = setup(tmp_path)
    body = proposal(service, snapshot)
    with pytest.raises(ValueError):
        service.preview(body | {field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_ref", A),
        ("value_text", "2"),
        ("value_text", "0.10"),
        ("wire_index", 1),
        ("review_sha256", "0" * 64),
    ],
)
def test_valid_changed_proposals_cannot_reuse_the_previous_combined_review(tmp_path, field, value):
    _, service, snapshot = setup(tmp_path)
    body = proposal(service, snapshot)
    _, review = service.preview(body)
    with pytest.raises(ValueError):
        service.export(body | {"review_sha256": review["review_sha256"], field: value})


@pytest.mark.parametrize(
    "fault",
    [
        "unverified",
        "vendor",
        "device",
        "name",
        "model",
        "unknown-settings",
        "crc",
        "saved-identity",
    ],
)
def test_combined_source_keeps_both_existing_compiler_identity_and_merge_guards(tmp_path, fault):
    files = wire_files()
    metadata = {}
    if fault == "unverified":
        metadata["source_identity_matches"] = False
    elif fault == "device":
        metadata["device"] = "device,5137"
    elif fault in {"vendor", "name", "model"}:
        metadata["identity"] = IDENTITY | {
            {"vendor": "vendor-identifier", "name": "object-name", "model": "model-name"}[fault]: 99
            if fault == "vendor"
            else "Mismatch"
        }
    elif fault == "unknown-settings":
        files[11], files[12] = b"Unknown selectors", b"Opaque values"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    else:
        from .test_native_signal_compiler import inline

        files[11] += inline((8 << 22) | 5136, 470, 2390, "Another controller")
    _, service, snapshot = setup(tmp_path, files, **metadata)
    with pytest.raises(ValueError):
        service.source(source_request(snapshot))


@pytest.mark.parametrize("key", [3, 11, 12])
def test_retained_bytes_are_rechecked_before_all_operations(tmp_path, key):
    storage, service, snapshot = setup(tmp_path)
    body = proposal(service, snapshot)
    _, review = service.preview(body)
    (storage.directory / snapshot["id"] / f"file-{key}.bin").write_bytes(b"Changed source")
    for method, request in [
        (service.source, source_request(snapshot)),
        (service.preview, body),
        (service.export, body | {"review_sha256": review["review_sha256"]}),
    ]:
        with pytest.raises(ValueError):
            method(request)


def test_unavailable_candidate_is_discovered_from_actual_configuration(tmp_path):
    _, service, snapshot = setup(tmp_path, wire_files(config=True))
    body = proposal(service, snapshot)
    q = {
        k: body[k]
        for k in [
            "capture_id",
            "snapshot_sha256",
            "source_sha256",
            "effective_sha256",
            "diagram_ref",
            "record_sha256",
            "wire_index",
        ]
    }
    selection = service.selection(q)["selection"]
    assert [row["ref"] for row in selection["candidates"]] == [A]
    with pytest.raises(ValueError, match="configuration differs"):
        service.preview(body)


def test_source_keeps_actual_empty_diagram_unavailability(tmp_path):
    _, service, snapshot = setup(tmp_path, wire_files(empty=True))
    source = service.source(source_request(snapshot))
    assert source["diagrams"][0]["wire_count"] == 0
    assert not source["diagrams"][0]["available"] and source["fields"]


def test_composition_cannot_accept_an_edited_intermediate_as_a_new_saved_source(monkeypatch):
    compiler = EffectiveDefaultWireCompiler(wire_files())
    monkeypatch.setattr(compiler.wire, "merged", b"Different merged bytes")
    # Constructor qualification is independent of any future selection or model name.
    monkeypatch.setattr(
        "bms_tool.moi_default_wire.EffectiveWireCompiler", lambda files: compiler.wire
    )
    with pytest.raises(ValueError, match="identical saved merge"):
        EffectiveDefaultWireCompiler(wire_files())


def test_http_strict_closed_offline_and_exact_export(tmp_path):
    app = create_app(tmp_path)
    storage = app.state.native_applications.storage
    snapshot = retained(storage, wire_files(), identity=IDENTITY)
    service = NativeDefaultWire(NativeBackupRecords(storage))
    body = proposal(service, snapshot)
    with TestClient(app) as c:
        headers = {"X-Studio-Token": c.get("/api/session").json()["token"]}
        assert c.post(BASE + "/source", json=source_request(snapshot)).status_code == 403
        assert (
            c.post(BASE + "/source", json=source_request(snapshot), headers=headers).status_code
            == 200
        )
        assert (
            c.post(
                BASE + "/preview", json=body | {"device": "device,5136"}, headers=headers
            ).status_code
            == 422
        )
        response = c.post(BASE + "/preview", json=body, headers=headers)
        assert response.status_code == 200, response.text
        review = response.json()
        result = c.post(
            BASE + "/export",
            json=body | {"review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert result.status_code == 200, result.text
        assert (
            sha(result.content)
            == review["output_sha256"]
            == result.headers["X-Studio-Artifact-Sha256"]
        )
        assert result.headers["X-Studio-Snapshot-Sha256"] == snapshot["evidence_sha256"]
        assert result.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert not c.get("/api/session").json()["field_network_open"] and not storage.receipts()


async def test_actual_loopback_capture_compiles_offline_without_more_protocol_requests(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = wire_files()
    peer.metadata["object-name"] = IDENTITY["object-name"]
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-for-default-wire")
    snapshot, _ = native.storage.load(captured["id"])
    await bacnet.disconnect()
    before = list(seen)
    service = NativeDefaultWire(NativeBackupRecords(native.storage))
    body = proposal(service, snapshot)
    output, review = service.preview(body)
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert seen == before and not native.storage.receipts()
