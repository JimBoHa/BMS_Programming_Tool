"""An independent reader checks the wire-format root tables and original-record order."""

import pytest
from bacpypes3.primitivedata import Boolean, CharacterString, Real, Unsigned
from bms_tool.moi_application import _structs
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inline_monitor import compile_monitor
from bms_tool.native_inline_sequence_62 import LegacyInlineSequenceCompiler
from bms_tool.native_inputs import archive, encoded, raw_property

from .test_controller_application import native_record
from .test_native_inline_sequence import R, authored_source


def row(*values):
    return b"\x3e" + b"".join(encoded(v) for v in values) + b"\x3f"


def layout_source(model, *, missing_wire=False, misplaced=False, wrong_id=False):
    files = authored_source(model=model)
    source = MoiIdentity(files[3])
    graph = source.reader.diagram(R)
    blocks = len(graph["blocks"])
    wires = len(graph["connections"]) - int(missing_wire)
    layout = native_record(
        127,
        2 if wrong_id else 1,
        [
            (3383, b"".join(row(Real(i + 0.5), Real(-i), Unsigned(9)) for i in range(blocks))),
            (
                3384,
                b"".join(row(Boolean(True), CharacterString(f"route {i}")) for i in range(wires)),
            ),
            (6001, encoded(Unsigned(444))),
        ],
    )
    parts = [
        source.data[r["offset"] : r["end_offset"]] for r in source.records if r["class_id"] != 127
    ]
    parts.insert(len(parts) - int(misplaced), layout)
    return {**files, 3: archive(source, parts)}


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0"])
@pytest.mark.parametrize("mode", ["monitor", "shadow", "control"])
def test_62_download_keeps_complete_root_tables_and_originals(model, mode):
    fixture = layout_source(model)
    if mode == "monitor":
        output, report = compile_monitor(fixture, 300)
        historical, _ = compile_monitor(fixture, 300, preserve_root_layout=False)
        assert MoiIdentity(historical).records[-1]["class_id"] != 127
    else:
        donor = authored_source(model=model, catalog=True, wide=True)
        compiler = LegacyInlineSequenceCompiler(fixture, donor[3], 300)
        compiler.body()
        output, report = compiler.export(shadow=mode == "shadow")
    assert report["separate_root_layout_updated"]
    before, after = MoiIdentity(fixture[3]), MoiIdentity(output)
    before_graph, after_graph = before.reader.diagram(R), after.reader.diagram(R)
    old, new = before.records[-1], after.records[-1]
    assert new["class_id"] == old["class_id"] == 127
    assert raw_property(before, old, 6001) == raw_property(after, new, 6001)
    for pid, types, items in (
        (3383, (Real, Real, Unsigned), "blocks"),
        (3384, (Boolean, CharacterString), "connections"),
    ):
        rows = _structs(new["properties"][pid]["tags"], types)
        original = _structs(old["properties"][pid]["tags"], types)
        assert len(rows) == len(after_graph[items])
        assert rows[: len(original)] == original
        assert len(original) == len(before_graph[items])
        assert raw_property(after, new, pid).startswith(raw_property(before, old, pid)[:-1])
    assert len(before.records) + report.get("added_records", report.get("new_records")) == len(
        after.records
    )


@pytest.mark.parametrize("fault", ["missing_wire", "misplaced", "wrong_id"])
def test_malformed_separate_drawing_is_rejected_before_a_download(fault):
    source = layout_source("MS-VMA1630-0", **{fault: True})
    with pytest.raises(ValueError, match="root layout"):
        compile_monitor(source, 300)
