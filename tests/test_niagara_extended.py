"""Finite extended BOG interoperability, with external vendor descriptor checks.

These are offline graph/encoding checks. No test claims execution in a licensed
Niagara station. Foreign fixtures are hand-authored independently of our writer.
"""

import hashlib
import xml.etree.ElementTree as XML
import zipfile

import pytest
from bms_tool.engine import Engine, validate
from bms_tool.formats import ConversionError
from bms_tool.models import Edge, Node, Program, Target
from bms_tool.niagara import (
    SOURCE,
    SUPPORTED,
    NiagaraArchive,
    export_bog,
    import_bog,
)

from tests.test_niagara_sdk import DescriptorRegistry
from tests.test_niagara_sdk import sdk as genuine_sdk


@pytest.fixture(scope="module")
def vendor_metadata():
    return genuine_sdk.__wrapped__()


def unary(kind, params, *, source_unit="", unit="", identifier="block"):
    return Program(
        id="extended-niagara",
        nodes=[
            Node(id="source", kind="Input", unit=source_unit),
            Node(id=identifier, kind=kind, unit=unit, params=params),
            Node(id="result", kind="Output", unit=unit),
        ],
        edges=[
            Edge(id="input", source="source", target=identifier),
            Edge(id="output", source=identifier, target="result"),
        ],
    )


def native(program):
    return SOURCE.sub(b"", NiagaraArchive(export_bog(program)).xml)


def outputs_for(program, values):
    engine = Engine(program)
    inputs = [n.id for n in program.nodes if n.kind == "Input"]
    assert len(inputs) == 1
    results = []
    for value in values:
        scan = engine.step({inputs[0]: value})
        results.append(list(scan["outputs"].values()))
    return results


@pytest.mark.parametrize("unit", ["", "%", "degC", "cfm"])
def test_clamp_composite_preserves_finite_limits_units_and_multiple_consumers(unit):
    program = unary("Clamp", {"min": -5, "max": 30}, source_unit=unit, unit=unit)
    program.nodes.append(Node(id="second", kind="Output", unit=unit))
    program.edges.append(Edge(id="branch", source="block", target="second"))
    archive = export_bog(program)
    assert import_bog(archive) == program
    foreign = import_bog(SOURCE.sub(b"", NiagaraArchive(archive).xml))
    assert {n.kind for n in foreign.nodes} <= {"Input", "Output", "Constant", "Min", "Max"}
    assert not [d for d in validate(foreign) if d.level == "error"]
    values = [-100, -5, -4.75, 0, 30, 31, 100]
    actual = outputs_for(foreign, values)
    assert actual == [[max(-5, min(30, x))] * 2 for x in values]
    assert actual == outputs_for(program, values)


@pytest.mark.parametrize("clamp", [True, False])
@pytest.mark.parametrize("reversed_input", [True, False])
@pytest.mark.parametrize("descending_output", [True, False])
@pytest.mark.parametrize("units", [("", ""), ("%", "cfm"), ("degC", "degC")])
def test_scale_clamping_extrapolation_reversed_intervals_and_engineering_units(
    clamp, reversed_input, descending_output, units
):
    params = {
        "in_min": 100 if reversed_input else 0,
        "in_max": 0 if reversed_input else 100,
        "out_min": 1600 if descending_output else 200,
        "out_max": 200 if descending_output else 1600,
        "clamp": clamp,
    }
    program = unary("Scale", params, source_unit=units[0], unit=units[1])
    archive = export_bog(program)
    assert import_bog(archive) == program
    xml = SOURCE.sub(b"", NiagaraArchive(archive).xml)
    use_reset = clamp and units[0] == units[1]
    assert (b"kitControl:Reset" in xml) == use_reset
    if use_reset:
        component = next(
            e for e in XML.fromstring(xml).iter("p") if e.get("t") == "kitControl:Reset"
        )
        limits = {
            p.get("n"): float(p.find("./p[@n='value']").get("v"))
            for p in component
            if p.get("n", "").endswith("Limit")
        }
        assert limits["inputLowLimit"] < limits["inputHighLimit"]
    foreign = import_bog(xml)
    values = [-100, 0, 1, 25, 50, 75, 100, 200]
    actual = outputs_for(foreign, values)
    expected = outputs_for(program, values)
    assert [row[0] for row in actual] == pytest.approx([row[0] for row in expected])
    assert all(n.unit == units[1] for n in foreign.nodes if n.kind == "Output")


@pytest.mark.parametrize("clamp", [True, False])
def test_scale_composites_preserve_named_final_result_for_multiple_consumers(clamp):
    program = unary(
        "Scale",
        {"in_min": 0, "in_max": 100, "out_min": 200, "out_max": 800, "clamp": clamp},
        source_unit="%",
        unit="cfm",
        identifier="niagara_lower_3",
    )
    program.nodes.append(Node(id="second", kind="Output", unit="cfm"))
    program.edges.append(Edge(id="branch", source="niagara_lower_3", target="second"))
    foreign = import_bog(native(program))
    expected = [[200, 200], [500, 500], [800, 800] if clamp else [1400, 1400]]
    assert outputs_for(foreign, [0, 50, 200]) == expected


@pytest.mark.parametrize("kind", ["Clamp", "Scale"])
def test_expansion_enforces_target_resource_limit_before_export(kind):
    program = unary(kind, {"clamp": False} if kind == "Scale" else {})
    program.target = Target(max_nodes=3)
    with pytest.raises(ConversionError, match="expansion.*node limit"):
        export_bog(program)


def test_nonfinite_derived_scale_span_is_rejected_before_native_encoding():
    program = unary("Scale", {"in_min": -1e308, "in_max": 1e308, "clamp": False})
    with pytest.raises(ConversionError, match="finite"):
        export_bog(program)


# Original hand-authored native records, using real BUnit encodings independently
# checked against defaults/units.xml in test_niagara_sdk.py.
TEMPERATURE_FACETS = {
    "degF": "units=u:fahrenheit;\N{DEGREE SIGN}F;(K);*0.5555555555555556+255.37222222222223;",
    "degC": "units=u:celsius;\N{DEGREE SIGN}C;(K);+273.15;",
    "K": "units=u:kelvin;K;(K);;",
}


def foreign_converter(source, target, value=32):
    document = XML.fromstring(
        '<bajaObjectGraph version="4.0"><p n="Root" h="0" m="b=baja" t="b:Folder">'
        '<p n="Convert" h="1" m="k=kitControl" t="k:NumericUnitConverter"/>'
        "</p></bajaObjectGraph>"
    )
    component = document.find("./p/p")
    XML.SubElement(component, "p", {"n": "inFacets", "t": "b:Facets", "v": source})
    XML.SubElement(component, "p", {"n": "outFacets", "t": "b:Facets", "v": target})
    status = XML.SubElement(component, "p", {"n": "in", "t": "b:StatusNumeric"})
    XML.SubElement(status, "p", {"n": "value", "v": str(value)})
    XML.SubElement(status, "p", {"n": "status", "v": "0"})
    return XML.tostring(document, encoding="utf-8")


@pytest.mark.parametrize(
    "source,target,value,expected",
    [
        ("degF", "degC", 32, 0),
        ("degF", "K", 212, 373.15),
        ("degC", "degF", -40, -40),
        ("degC", "K", 0, 273.15),
        ("K", "degF", 273.15, 32),
        ("K", "degC", 373.15, 100),
        ("degF", "degF", 73.2, 73.2),
        ("degC", "degC", 22.5, 22.5),
        ("K", "K", 100, 100),
    ],
)
def test_real_unit_converter_encoding_and_foreign_static_input_units(
    source, target, value, expected
):
    program = unary("Convert", {"from": source, "to": target}, source_unit=source, unit=target)
    assert import_bog(export_bog(program)) == program
    xml = native(program)
    component = next(
        e for e in XML.fromstring(xml).iter("p") if e.get("t") == "kitControl:NumericUnitConverter"
    )
    assert component.find("./p[@n='facets']") is None
    assert component.find("./p[@n='inFacets']").get("v") == TEMPERATURE_FACETS[source]
    assert component.find("./p[@n='outFacets']").get("v") == TEMPERATURE_FACETS[target]
    actual = outputs_for(import_bog(xml), [value])[0][0]
    assert actual == pytest.approx(expected)
    foreign = import_bog(
        foreign_converter(TEMPERATURE_FACETS[source], TEMPERATURE_FACETS[target], value)
    )
    assert next(n for n in foreign.nodes if n.kind == "Constant").unit == source
    assert next(n for n in foreign.nodes if n.kind == "Convert").unit == target
    assert list(Engine(foreign).step()["outputs"].values()) == pytest.approx([expected])


@pytest.mark.parametrize(
    "facets",
    ["", "units=u:percent;%;;;", "units=u:celsius;°C;(K);+200;", "units=u:unknown;x;(K);;"],
)
def test_native_converter_rejects_missing_wrong_dimension_or_changed_unit_transform(facets):
    with pytest.raises(ConversionError, match="temperature units|scale/offset|Unknown"):
        import_bog(foreign_converter(TEMPERATURE_FACETS["degF"], facets))


def test_native_converter_rejects_bad_status_ignored_facets_and_wrong_facets_type():
    xml = foreign_converter(TEMPERATURE_FACETS["degF"], TEMPERATURE_FACETS["degC"])
    for invalid, message in (
        (xml.replace(b'n="status" v="0"', b'n="status" v="1"'), "Non-good"),
        (xml.replace(b'n="inFacets"', b'n="facets"'), "configuration"),
        (xml.replace(b't="b:Facets"', b't="b:String"', 1), "type baja:Facets"),
    ):
        with pytest.raises(ConversionError, match=message):
            import_bog(invalid)


def foreign_reset():
    return b"""<bajaObjectGraph version="4.0"><p n="Root" h="0" m="b=baja" t="b:Folder">
    <p n="Reset" h="1" m="k=kitControl" t="k:Reset">
    <p n="inA"><p n="value" v="75"/><p n="status" v="0"/></p>
    <p n="inputLowLimit"><p n="value" v="50"/></p>
    <p n="inputHighLimit"><p n="value" v="100"/></p>
    <p n="outputLowLimit"><p n="value" v="180"/></p>
    <p n="outputHighLimit"><p n="value" v="140"/></p>
    </p></p></bajaObjectGraph>"""


def test_independently_authored_reset_static_limits_import_as_clamped_scale():
    program = import_bog(foreign_reset())
    scale = next(n for n in program.nodes if n.kind == "Scale")
    assert scale.params == {
        "in_min": 50,
        "in_max": 100,
        "out_min": 180,
        "out_max": 140,
        "clamp": True,
    }
    # Manufacturer BReset equation: ((140-180)/(100-50))*(75-50)+180.
    assert list(Engine(program).step()["outputs"].values()) == [160]


def test_reset_rejects_implicit_inverted_or_live_limits_instead_of_losing_behavior():
    xml = foreign_reset()
    missing = XML.fromstring(xml)
    component = missing.find("./p/p")
    component.remove(component.find("./p[@n='inputLowLimit']"))
    live = xml.replace(
        b"</p></p></bajaObjectGraph>",
        b'<p n="Link" t="b:Link"><p n="sourceOrd" v="h:1"/>'
        b'<p n="sourceSlotName" v="out"/><p n="targetSlotName" v="inputLowLimit"/>'
        b"</p></p></p></bajaObjectGraph>",
    )
    for invalid, message in (
        (XML.tostring(missing), "every native Reset limit"),
        (xml.replace(b'n="value" v="100"', b'n="value" v="40"'), "must be less"),
        (live, "input slot"),
    ):
        with pytest.raises(ConversionError, match=message):
            import_bog(invalid)


@pytest.mark.parametrize(
    "program",
    [
        unary("Clamp", {"min": 10, "max": 10}, source_unit="degF", unit="degF"),
        unary("Scale", {"clamp": False}, source_unit="%", unit="cfm"),
        unary("Scale", {"clamp": True}, source_unit="%", unit="cfm"),
    ],
)
def test_new_native_composite_slots_and_links_match_genuine_manufacturer_descriptors(
    vendor_metadata, program
):
    registry = DescriptorRegistry(vendor_metadata)
    try:
        registry.check(XML.fromstring(native(program)))
    finally:
        registry.docs.close()


def test_documented_reset_and_converter_contracts_are_present_in_pinned_vendor_metadata(
    vendor_metadata,
):
    assert len(SUPPORTED) == 23
    registry = DescriptorRegistry(vendor_metadata)
    try:
        reset = registry.descriptor("com.tridium.kitControl.util.BReset")
        assert "(D-B)" in reset.findtext("description")
        assert "(C-A)" in reset.findtext("description")
        assert "capped" in reset.findtext("description")
        converter = registry.properties("com.tridium.kitControl.conversion.BNumericUnitConverter")
        assert converter == {
            "inFacets": "javax.baja.sys.BFacets",
            "in": "javax.baja.status.BStatusNumeric",
            "outFacets": "javax.baja.sys.BFacets",
            "out": "javax.baja.status.BStatusNumeric",
        }
    finally:
        registry.docs.close()
    guide = vendor_metadata / "docKitControl-doc.jar"
    assert hashlib.sha256(guide.read_bytes()).hexdigest() == (
        "68b399f8d63228e950dc89607c1ac9bfd89c8c9442aebbeb6fe299dd6b9eef0b"
    )
    with zipfile.ZipFile(guide) as archive:
        guide_text = archive.read("doc/kitControl-NumericUnitConverter.html").decode()
        assert "same category" in guide_text and "fault" in guide_text
