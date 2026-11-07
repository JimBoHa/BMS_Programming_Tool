"""Literal order bytes and actual saved settings; authored data only."""

import itertools
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_execution_order import MoiExecutionOrder
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_execution_order import NativeExecutionOrder
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_wire_sources import REF, A, B, source
from .test_native_signal_compiler import inline, retained
from .test_native_wire_compiler import BOOLEAN, wire_files

BASE = "/api/bacnet/controller/native-application/inspection/execution-order"
IDENTITY = {
    "object-name": "Authored native wire controller",
    "vendor-identifier": 5,
    "model-name": "UNLISTED-MODEL",
}


def setup(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage, files or wire_files(), **{"identity": IDENTITY, **metadata})
    service = NativeExecutionOrder(NativeBackupRecords(storage))
    _, files = storage.load(snapshot["id"])
    q = dict(
        capture_id=snapshot["id"],
        snapshot_sha256=snapshot["evidence_sha256"],
        source_sha256=sha(files[3]),
        diagram_ref=REF,
        record_sha256=MoiIdentity(files[3]).reader.records[REF]["sha256"],
    )
    return storage, service, snapshot, q


def proposal(service, q, proposed=None):
    info = service.source(q)
    return {
        **q,
        "effective_sha256": info["effective_sha256"],
        "effective_record_sha256": info["selection"]["record_sha256"],
        "selection_sha256": info["selection"]["selection_sha256"],
        "proposed_order": proposed if proposed is not None else [1, 0, 2, 3],
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("positions", [False, True])
def test_literal_saved_merge_then_only_order_atoms_change(
    tmp_path, compressed, extended, diagram_class, positions
):
    files = wire_files(
        compressed=compressed, extended=extended, diagram_class=diagram_class, positions=positions
    )
    original = dict(files)
    storage, service, snapshot, q = setup(tmp_path, files)
    request = proposal(service, q)
    output, reviewed = service.preview(request)
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    before, after = MoiIdentity(merged), MoiIdentity(output)
    old = b"".join(encoded(Unsigned(x)) for x in (0, 1, 2, 3)) + b"\x2f"
    new = b"".join(encoded(Unsigned(x)) for x in (1, 0, 2, 3)) + b"\x2f"
    assert before.data.count(old) == 1
    assert after.data == before.data.replace(old, new, 1)
    assert after.reader.diagram(REF) == {
        **before.reader.diagram(REF),
        "execution_order": [1, 0, 2, 3],
    }
    assert after.reader.scalar(after.reader.records[A], 3113) == 42
    assert after.reader.scalar(after.reader.records[B], 3113) == 17
    assert after.reader.scalar(after.reader.records[BOOLEAN], 3113) is True
    compilation = reviewed["compilation"]
    assert compilation["compiled_sha256"] == sha(output)
    assert compilation["compiled_native_sha256"] == sha(after.data)
    assert compilation["compilation_sha256"] == seal(
        {k: v for k, v in compilation.items() if k != "compilation_sha256"}
    )
    assert reviewed["review_sha256"] == seal(
        {k: v for k, v in reviewed.items() if k != "review_sha256"}
    )
    assert service.export({**request, "review_sha256": reviewed["review_sha256"]}) == (
        output,
        reviewed,
    )
    assert storage.load(snapshot["id"])[1] == original and not storage.receipts()
    if compressed:
        assert output[:10] == merged[:10]


@pytest.mark.parametrize("order", list(itertools.permutations(range(4))))
def test_all_permutations_have_independent_wire_phase_oracles(order):
    editor = MoiExecutionOrder(source(compressed=False))
    selected = editor.inspect(REF)
    allowed = order.index(0) < order.index(2) and order.index(1) < order.index(3)
    args = dict(
        diagram_ref=REF, selection_sha256=selected["selection_sha256"], proposed_order=list(order)
    )
    if not allowed:
        with pytest.raises(ValueError, match="execution relationship"):
            editor.compile(**args)
        return
    output, report = editor.compile(**args)
    old = b"".join(encoded(Unsigned(x)) for x in (0, 1, 2, 3)) + b"\x2f"
    new = b"".join(encoded(Unsigned(x)) for x in order) + b"\x2f"
    assert output == editor.editor.data.replace(old, new, 1)
    assert len(report["patches"]) == sum(x != y for x, y in enumerate(order))


@pytest.mark.parametrize(
    "wires", [[(2, 85, 0, 7000)], [(2, 85, 0, 7000), (0, 85, 2, 7000)], [(0, 85, 0, 7000)], []]
)
def test_existing_backward_feedback_self_and_empty_connections_remain_exact(wires):
    editor = MoiExecutionOrder(source(wires=wires))
    s = editor.inspect(REF)
    output, _ = editor.compile(
        diagram_ref=REF, selection_sha256=s["selection_sha256"], proposed_order=[1, 0, 2, 3]
    )
    assert (
        MoiIdentity(output).reader.diagram(REF)["connections"]
        == editor.reader.diagram(REF)["connections"]
    )
    if wires and wires[0][0] == 2:
        with pytest.raises(ValueError, match="execution relationship"):
            editor.compile(
                diagram_ref=REF, selection_sha256=s["selection_sha256"], proposed_order=[2, 1, 0, 3]
            )


def many_source(count, width=None):
    root = native_record(
        470,
        5136,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier(("device", 5136)))),
            (2390, encoded(CharacterString(IDENTITY["object-name"]))),
            (70, encoded(CharacterString("UNLISTED-MODEL"))),
        ],
    )
    graph = native_record(
        575,
        1,
        [
            (32527, encoded(CharacterString(REF))),
            (75, encoded(ObjectIdentifier((575, 1)))),
            (3375, b"".join(encoded(ObjectIdentifier((2, i + 10))) for i in range(count))),
            (
                3117,
                b"".join(
                    encoded(Unsigned(i))
                    if width is None
                    else bytes([0x20 | width]) + i.to_bytes(width, "big")
                    for i in range(count)
                ),
            ),
            (3118, b""),
        ],
    )
    members = [
        native_record(
            551,
            i + 10,
            [
                (32527, encoded(CharacterString(f"{REF}.2_{i + 10}"))),
                (75, encoded(ObjectIdentifier((2, i + 10)))),
                (2390, encoded(CharacterString(f"Member {i}"))),
            ],
        )
        for i in range(count)
    ]
    parts = [b"\0\0" + struct.pack("<I", len(r) + 6) + r for r in [root, graph, *members]]
    return struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(parts)) + b"".join(parts)


@pytest.mark.parametrize("count", [1, 256, 257, 512])
def test_original_unsigned_widths_are_kept_at_boundaries(count):
    editor = MoiExecutionOrder(many_source(count))
    s = editor.inspect(REF)
    proposed = list(range(count))
    if count > 1:
        proposed[0], proposed[1] = proposed[1], proposed[0]
    output, _ = editor.compile(
        diagram_ref=REF, selection_sha256=s["selection_sha256"], proposed_order=proposed
    )
    assert MoiIdentity(output).reader.diagram(REF)["execution_order"] == proposed
    if count > 256:
        proposed = list(range(count))
        proposed[0], proposed[256] = proposed[256], proposed[0]
        with pytest.raises(ValueError, match="Unsigned payload width"):
            editor.compile(
                diagram_ref=REF, selection_sha256=s["selection_sha256"], proposed_order=proposed
            )


@pytest.mark.parametrize("count", [0, 513])
def test_outside_member_profile_refuses(count):
    with pytest.raises(ValueError):
        MoiExecutionOrder(many_source(count)).inspect(REF)


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_recorded_nonminimal_unsigned_widths_remain_literal(width):
    raw = many_source(4, width=width)
    editor = MoiExecutionOrder(raw)
    selection = editor.inspect(REF)
    output, _ = editor.compile(
        diagram_ref=REF, selection_sha256=selection["selection_sha256"], proposed_order=[1, 0, 2, 3]
    )
    old = b"".join(bytes([0x20 | width]) + i.to_bytes(width, "big") for i in [0, 1, 2, 3]) + b"\x2f"
    new = b"".join(bytes([0x20 | width]) + i.to_bytes(width, "big") for i in [1, 0, 2, 3]) + b"\x2f"
    assert raw.count(old) == 1 and output == raw.replace(old, new, 1)
    assert all(row["payload_bytes"] == width for row in selection["slots"])


def test_vendor_identity_must_retain_its_original_integer_type(tmp_path):
    _, service, _, query = setup(tmp_path, identity={**IDENTITY, "vendor-identifier": 5.0})
    with pytest.raises(ValueError, match="typed vendor"):
        service.source(query)


@pytest.mark.parametrize("compressed", [False, True])
def test_no_op_is_exact_merged_source_and_never_discards_saved_values(tmp_path, compressed):
    files = wire_files(compressed=compressed)
    _, service, _, q = setup(tmp_path, files)
    output, report = service.preview(proposal(service, q, [0, 1, 2, 3]))
    merged, _ = ParameterApplication(files[3], files[11], files[12]).compile()
    assert output == merged and output != files[3]
    assert report["compilation"]["order_edit"]["patches"] == []
    editor = MoiExecutionOrder(output)
    s = editor.inspect(REF)
    assert (
        editor.compile(
            diagram_ref=REF, selection_sha256=s["selection_sha256"], proposed_order=[0, 1, 2, 3]
        )[0]
        == output
    )


@pytest.mark.parametrize(
    "fault",
    [
        "unknown",
        "crc",
        "name",
        "reference",
        "unverified",
        "vendor",
        "device",
        "original_hash",
        "record_hash",
        "effective_hash",
        "effective_record",
        "selection",
        "duplicate",
        "missing",
        "range",
        "bool",
        "float",
        "string",
        "extra",
    ],
)
def test_unknown_saved_sources_identity_and_stale_or_malformed_requests_refuse(tmp_path, fault):
    files = wire_files()
    metadata = {}
    if fault == "unknown":
        files[11], files[12] = b"Unknown directory", b"Opaque values"
    if fault == "crc":
        files[12] = files[12][:-1] + bytes([files[12][-1] ^ 1])
    if fault == "name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Different controller")
    if fault == "reference":
        files[11] += inline((551 << 22) | 10, 551, 32527, "controller/unknown")
    if fault == "unverified":
        metadata["source_identity_matches"] = False
    if fault == "vendor":
        metadata["identity"] = {**IDENTITY, "vendor-identifier": 999}
    if fault == "device":
        metadata["device"] = "device,99"
    _, service, _, q = setup(tmp_path, files, **metadata)
    if fault in ["unknown", "crc", "name", "reference", "unverified", "vendor", "device"]:
        with pytest.raises(ValueError):
            service.source(q)
        return
    request = proposal(service, q)
    updates = {
        "original_hash": {"source_sha256": "0" * 64},
        "record_hash": {"record_sha256": "0" * 64},
        "effective_hash": {"effective_sha256": "0" * 64},
        "effective_record": {"effective_record_sha256": "0" * 64},
        "selection": {"selection_sha256": "0" * 64},
        "duplicate": {"proposed_order": [0, 0, 2, 3]},
        "missing": {"proposed_order": [0, 1, 2]},
        "range": {"proposed_order": [0, 1, 2, 4]},
        "bool": {"proposed_order": [True, 0, 2, 3]},
        "float": {"proposed_order": [1.0, 0, 2, 3]},
        "string": {"proposed_order": ["1", 0, 2, 3]},
        "extra": {"transfer": True},
    }
    with pytest.raises(ValueError):
        service.preview({**request, **updates[fault]})


def test_strict_http_export_proofs_and_no_field_or_intent_work(tmp_path, monkeypatch):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local order compilation attempted a field operation")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    storage, service, snapshot, q = setup(tmp_path)
    request = proposal(service, q)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE + "/source", json=q).status_code == 403
        assert client.post(BASE + "/source", headers=headers, json=q).json() == service.source(q)
        reply = client.post(BASE + "/preview", headers=headers, json=request)
        assert reply.status_code == 200
        review = reply.json()
        export_body = {**request, "review_sha256": review["review_sha256"]}
        assert client.post(BASE + "/export", json=export_body).status_code == 403
        result = client.post(BASE + "/export", headers=headers, json=export_body)
        assert result.status_code == 200
        assert (
            sha(result.content)
            == result.headers["X-Studio-Artifact-Sha256"]
            == review["output_sha256"]
        )
        assert result.headers["X-Studio-Source-Sha256"] == q["source_sha256"]
        assert result.headers["X-Studio-Snapshot-Sha256"] == q["snapshot_sha256"]
        assert result.headers["X-Studio-Review-Sha256"] == review["review_sha256"]
        assert (
            result.headers["X-Studio-Compilation-Sha256"]
            == review["compilation"]["compilation_sha256"]
        )
        assert (
            client.post(
                BASE + "/export", headers=headers, json={**export_body, "review_sha256": "0" * 64}
            ).status_code
            == 422
        )
        assert client.get("/api/session").json()["field_network_open"] is False
    assert not storage.receipts() and storage.load(snapshot["id"])[1] == wire_files()
