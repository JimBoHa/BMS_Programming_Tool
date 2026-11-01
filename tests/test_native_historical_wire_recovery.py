"""A retained original native connection proves only its missing output pin."""

import struct

import pytest
from bms_tool.moi_identity import MoiIdentity, seal
from bms_tool.mstp import header_crc
from bms_tool.native_historical_pin import HistoricalWireCompiler
from bms_tool.native_historical_wire_recovery import NativeHistoricalWireRecovery
from bms_tool.native_wire_transfer import compile_wire

from .test_moi_wire_sources import REF, A, B
from .test_native_default_transfer import real_slot
from .test_native_signal_compiler import slot
from .test_native_wire_compiler import wire_files
from .test_native_wire_recovery import FANOUT, current_source, setup


@pytest.mark.parametrize("index,previous", [(0, A), (1, B)])
@pytest.mark.parametrize("diagram_class", [536, 575])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("source_index_width", [1, 2, 3, 4])
def test_missing_pin_uses_actual_original_record_and_preserves_every_other_merged_byte(
    tmp_path, index, previous, diagram_class, compressed, source_index_width
):
    storage, ordinary, request, before, files = setup(
        tmp_path,
        index=index,
        diagram_class=diagram_class,
        compressed=compressed,
        wires=FANOUT[:2],
        source_index_width=source_index_width,
    )
    with pytest.raises(ValueError, match="no observed outgoing"):
        ordinary.prepare(request)
    service = NativeHistoricalWireRecovery(ordinary.records)
    report = service.prepare(request)
    assert report["profile"] == "native-historical-pin-wire-recovery-draft/1"
    pin = report["origin"]["historical_pin"]
    assert pin["source_ref"] == previous and pin["old"][1] == 85
    assert pin["original_capture_id"] == before["id"]
    assert pin["original_snapshot_sha256"] == before["evidence_sha256"]
    assert pin["diagram_class"] == diagram_class
    assert pin["source_index_bytes"] == source_index_width
    assert seal(pin) == report["origin"]["historical_pin_sha256"]
    compiler = service.compiler_for(report, files)
    proposal = {k: v for k, v in report["proposal"].items() if k != "recovery_parent_receipt"}
    output, compiled = compile_wire(files, proposal, _compiler=compiler)
    assert compiled["historical_pin_evidence"] == pin
    assert compiled["historical_pin_evidence_sha256"] == seal(pin)
    observed = MoiIdentity(output)
    assert observed.reader.diagram(REF)["connections"][index]["source_ref"] == previous
    offset, width = compiled["wire_edit"]["source_index_offset"], pin["source_index_bytes"]
    merged = compiler.effective.editor.data
    assert (
        observed.data
        == merged[:offset] + pin["old"][0].to_bytes(width, "big") + merged[offset + width :]
    )
    assert report["proposal_candidate"]["ref"] == previous
    assert report["proposal_candidate"]["index"] == pin["old"][0]
    assert report["proposal_candidate"]["current_source"] is False
    assert len(storage.receipts()) == 1 and storage.load(request["capture_id"])[1] == files
    assert report["read_only"] and not report["controller_queries"] and not report["can_apply"]


def test_current_pin_keeps_the_exact_existing_v1_report(tmp_path):
    _, ordinary, request, _, _ = setup(tmp_path)
    assert NativeHistoricalWireRecovery(ordinary.records).prepare(request) == ordinary.prepare(
        request
    )


def test_historical_pin_keeps_other_current_saved_real_values(tmp_path):
    storage, ordinary, request, _, files = setup(tmp_path, wires=FANOUT[:2])
    real_slot(files, 0, struct.pack(">f", 45))
    service = NativeHistoricalWireRecovery(ordinary.records)
    report = service.prepare(current_source(storage, request, files))
    output, _ = compile_wire(
        files,
        {k: v for k, v in report["proposal"].items() if k != "recovery_parent_receipt"},
        _compiler=service.compiler_for(report, files),
    )
    image = MoiIdentity(output)
    assert image.reader.scalar(image.reader.records[A], 3113) == 45
    assert image.reader.scalar(image.reader.records[B], 3113) == 17


@pytest.mark.parametrize(
    "change", ["index", "port", "class", "source", "object", "configuration", "image", "alias"]
)
def test_altered_retained_pin_cannot_qualify_a_private_compiler(tmp_path, change):
    _, ordinary, request, _, files = setup(tmp_path, wires=FANOUT[:2])
    report = NativeHistoricalWireRecovery(ordinary.records).prepare(request)
    pin = report["origin"]["historical_pin"]
    if change == "index":
        pin["wire_index"] = 1
    elif change == "port":
        pin["old"][1] = 86
    elif change == "class":
        pin["source_class"] = 530
    elif change == "source":
        pin["source_ref"] = B
    elif change == "object":
        pin["source_object"] = "analog-value,11"
    elif change == "configuration":
        pin["source_configuration_sha256"] = "0" * 64
    elif change == "image":
        pin["after_native_sha256"] = "0" * 64
    else:
        pin["old"][0] = False
    with pytest.raises(ValueError):
        HistoricalWireCompiler(files, pin)


@pytest.mark.parametrize("both", [False, True])
def test_matching_new_prototypes_do_not_replace_original_pin_configuration(tmp_path, both):
    files = wire_files(target_class=538, wires=FANOUT[:2])
    for oid in (10, 11):
        files[11] += slot((2 << 22) | oid, 551, 65000, 2, len(files[12]))
        value = (1).to_bytes(4, "big")
        files[12] += value + bytes([header_crc(value) ^ 255])
    storage, ordinary, request, _, files = setup(tmp_path, files=files)
    service = NativeHistoricalWireRecovery(ordinary.records)
    service.prepare(request)
    real_slot(files, 17, (2).to_bytes(4, "big"))
    if both:
        real_slot(files, 22, (2).to_bytes(4, "big"))
    with pytest.raises(ValueError, match="configuration changed"):
        service.prepare(current_source(storage, request, files))


@pytest.mark.parametrize("fault", ["order", "cycle"])
def test_original_edge_does_not_bypass_current_order_or_cycle(tmp_path, fault):
    options = {"wires": FANOUT[:2]}
    if fault == "order":
        options["order"] = (1, 2, 0, 3)
    else:
        options["wires"] = [*FANOUT[:2], (2, 85, 0, 7000)]
    _, ordinary, request, _, _ = setup(tmp_path, **options)
    with pytest.raises(ValueError, match="execute before|introduce a cycle"):
        NativeHistoricalWireRecovery(ordinary.records).prepare(request)
