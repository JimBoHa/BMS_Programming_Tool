"""Literal mixed native defaults qualify local composition, not deployment."""

import copy
import gzip
import struct
import types

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real
from bms_tool.app import create_app
from bms_tool.moi_default_batch import PROFILE, EffectiveDefaultBatchCompiler
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_default_batch import NativeDefaultBatch
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_enum_defaults import REF as ENUM
from .test_moi_enum_defaults import enum_source
from .test_moi_wire_sources import C, D
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import BOOLEAN, setup, wire_files

BASE = "/api/bacnet/controller/native-application/inspection/default-batch"
SAVED_ENUM = "controller/saved-enum"


def batch_files(*, compressed=True, extended=False, width=1, padding=0, extra=0):
    files = wire_files(compressed=False, extended=extended)
    data = bytearray(files[3])
    enum = MoiIdentity(enum_source(width=width, padding=padding, compressed=False))
    record = enum.reader.records[ENUM]
    additions = [enum.data[record["offset"] : record["end_offset"]]]
    additions.append(
        native_record(
            529,
            2,
            [
                (32527, encoded(CharacterString(SAVED_ENUM))),
                (75, encoded(ObjectIdentifier((529, 2)))),
                (3113, encoded(Enumerated(255))),
                (931, encoded(Enumerated(0x123))),
                (65001, bytes.fromhex("4e21034f")),
            ],
        )
    )
    for index in range(100, 100 + extra):
        additions.append(
            native_record(
                526,
                index,
                [
                    (32527, encoded(CharacterString(f"controller/batch-extra-{index}"))),
                    (75, encoded(ObjectIdentifier((2, index)))),
                    (3113, encoded(Real(3.5))),
                ],
            )
        )
    data[10:14] = (int.from_bytes(data[10:14], "little") + len(additions)).to_bytes(4, "little")
    for raw in additions:
        data.extend(
            b"\x00\x00" + struct.pack("<I", len(raw) + 6)
            if extended or len(raw) + 2 > 65535
            else struct.pack("<H", len(raw) + 2)
        )
        data.extend(raw)
    for oid, cid, kind, payload in [
        ((2 << 22) | 12, 527, 4, struct.pack(">f", 3.5)),
        ((19 << 22) | 2, 529, 9, (513).to_bytes(2, "big")),
    ]:
        files[11] += slot(oid, cid, 3113, kind, len(files[12]))
        files[12] += payload + bytes([header_crc(payload) ^ 255])
    files[3] = gzip.compress(data, mtime=123) if compressed else bytes(data)
    return files


def local(tmp_path, files=None, **metadata):
    storage, _, snapshot = setup(tmp_path, files or batch_files(), **metadata)
    service = NativeDefaultBatch(NativeBackupRecords(storage))
    query = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    opened = service.source(query)
    return storage, service, snapshot, query, opened


def changes(opened, *, noop=False):
    proposed = {C: "0.1", D: "-0", BOOLEAN: False, ENUM: 4294967295, SAVED_ENUM: 65535}
    result = []
    for row in opened["fields"]:
        field, kind = row["field"], row["kind"]
        value = field["effective_value"] if noop else proposed.get(field["ref"], "1")
        result.append(
            {
                "kind": kind,
                "record_ref": field["ref"],
                "encoded_sha256": field["encoded_sha256"],
                **({"value_text": str(value)} if kind == "real" else {"value": value}),
            }
        )
    return result


def request(query, opened, edits=None):
    return {
        **query,
        "source_sha256": opened["source_sha256"],
        "effective_sha256": opened["effective_sha256"],
        "changes": changes(opened) if edits is None else edits,
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("width", [1, 2, 3, 4])
@pytest.mark.parametrize("reverse", [False, True])
def test_literal_mixed_defaults_and_every_unselected_byte_survive_both_orders(
    tmp_path, compressed, extended, width, reverse
):
    files = batch_files(compressed=compressed, extended=extended, width=width)
    original = copy.deepcopy(files)
    storage, service, _, query, opened = local(tmp_path, files)
    edits = changes(opened)
    if reverse:
        edits.reverse()
    body = request(query, opened, edits)
    output, review = service.preview(body)
    c = review["compilation"]
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(output)
    expected_values = {
        C: b"\x44" + bytes.fromhex("3dcccccd") + b"\x2f",
        D: b"\x44" + bytes.fromhex("80000000") + b"\x2f",
        BOOLEAN: b"\x10\x2f",
        ENUM: b"\x94\xff\xff\xff\xff\x2f",
        SAVED_ENUM: b"\x92\xff\xff\x2f",
    }
    assert len(c["selected"]) == c["edit_count"] == c["changed_count"] == 5
    previous_before = previous_after = 14
    for old, new in zip(before.records, after.records, strict=True):
        ref = before.reader.scalar(old, 32527)
        raw_before = before.data[old["offset"] : old["end_offset"]]
        raw_after = after.data[new["offset"] : new["end_offset"]]
        if ref in expected_values:
            prop = old["properties"][3113]
            a, b = (
                prop["value_start_offset"] - old["offset"],
                prop["value_end_offset"] - old["offset"],
            )
            assert raw_after == raw_before[:a] + expected_values[ref] + raw_before[b:]
        else:
            assert raw_after == raw_before
            assert (
                before.data[previous_before : old["offset"]]
                == after.data[previous_after : new["offset"]]
            )
        previous_before, previous_after = old["end_offset"], new["end_offset"]
    assert after.data[:14] == before.data[:14]
    assert list(after.reader.records) == list(before.reader.records)
    assert c["both_orders_identical"] and c["other_merged_bytes_preserved"]
    assert c["compiled_native_sha256"] == sha(after.data) and c["compiled_sha256"] == sha(output)
    assert c["forward"][-1]["edit"]["output_sha256"] == sha(output)
    assert c["reverse"][-1]["edit"]["output_sha256"] == sha(output)
    assert [r["record_ref"] for r in c["reverse"]] == [r["record_ref"] for r in reversed(edits)]
    assert c["profile"] == review["profile"] == PROFILE
    assert c["parameter_merge"] == opened["parameter_merge"]
    assert {r["kind"] for r in c["independent"]} == {"real", "boolean", "enum"}
    assert service.export(body | {"review_sha256": review["review_sha256"]}) == (output, review)
    assert not any(
        review[k]
        for k in [
            "controller_queries",
            "controller_write",
            "can_apply",
            "field_transfer_enabled",
            "current_identity_verified",
        ]
    )
    assert not c["enum_semantics_verified"] and files == original
    assert storage.load(query["capture_id"])[1] == original and not storage.receipts()
    if compressed:
        assert output[:10] == merged[:10]


@pytest.mark.parametrize("compressed", [False, True])
def test_all_noops_preserve_the_exact_saved_merge_not_the_unmerged_archive(tmp_path, compressed):
    files = batch_files(compressed=compressed)
    _, service, _, query, opened = local(tmp_path, files)
    output, review = service.preview(request(query, opened, changes(opened, noop=True)))
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    assert output == merged and output != files[3]
    assert review["compilation"]["changed_count"] == 0


def test_enum_growth_promotes_only_its_own_record_frame(tmp_path):
    empty = MoiIdentity(enum_source(compressed=False))
    record = empty.reader.records[ENUM]
    padding = 65533 - (record["end_offset"] - record["offset"]) - 3
    files = batch_files(compressed=False, padding=padding)
    _, service, _, query, opened = local(tmp_path, files)
    output, _ = service.preview(request(query, opened))
    before, after = MoiIdentity(files[3]), MoiIdentity(output)
    old, new = before.reader.records[ENUM], after.reader.records[ENUM]
    assert before.data[old["offset"] - 2 : old["offset"]] == b"\xff\xff"
    assert after.data[new["offset"] - 6 : new["offset"]][:2] == b"\x00\x00"
    assert after.reader.scalar(new, 3113) == 4294967295


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate",
        "kind",
        "encoding",
        "source",
        "merge",
        "real-nan",
        "real-underflow",
        "enum-capacity",
        "enum-boolean",
        "boolean-integer",
        "extra",
    ],
)
def test_invalid_mixed_batch_refuses_atomically_without_mutating_any_source(tmp_path, fault):
    storage, service, _, query, opened = local(tmp_path)
    before = storage.load(query["capture_id"])
    body = request(query, opened)
    if fault == "duplicate":
        body["changes"].append(copy.deepcopy(body["changes"][0]))
    elif fault == "kind":
        body["changes"][0]["kind"] = "enum"
    elif fault == "encoding":
        body["changes"][-1]["encoded_sha256"] = "0" * 64
    elif fault in ("source", "merge"):
        body["source_sha256" if fault == "source" else "effective_sha256"] = "0" * 64
    elif fault.startswith("real-"):
        body["changes"][0]["value_text"] = "NaN" if fault == "real-nan" else "1e-999"
    elif fault == "enum-capacity":
        next(r for r in body["changes"] if r["record_ref"] == SAVED_ENUM)["value"] = 65536
    elif fault == "enum-boolean":
        next(r for r in body["changes"] if r["kind"] == "enum")["value"] = True
    elif fault == "boolean-integer":
        next(r for r in body["changes"] if r["kind"] == "boolean")["value"] = 1
    else:
        body["changes"][-1]["token"] = "forbidden"
    with pytest.raises(ValueError):
        service.preview(body)
    assert storage.load(query["capture_id"]) == before and not storage.receipts()


def test_sixteen_actual_distinct_fields_compile_but_seventeen_are_refused(tmp_path):
    _, service, _, query, opened = local(tmp_path, batch_files(extra=12))
    edits = changes(opened)
    assert len(edits) == 17
    output, review = service.preview(request(query, opened, edits[:16]))
    assert review["compilation"]["edit_count"] == 16 and output
    with pytest.raises(ValueError):
        service.preview(request(query, opened, edits))


def test_http_token_exact_review_export_and_closed_transfer_authority(tmp_path):
    _, _, _, query, opened = local(tmp_path)
    body = request(query, opened)
    with TestClient(create_app(tmp_path)) as client:
        assert client.post(BASE + "/source", json=query).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        review = client.post(BASE + "/preview", json=body, headers=headers)
        assert review.status_code == 200
        data = review.json()
        response = client.post(
            BASE + "/export", json=body | {"review_sha256": data["review_sha256"]}, headers=headers
        )
        assert response.status_code == 200 and sha(response.content) == data["output_sha256"]
        assert response.headers["X-Studio-Review-Sha256"] == data["review_sha256"]
        assert (
            client.post(
                BASE + "/preview", json=body | {"can_apply": True}, headers=headers
            ).status_code
            == 422
        )
        assert (
            client.post(
                BASE + "/export", json=body | {"review_sha256": "0" * 64}, headers=headers
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]


async def test_disconnected_captured_batch_has_no_additional_peer_requests_or_receipts(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = batch_files()
    peer.metadata["object-name"] = "Authored native wire controller"
    calls = []
    original = peer.indication

    async def watch(self, apdu):
        calls.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    capture = await native.capture(**target, operation_id="capture-batch-source")
    snapshot, files = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = list(calls)
    service = NativeDefaultBatch(NativeBackupRecords(native.storage))
    query = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    opened = service.source(query)
    output, review = service.preview(request(query, opened))
    assert output and review["compilation"]["edit_count"] == 5
    assert calls == before and not native.storage.receipts()
    assert native.storage.load(snapshot["id"])[1] == files


@pytest.mark.parametrize("fault", ["report", "opaque"])
def test_contradictory_independent_compilation_is_not_used_as_a_witness(
    tmp_path, monkeypatch, fault
):
    from bms_tool.native_signal_compiler import EffectiveSignalCompiler

    storage, service, _, query, opened = local(tmp_path, batch_files(compressed=False))
    before = storage.load(query["capture_id"])
    original = EffectiveSignalCompiler.compile

    def inconsistent(self, **kwargs):
        output, report = original(self, **kwargs)
        if fault == "report":
            report["compiled_sha256"] = "0" * 64
        else:
            assert b"Opaque metadata retained" in output
            output = output.replace(b"Opaque metadata retained", b"Opaque metadata retainez")
            report["compiled_sha256"] = sha(output)
            report["compiled_native_sha256"] = sha(MoiIdentity(output).data)
        return output, report

    monkeypatch.setattr(EffectiveSignalCompiler, "compile", inconsistent)
    with pytest.raises(ValueError, match="independent typed compilation"):
        service.preview(request(query, opened))
    assert storage.load(query["capture_id"]) == before and not storage.receipts()


def test_both_composition_orders_matching_does_not_excuse_unselected_byte_changes(
    tmp_path, monkeypatch
):
    _, service, _, query, opened = local(tmp_path, batch_files(compressed=False))
    original = EffectiveDefaultBatchCompiler._compose

    def inconsistent(self, changes):
        output, steps = original(self, changes)
        return output.replace(b"Opaque metadata retained", b"Opaque metadata retainez"), steps

    monkeypatch.setattr(EffectiveDefaultBatchCompiler, "_compose", inconsistent)
    with pytest.raises(ValueError, match="literal byte"):
        service.preview(request(query, opened))


@pytest.mark.parametrize("fault", ["saved-layout", "crc", "identity", "vendor", "unverified"])
def test_saved_source_or_identity_faults_withhold_batch_compilation(tmp_path, fault):
    files = batch_files()
    metadata = {}
    if fault == "saved-layout":
        files[11] = b"Authored unknown saved directory"
    elif fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    elif fault in ("identity", "vendor"):
        metadata["identity"] = {
            "object-name": "Different name"
            if fault == "identity"
            else "Authored native wire controller",
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 99 if fault == "vendor" else 5,
        }
    else:
        metadata["source_identity_matches"] = False
    storage, _, snapshot = setup(tmp_path, files, **metadata)
    service = NativeDefaultBatch(NativeBackupRecords(storage))
    before = storage.load(snapshot["id"])
    with pytest.raises(ValueError):
        service.source(
            {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
        )
    assert storage.load(snapshot["id"]) == before and not storage.receipts()
