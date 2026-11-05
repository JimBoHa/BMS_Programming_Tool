"""Literal append oracle and fresh configuration guards, without field services."""

import copy
import struct

import pytest
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_connection_transfer import compile_connection, verify_connection_preservation

from .test_moi_connection_copies import ADDED, WIRE, frames, packed
from .test_moi_wire_sources import REF, A
from .test_native_connection_compiler import META, connection_files, proposal, setup
from .test_native_connection_copies import filesystem
from .test_native_default_transfer import real_slot


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("metadata", [False, True])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("metadata_first", [False, True])
def test_fresh_merge_then_literal_append_preserves_every_other_expanded_byte(
    tmp_path, compressed, extended, metadata, diagram_class, metadata_first
):
    files = connection_files(
        compressed=compressed,
        extended=extended,
        metadata=metadata,
        diagram_class=diagram_class,
        metadata_first=metadata_first,
    )
    storage, service, _, query = setup(tmp_path, files)
    body = proposal(service, query)
    before = filesystem(storage.directory)
    _, reviewed = compile_connection(files, body)
    fresh = dict(files)
    real_slot(fresh, 0, struct.pack(">f", 77))
    output, compilation = compile_connection(
        fresh, body, fresh=True, expected_guard=reviewed["connection_guard"]
    )
    merged, _ = ParameterApplication(fresh[3], fresh[11], fresh[12]).compile()
    original = MoiIdentity(merged)
    expected = []
    for width, raw in frames(original.data):
        if int.from_bytes(raw[:2], "little") == diagram_class:
            assert raw.count(WIRE + b"\x2f") == 1
            raw = raw.replace(WIRE + b"\x2f", WIRE + ADDED + b"\x2f", 1)
            if metadata:
                assert raw.count(META + b"\x2f") == 1
                raw = raw.replace(META + b"\x2f", META + META + b"\x2f", 1)
        expected.append((width, raw))
    actual = MoiIdentity(output)
    assert actual.data == packed(original.data[:14], expected)
    assert actual.reader.scalar(actual.reader.records[A], 3113) == 77
    assert compilation["connection_guard"] == reviewed["connection_guard"]
    assert compilation["connection_edit"]["new"] == [0, 85, 3, 7000]
    assert compilation["parameter_transfer_qualification"]["qualified_fields"] == 0
    assert compilation["native_record_count"] == len(original.records) == len(actual.records)
    proof = verify_connection_preservation(
        fresh, {**fresh, 3: output}, body, compilation["connection_guard"]
    )
    assert (
        proof["identity_unchanged"]
        and proof["selected_connection"]["effective_connection_verified"]
    )
    assert filesystem(storage.directory) == before and storage.load(query["capture_id"])[1] == files
    assert not storage.receipts()


@pytest.mark.parametrize(
    "key,value",
    [
        ("configuration_sha256", "f" * 64),
        ("profile", "future/2"),
        ("connection_count", 2),
        ("prototype_index", 1),
        ("prototype_old", [1, 85, 2, 7000]),
        ("source_ref", "controller/another-source"),
        ("target_ref", A),
        ("property_sha256", "f" * 64),
        ("metadata_property_sha256", None),
    ],
)
def test_guard_mutation_or_future_profile_refuses_fresh_compile_without_storage_changes(
    tmp_path, key, value
):
    storage, service, files, query = setup(tmp_path)
    body = proposal(service, query)
    _, report = compile_connection(files, body)
    before = filesystem(storage.directory)
    changed = copy.deepcopy(report["connection_guard"])
    changed[key] = value
    with pytest.raises(ValueError):
        compile_connection(files, body, fresh=True, expected_guard=changed)
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_fresh_compile_requires_review_guard_and_preview_still_requires_effective_hash(tmp_path):
    storage, service, files, query = setup(tmp_path)
    body = proposal(service, query)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="reviewed configuration guard"):
        compile_connection(files, body, fresh=True)
    with pytest.raises(ValueError, match="archive changed"):
        compile_connection(files, body | {"effective_sha256": "f" * 64})
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_preservation_requires_full_snapshot_and_rejects_other_saved_value_changes(tmp_path):
    _, service, files, query = setup(tmp_path)
    body = proposal(service, query)
    output, report = compile_connection(files, body)
    guard = report["connection_guard"]
    with pytest.raises(ValueError, match="complete native readback"):
        verify_connection_preservation(files, {3: output}, body, guard)
    changed = {**files, 3: output}
    real_slot(changed, 0, struct.pack(">f", 99))
    with pytest.raises(ValueError, match="saved parameter differs"):
        verify_connection_preservation(files, changed, body, guard)
    assert len(MoiIdentity(output).reader.diagram(REF)["connections"]) == 2
