"""Declared output-only records retain bytes without concealing input occupancy."""

import gzip
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.moi_terminal_copies import MoiTerminalCopies

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed
from .test_moi_terminal_copies import authored, literal_move, proposal


def with_output(files, *, cid=241, label="CO OUT4", slot=1, oid=None, ref=None, extra=()):
    app = MoiIdentity(files[3])
    kind = 4 if cid == 239 else 1
    oid = oid or (kind, 501)
    props = [
        (32527, encoded(CharacterString(ref or f"controller/{kind}_501"))),
        (75, encoded(ObjectIdentifier(oid))),
        (31, encoded(CharacterString(label))),
        (519, slot if isinstance(slot, bytes) else encoded(Unsigned(slot))),
        (65000, b"\x4e\x21\x03\x4f"),
        *extra,
    ]
    output = native_record(cid, 501, props)
    header = bytearray(app.data[:14])
    struct.pack_into("<I", header, 10, len(app.records) + 1)
    raw = packed(bytes(header), frames(app.data) + [(6, output)])
    return {**files, 3: gzip.compress(raw, mtime=12345) if app.compressed else raw}


@pytest.mark.parametrize("cid,label", [(241, "CO OUT4"), (241, "AO OUT1"), (239, "BO OUT1")])
@pytest.mark.parametrize("slot", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("compressed", [False, True])
def test_explicit_version_two_preserves_complete_outputs_and_a_separate_terminal_namespace(
    cid, label, slot, compressed
):
    files = with_output(authored(compressed=compressed), cid=cid, label=label, slot=slot)
    with pytest.raises(ValueError):
        MoiTerminalCopies(files[3])
    compiler = MoiTerminalCopies(files[3], output_namespace=True)
    assert compiler.inspect()["profile"] == "tagged-moi-local-terminal-copy/2"
    assert compiler.inspect()["unassigned_slots"] == [2, 3]
    output, proof = compiler.compile(**proposal(compiler))
    assert MoiIdentity(output).data == literal_move(MoiIdentity(files[3]).data)
    assert proof["profile"] == "tagged-moi-local-terminal-copy/2"


@pytest.mark.parametrize(
    "updates",
    [
        {"label": "UI IN2"},
        {"label": "AO1-Int"},
        {"cid": 999},
        {"oid": (0, 501)},
        {"ref": "controller/sa/1_501"},
        {"slot": encoded(Enumerated(1))},
        {"extra": [(2577, encoded(Unsigned(0)))]},
        {"extra": [(3645, encoded(Unsigned(0)))]},
    ],
)
def test_unqualified_output_identity_slot_or_input_looking_binding_still_refuses(updates):
    files = with_output(authored(), **updates)
    with pytest.raises(ValueError):
        MoiTerminalCopies(files[3], output_namespace=True)
