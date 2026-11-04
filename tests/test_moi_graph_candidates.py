"""Compare bitset witnesses with independently exercised native profile predicates."""

import random
import struct
from unittest.mock import patch

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.moi_connection_copies import MoiConnectionCopies
from bms_tool.moi_graph_candidates import GraphCandidates, eligible_connection, eligible_wire
from bms_tool.moi_wire_sources import MoiWireSources

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import authored, frames, packed, property_bytes
from .test_moi_wire_sources import REF, B, D, wide_source


def oracle_copy(editor):
    for diagram in editor.reader.summary()["diagrams"]:
        for index in range(diagram["connections"]):
            info = editor.inspect(diagram["ref"], index)
            if info["available"]:
                return {
                    "diagram_ref": diagram["ref"],
                    "wire_index": index,
                    "candidate_count": len(info["candidates"]) - 1,
                }
    return None


def oracle_connections(compiler):
    allowed = set()
    for diagram in compiler.wire.reader.summary()["diagrams"]:
        for index in range(diagram["connections"]):
            initial = compiler.inspect(diagram["ref"], index)
            for row in initial["sources"]:
                info = compiler.inspect(diagram["ref"], index, row["ref"])
                if info["available"]:
                    allowed.update(
                        (diagram["ref"], index, row["ref"], target["ref"])
                        for target in info["targets"]
                    )
    return allowed


@pytest.mark.parametrize("case", range(64))
def test_search_agrees_with_original_predicates_over_ports_configurations_order_and_cycles(case):
    rng = random.Random(13217 + case)
    inputs = [(i, p) for i in range(4) for p in (7000, 7001)]
    rng.shuffle(inputs)
    wires = [
        (rng.randrange(4), rng.choice((85, 86)), dst, port)
        for dst, port in inputs[: rng.randrange(9)]
    ]
    order = list(range(4))
    rng.shuffle(order)
    raw = authored(
        wires=wires, order=tuple(order), source_class=551, target_class=551, config=case % 3 == 0
    )
    editor = MoiWireSources(raw)
    expected = oracle_copy(editor)
    with patch.object(editor, "inspect", wraps=editor.inspect) as inspector:
        found, error = eligible_wire(editor)
        assert error is None and found == expected
        assert inspector.call_count <= 1
    compiler = MoiConnectionCopies(raw)
    expected = oracle_connections(compiler)
    with patch.object(compiler, "inspect", wraps=compiler.inspect) as inspector:
        found, error = eligible_connection(compiler)
        assert error is None and bool(found) == bool(expected)
        if found:
            assert (
                found["diagram_ref"],
                found["prototype_index"],
                found["source_ref"],
                found["target_ref"],
            ) in expected
        assert inspector.call_count <= 2


def test_alternate_observed_source_can_work_when_prototype_default_executes_too_late():
    raw = authored(wires=[(0, 85, 2, 7000), (1, 85, 2, 7001)], order=(1, 3, 0, 2))
    compiler = MoiConnectionCopies(raw)
    assert not compiler.inspect(REF)["available"]
    found, error = eligible_connection(compiler)
    assert error is None and found["prototype_index"] == 0
    assert found["source_ref"] == B and found["target_ref"] == D


def test_new_index_can_widen_while_legacy_replacement_keeps_recorded_width():
    raw = wide_source()
    copy = MoiWireSources(raw)
    assert eligible_wire(copy)[0] == oracle_copy(copy)
    compiler = MoiConnectionCopies(raw)
    found, error = eligible_connection(compiler)
    assert error is None
    assert (
        found["diagram_ref"],
        found["prototype_index"],
        found["source_ref"],
        found["target_ref"],
    ) in oracle_connections(compiler)


def test_dense_strongly_connected_graph_search_has_bounded_inspector_calls():
    # Different free target pins exist, but all members reach every source.
    wires = [(0, 85, 1, 7000), (1, 85, 2, 7000), (2, 85, 3, 7000), (3, 85, 0, 7000)]
    wires += [(i % 4, 85, (i + 1) % 4, 8000 + i) for i in range(1000)]
    raw = authored(wires=wires, source_class=551, target_class=551)
    compiler = MoiConnectionCopies(raw)
    with patch.object(compiler, "inspect", wraps=compiler.inspect) as inspector:
        found, error = eligible_connection(compiler)
        assert found is None and error is None and inspector.call_count == 1
    editor = MoiWireSources(raw)
    with patch.object(editor, "inspect", wraps=editor.inspect) as inspector:
        found, error = eligible_wire(editor)
        assert found is None and error is None and inspector.call_count == 0


@pytest.mark.parametrize("metadata", [b"", b"\x3e\x10\x3f"])
def test_unknown_continuation_refuses_addition_without_disabling_legacy_source_copy(metadata):
    raw = authored(metadata=metadata, wires=[(0, 85, 2, 7000), (1, 85, 3, 7000)])
    found, error = eligible_connection(MoiConnectionCopies(raw))
    assert found is None and error
    assert eligible_wire(MoiWireSources(raw))[0] == oracle_copy(MoiWireSources(raw))


def test_duplicate_inputs_and_existing_tag_budget_refuse_new_edge_witness():
    raw = authored(wires=[(0, 85, 2, 7000), (1, 85, 2, 7000)])
    found, error = eligible_connection(MoiConnectionCopies(raw))
    assert found is None and "ambiguous input ownership" in error
    raw = authored(wires=[(0, 85, 2, index) for index in range(3333)])
    found, error = eligible_connection(MoiConnectionCopies(raw))
    assert found is None and "tag budget" in error


def test_reachability_matches_direct_native_edges_for_all_members():
    raw = authored(wires=[(0, 85, 1, 7000), (1, 85, 2, 7000), (2, 85, 1, 7001)], target_class=551)
    editor = MoiWireSources(raw)
    graph, _, _, wires = editor.graph(REF)
    search = GraphCandidates(graph, wires, editor.signatures)
    assert search.ancestors == {0: 1, 1: 7, 2: 7, 3: 8}
    assert search.earlier == {0: 0, 1: 1, 2: 3, 3: 7}
    assert search.later == {0: 14, 1: 12, 2: 8, 3: 0}


def test_maximum_member_cycle_has_free_inputs_but_no_new_cycle_or_replacement_witness():
    count = 512
    objects = [
        native_record(
            470,
            5136,
            [
                (32527, encoded(CharacterString("controller"))),
                (75, encoded(ObjectIdentifier((8, 5136)))),
                (2390, encoded(CharacterString("Authored maximum member graph"))),
                (70, encoded(CharacterString("UNLISTED-MODEL"))),
            ],
        )
    ]
    wires = [(i, 85, (i + 1) % count, 7000 + i) for i in range(count)]
    objects.append(
        native_record(
            575,
            1,
            [
                (32527, encoded(CharacterString(REF))),
                (75, encoded(ObjectIdentifier((575, 1)))),
                (3375, b"".join(encoded(ObjectIdentifier((2, 10 + i))) for i in range(count))),
                (3117, b"".join(encoded(Unsigned(i)) for i in range(count))),
                (
                    3118,
                    b"".join(
                        b"\x3e" + b"".join(encoded(Unsigned(v)) for v in row) + b"\x3f"
                        for row in wires
                    ),
                ),
            ],
        )
    )
    for i in range(count):
        objects.append(
            native_record(
                551,
                10 + i,
                [
                    (32527, encoded(CharacterString(f"{REF}.2_{10 + i}"))),
                    (75, encoded(ObjectIdentifier((2, 10 + i)))),
                    (3113, encoded(Real(1))),
                ],
            )
        )
    raw = struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, len(objects)) + b"".join(
        struct.pack("<H", len(row) + 2) + row for row in objects
    )
    compiler = MoiConnectionCopies(raw)
    with patch.object(compiler, "inspect", wraps=compiler.inspect) as inspector:
        assert eligible_connection(compiler) == (None, None)
        assert inspector.call_count == 1
    editor = MoiWireSources(raw)
    with patch.object(editor, "inspect", wraps=editor.inspect) as inspector:
        assert eligible_wire(editor) == (None, None)
        assert inspector.call_count == 0


@pytest.mark.parametrize("length", [508, 521])
def test_excessive_references_fail_existing_reader_admission_before_candidate_search(length):
    raw = authored(compressed=False)
    original = MoiConnectionCopies(raw)
    name = "controller/" + "x" * (length - len("controller/"))
    replacements = {}
    for ref, record in original.wire.reader.records.items():
        if ref.startswith(REF):
            old = property_bytes(32527, encoded(CharacterString(ref)))
            new = property_bytes(32527, encoded(CharacterString(name + ref[len(REF) :])))
            replacements[record["offset"]] = (old, new)
    records = []
    for (width, body), record in zip(frames(raw), original.editor.records, strict=True):
        if record["offset"] in replacements:
            old, new = replacements[record["offset"]]
            assert body.count(old) == 1
            body = body.replace(old, new, 1)
        records.append((width, body))
    with pytest.raises(ValueError, match="unambiguous complete native records"):
        MoiConnectionCopies(packed(raw[:14], records))
