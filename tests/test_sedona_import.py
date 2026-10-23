import io
import zipfile

import pytest
from bms_tool.engine import Engine
from bms_tool.formats import ConversionError, export_program, import_program
from bms_tool.iec_symbols import SymbolTable
from bms_tool.sedona import compiler, toolchain
from bms_tool.sedona_import import import_sax

from tests.test_native_sedona import has_sdk

pytestmark = pytest.mark.skipif(not has_sdk(), reason="Optional pinned Sedona SDK is required")


def sax(*, order="forward"):
    source = """<comp name="a" type="types::WriteFloat"><prop name="in" val="40"/></comp>"""
    constant = """<comp name="b" type="types::ConstFloat"><prop name="out" val="2"/></comp>"""
    add = """<comp name="sum" type="math::Add2"/>"""
    comps = source + constant + add if order == "forward" else add + source + constant
    return (
        """<sedonaApp><schema><kit name="sys"/><kit name="types"/><kit name="math"/></schema>
      <app><prop name="scanPeriod" val="1000"/><comp name="logic" type="sys::Folder">"""
        + comps
        + """</comp></app>
      <links><link from="/logic/a.out" to="/logic/sum.in1"/>
      <link from="/logic/b.out" to="/logic/sum.in2"/></links></sedonaApp>"""
    ).encode()


def output_for(program, path):
    return next(n.id for n in program.nodes if n.kind == "Output" and n.label == path + ".out")


def test_foreign_native_source_converts_without_embedded_studio_metadata():
    program = import_program(sax(), "foreign.sax")
    output = output_for(program, "/logic/sum")
    assert Engine(program).step()["outputs"][output] == 42
    assert program.metadata["conversion"]["review_required"]
    assert len(program.metadata["conversion"]["behavior_changes"]) == 4
    # Conversion is semantic: the native source has no Studio graph payload.
    exported = export_program(program, "plcopen")[0]
    assert SymbolTable(program).role(output, "value").encode() in exported


def test_backward_native_link_retains_first_scan_delay():
    program = import_sax(sax(order="reverse"))
    output = output_for(program, "/logic/sum")
    engine = Engine(program)
    assert engine.step()["outputs"][output] == 2  # WriteFloat.out initializes at zero.
    assert engine.step()["outputs"][output] == 42
    assert len(program.metadata["conversion"]["previous_scan_links"]) == 1


def test_real_sab_compiler_output_converts_to_a_graph(tmp_path):
    source = tmp_path / "foreign.sax"
    source.write_bytes(sax())
    sdk, java = toolchain()
    compiler(sdk, java, source)
    program = import_program(source.with_suffix(".sab").read_bytes(), "foreign.sab")
    assert program.metadata["conversion"]["source_format"] == "Sedona SAB"
    assert Engine(program).step()["outputs"][output_for(program, "/logic/sum")] == 42


def test_unknown_logic_and_missing_native_schema_are_never_dropped():
    with pytest.raises(ConversionError, match="Unsupported native logic"):
        import_sax(sax().replace(b"math::Add2", b"math::Unknown"))
    with pytest.raises(ConversionError, match="undeclared kit"):
        import_sax(sax().replace(b"math::Add2", b"custom::Add2"))
    with pytest.raises(ConversionError, match="Unmapped native configuration"):
        import_sax(
            sax().replace(
                b'<comp name="sum" type="math::Add2"/>',
                b'<comp name="sum" type="math::Add2"><prop name="secretMode" val="2"/></comp>',
            )
        )
    with pytest.raises(ConversionError, match="checksum"):
        import_sax(sax().replace(b'<kit name="sys"/>', b'<kit name="sys" checksum="../../bad"/>'))


def test_modified_native_bundle_checksum_is_rejected():
    from bms_tool.templates import all_templates

    original = export_program(all_templates()[0], "sedona")[0]
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(out, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            target.writestr(name, data + b"edited" if name == "app.sab" else data)
    with pytest.raises(ConversionError, match="checksum"):
        import_program(out.getvalue(), "bad.sedona.zip")
