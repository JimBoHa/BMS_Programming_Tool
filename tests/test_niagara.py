import io
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
from bms_tool.engine import Engine
from bms_tool.formats import ConversionError
from bms_tool.models import Edge, Node, Program
from bms_tool.niagara import NATIVE, SOURCE, NiagaraArchive, export_bog, import_bog

from tests.test_native_sedona import block_program


def archive(xml, extra=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("file.xml", xml)
        if extra:
            z.writestr("unknown.bin", extra)
        z.comment = b"preserve native metadata"
    return out.getvalue()


@pytest.mark.parametrize("kind", [*NATIVE, "Input", "Output", "Constant", "Switch"])
def test_native_primitive_round_trip_and_foreign_finite_graph_values(kind):
    program = block_program(kind)
    content = export_bog(program)
    assert NiagaraArchive(content).export() == content
    restored = import_bog(content)
    assert restored == program and restored.digest() == program.digest()
    native_xml = SOURCE.sub(b"", NiagaraArchive(content).xml)
    foreign = import_bog(native_xml)
    expected = list(Engine(program).step()["outputs"].values())
    actual = list(Engine(foreign).step()["outputs"].values())
    assert actual == expected
    assert foreign.metadata["conversion"]["review_required"]
    assert any(
        "events" in difference for difference in foreign.metadata["conversion"]["differences"]
    )


def test_unknown_archive_members_and_original_bytes_are_preserved_not_silently_converted():
    xml = NiagaraArchive(export_bog(block_program("Add"))).xml
    content = archive(xml, b"opaque original resource")
    view = NiagaraArchive(content)
    assert view.export() == content and "unknown.bin" in view.summary()["members"]
    with pytest.raises(ConversionError, match="resources"):
        import_bog(content)


@pytest.mark.parametrize("kind", ["PI", "Delay", "Schedule", "TimerOn", "Alarm", "Slew"])
def test_unverified_stateful_native_semantics_are_rejected(kind):
    with pytest.raises(ConversionError, match="does not lower"):
        export_bog(block_program(kind))


def test_external_native_edit_cannot_hide_behind_embedded_original_source():
    content = export_bog(block_program("Constant"))
    native = NiagaraArchive(content).xml.replace(b'v="-3.25"', b'v="9.0"')
    with pytest.raises(ConversionError, match="no longer matches"):
        import_bog(archive(native))


def test_unknown_component_and_dynamic_logic_settings_stop_conversion():
    native = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Add"))).xml)
    with pytest.raises(ConversionError, match="mapping"):
        import_bog(native.replace(b"kitControl:Add", b"kitControl:CustomControl"))
    with pytest.raises(ConversionError, match="configuration"):
        import_bog(native.replace(b'<p n="inC"', b'<p n="unknownSetting"', 1))


@pytest.mark.parametrize("replacement", [b"h:missing", b"foxs://site/point", b"slot:/outside"])
def test_unresolved_external_native_links_are_rejected(replacement):
    native = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Add"))).xml)
    native = native.replace(b'v="h:2"', b'v="' + replacement + b'"')
    with pytest.raises(ConversionError, match="external, unresolved"):
        import_bog(native)


def test_raw_xml_unsafe_duplicates_and_depth_limits():
    base = b'<bajaObjectGraph version="4.0"><p h="1" n="Root" m="b:baja" t="b:Folder"/></bajaObjectGraph>'
    assert NiagaraArchive(base).summary()["components"][0]["type"] == "baja:Folder"
    with pytest.raises(ConversionError, match="duplicate"):
        NiagaraArchive(base.replace(b"/></baja", b'/><p h="1" n="Other" t="b:Folder"/></baja'))
    with pytest.raises(ConversionError, match="unsafe"):
        NiagaraArchive(
            b'<!DOCTYPE x [<!ENTITY ex SYSTEM "file:///etc/passwd">]><bajaObjectGraph version="4.0">&ex;</bajaObjectGraph>'
        )
    with pytest.raises(ConversionError, match="depth"):
        NiagaraArchive(
            b'<bajaObjectGraph version="4.0">' + b"<p>" * 60 + b"</p>" * 60 + b"</bajaObjectGraph>"
        )


def test_protected_encoding_and_nonfinite_values_fail_explicitly():
    native = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Constant"))).xml)
    with pytest.raises(ConversionError, match="Protected"):
        import_bog(native.replace(b'KeySource="none"', b'KeySource="keyring"'))
    with pytest.raises(ConversionError, match="finite"):
        import_bog(native.replace(b'v="-3.25"', b'v="NaN"'))


def test_four_input_reduction_keeps_all_consumers_on_final_result():
    # Result precedes Sum, deliberately exercising forward and backward XML order.
    xml = b"""<bajaObjectGraph version="4.0"><p h="0" n="Root" m="b=baja" t="b:Folder">
    <p h="1" n="Result" m="c=control" t="c:NumericWritable"><p n="fallback"><p n="value" v="0"/></p><p n="Link" t="b:Link"><p n="sourceOrd" v="h:2"/><p n="sourceSlotName" v="out"/><p n="targetSlotName" v="in16"/></p></p>
    <p h="2" n="Sum" m="k=kitControl" t="k:Add"><p n="inA" v="1"/><p n="inB" v="2"/><p n="inC" v="3"/><p n="inD" v="4"/></p>
    </p></bajaObjectGraph>"""
    converted = import_bog(xml)
    assert list(Engine(converted).step()["outputs"].values()) == [10]


def test_boolean_comparator_constant_inputs_remain_numeric():
    xml = b"""<bajaObjectGraph version="4.0"><p h="0" n="Root" m="b=baja" t="b:Folder"><p h="1" n="Above" m="k=kitControl" t="k:GreaterThan"><p n="inA" v="10"/><p n="inB" v="5"/></p></p></bajaObjectGraph>"""
    p = import_bog(xml)
    assert list(Engine(p).step()["outputs"].values()) == [True]


def test_relative_local_ord_is_resolved_without_network_access():
    program = block_program("Add")
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(program)).xml)
    raw = raw.replace(b'v="h:2"', b'v="slot:../n_input0"')
    assert list(Engine(import_bog(raw)).step()["outputs"].values()) == [6]


def test_native_mixed_finite_unit_facets_round_trip():
    p = Program(
        nodes=[
            Node(id="in", kind="Input", unit="degF", params={"default": 72}),
            Node(id="out", kind="Output", unit="degF"),
        ],
        edges=[Edge(id="e", source="in", target="out")],
    )
    data = export_bog(p)
    assert b"degreeFahrenheit" in NiagaraArchive(data).xml
    assert {n.unit for n in import_bog(SOURCE.sub(b"", NiagaraArchive(data).xml)).nodes} == {"degF"}
    p.nodes[0].unit = p.nodes[1].unit = "unknown-unit"
    with pytest.raises(ConversionError, match="facet mapping"):
        export_bog(p)


@pytest.mark.parametrize(
    "component", ["kitControl:Program", "custom:UnknownLogic", "baja:Component"]
)
def test_handleless_typed_native_logic_is_preserved_but_never_silently_dropped(component):
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Constant"))).xml)
    raw = raw.replace(
        b"</bajaObjectGraph>", f'<p n="HiddenLogic" t="{component}"/></bajaObjectGraph>'.encode()
    )
    preserved = NiagaraArchive(raw)
    assert preserved.export() == raw
    assert preserved.summary()["unhandled_typed_records"][0]["type"] == component
    with pytest.raises(ConversionError, match="without a handle would be lost"):
        import_bog(raw)


def test_root_scope_native_module_aliases_are_resolved():
    raw = b"""<bajaObjectGraph version="4.0" m="b=baja;k=kitControl"><p h="0" n="Root" t="b:Folder"><p h="1" n="C" t="k:NumericConst"><p n="out" v="7"/></p></p></bajaObjectGraph>"""
    assert list(Engine(import_bog(raw)).step()["outputs"].values()) == [7]
    with pytest.raises(ConversionError, match="duplicate native module"):
        NiagaraArchive(raw.replace(b"b=baja;k=kitControl", b"b=baja;b=other"))


@pytest.mark.parametrize("configuration", [b"min=d:10", b"max=d:100", b"customLimit=i:1"])
def test_unmodeled_native_facets_cannot_be_silently_discarded(configuration):
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Input"))).xml)
    raw = raw.replace(
        b'n="fallback"',
        b'n="facets" t="b:Facets" v="units=u:null|' + configuration + b'"/><p n="fallback"',
        1,
    )
    with pytest.raises(ConversionError, match="facet configuration would be lost"):
        import_bog(raw)


def test_supported_display_facets_retain_exact_original_conversion_evidence():
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Input"))).xml)
    facets = "units=u:null;;;;|precision=i:2|min=d:-inf|max=d:+inf"
    raw = raw.replace(
        b'n="fallback"', b'n="facets" t="b:Facets" v="' + facets.encode() + b'"/><p n="fallback"', 1
    )
    converted = import_bog(raw)
    assert facets in converted.metadata["conversion"]["native_facets"].values()


@pytest.mark.parametrize(
    "configuration,message",
    [
        (b'<p n="status" v="1"/>', "Non-good native status"),
        (b'<p n="status" v="0"/><p n="status" v="1"/>', "Duplicate native status"),
        (b'<p n="status"><p n="value" v="1"/></p>', "status encoding"),
        (b'<p n="unknownConfig" v="1"/>', "nested native value"),
    ],
)
def test_nested_native_status_and_unknown_value_settings_are_not_ignored(configuration, message):
    raw = (
        b'<bajaObjectGraph version="4.0"><p h="1" n="C" m="k=kitControl" t="k:NumericConst"><p n="out"><p n="value" v="5"/>'
        + configuration
        + b"</p></p></bajaObjectGraph>"
    )
    with pytest.raises(ConversionError, match=message):
        import_bog(raw)


def test_mixed_scalar_and_status_encoding_is_rejected():
    raw = b'<bajaObjectGraph version="4.0"><p h="1" n="C" m="k=kitControl" t="k:NumericConst"><p n="out" v="5"><p n="status" v="1"/></p></p></bajaObjectGraph>'
    with pytest.raises(ConversionError, match="mixes attribute and nested"):
        import_bog(raw)


def test_export_status_values_explicitly_configure_good_initial_status():
    graph = NiagaraArchive(export_bog(block_program("Add")))
    wrappers = graph.root.findall(".//p[@t='b:StatusNumeric']")
    assert wrappers
    assert all(wrapper.find("./p[@n='status']").get("v") == "0" for wrapper in wrappers)


def test_reduction_extra_input_cannot_read_a_folder_as_an_executable_source():
    raw = b"""<bajaObjectGraph version="4.0"><p h="0" n="Root" m="b=baja;k=kitControl" t="b:Folder"><p h="1" n="Sum" t="k:Add"><p n="inA" v="1"/><p n="inB" v="2"/><p n="Link" t="b:Link"><p n="sourceOrd" v="h:0"/><p n="sourceSlotName" v="out"/><p n="targetSlotName" v="inC"/></p></p></p></bajaObjectGraph>"""
    with pytest.raises(ConversionError, match="source is not an executable"):
        import_bog(raw)


def test_unknown_native_link_configuration_cannot_be_dropped():
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Add"))).xml)
    raw = raw.replace(b'<p n="sourceOrd"', b'<p n="enabled" v="false"/><p n="sourceOrd"', 1)
    with pytest.raises(ConversionError, match="link configuration would be lost"):
        import_bog(raw)


def test_corrupt_native_zip_deflate_stream_is_a_conversion_error():
    raw = bytearray(export_bog(block_program("Constant")))
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.infolist()[0]
        offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    raw[offset : offset + 8] = b"\xff" * 8
    with pytest.raises(ConversionError, match="Malformed or unsafe"):
        NiagaraArchive(bytes(raw))


def test_custom_native_link_relations_are_not_silently_converted_to_data_links():
    raw = SOURCE.sub(b"", NiagaraArchive(export_bog(block_program("Add"))).xml)
    raw = raw.replace(
        b'<p n="sourceOrd"', b'<p n="relationId" v="n:customLink"/><p n="sourceOrd"', 1
    )
    with pytest.raises(ConversionError, match="link relation configuration"):
        import_bog(raw)


def test_public_independent_pybog_builder_generates_importable_native_source():
    source = Path(__file__).resolve().parents[2] / "Reference_Sources/bbartling--pybog/src"
    if not source.is_dir():
        pytest.skip("Optional independently checked pybog source is not installed")
    sys.path.insert(0, str(source))
    try:
        from bog_builder.builder import BogFolderBuilder

        builder = BogFolderBuilder("Independent", debug=False)
        builder.add_numeric_writable("A", default_value=100)
        builder.add_numeric_const("B", 40)
        builder.add_subtract("Difference")
        builder.add_numeric_writable("Result")
        builder.add_link("A", "out", "Difference", "inA")
        builder.add_link("B", "out", "Difference", "inB")
        builder.add_link("Difference", "out", "Result", "in16")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "independent.bog"
            builder.save(str(path))
            program = import_bog(path.read_bytes())
        assert list(Engine(program).step()["outputs"].values()) == [60]
    finally:
        sys.path.remove(str(source))
