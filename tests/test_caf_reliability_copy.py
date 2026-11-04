"""Independent authored Reliability Check subtrees; no vendor/field fixtures."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_reliability_copy import PROFILE, CafReliabilityCopies
from bms_tool.moi_identity import seal, sha

from tests.test_caf_boolean_logic_copy import example as graph_example
from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_4"
PROTOTYPE = REF + ".539_10"


def example(*, kind="float", spelling="true", zero=False):
    standard, typ, cid = (22, 19, 528) if kind == "enum" else (21, 2, 526)
    parent = (
        f'<object classid="539" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="539">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(3184, '<array><enum set="509">513</enum><enum set="509">85</enum></array>')
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    children = ""
    for cls, object_type, instance, port in [(531, 5, 11, 85), (cid, typ, 12, 513)]:
        ref = f"{PROTOTYPE}.{object_type}_{instance}"
        children += (
            f'<object classid="{cls}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{object_type}">{instance}</BACoid>')
            + prop(32527, f"<string>{ref}</string>")
            + prop(3365, f'<enum set="509">{port}</enum>')
            + (
                prop(3113, f"<boolean>{spelling}</boolean>")
                if port == 85 and kind != "enum"
                else ""
            )
            + (
                prop(74, "<unsignedShort>2</unsignedShort>")
                + prop(931, '<enum set="802">349</enum>')
                if object_type == 19
                else ""
            )
            + "</object>"
        )
    xml = CafArchive(graph_example()).xml.decode()
    start = xml.index('<object classid="559"')
    end = xml.index(f'<object classid="530" classVersion="1.0" ref="{REF}.5_20"')
    xml = (xml[:start] + parent + children + xml[end:]).replace(
        '<BACoid id="559">10</BACoid>', '<BACoid id="539">10</BACoid>', 1
    )
    return packed(xml, zero=zero)


def options(c, **updates):
    s = c.inspect(REF, PROTOTYPE)
    return {
        "diagram_ref": REF,
        "prototype_ref": PROTOTYPE,
        "selection_sha256": s["selection_sha256"],
        "x": "+81.000",
        "y": "4.2E+1",
        **updates,
    }


def mixed_example():
    from tests.test_caf_boolean_logic_copy import mixed_example as previous
    from tests.test_caf_constant_copy import REF as FREF

    xml = CafArchive(previous()).xml.decode()
    for kind, first, input_type in [("float", 110, 2), ("enum", 120, 19)]:
        own = CafArchive(example(kind=kind)).xml.decode()
        start = own.index('<object classid="539"')
        end = own.index(f'<object classid="530" classVersion="1.0" ref="{REF}.5_20"')
        subtree = own[start:end].replace(REF, FREF).replace(".539_10", f".539_{first}")
        for typ, old, new in [(539, 10, first), (5, 11, first + 1), (input_type, 12, first + 2)]:
            subtree = (
                subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
                .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
                .replace(f'objectid="{old}"', f'objectid="{new}"')
                .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
            )
        xml = xml.replace("</objects>", subtree + "</objects>")
    xml = xml.replace(
        '<BACoid id="559">100</BACoid></array>',
        '<BACoid id="559">100</BACoid><BACoid id="539">110</BACoid><BACoid id="539">120</BACoid></array>',
        1,
    )
    xml = xml.replace(shorts(*range(10)), shorts(*range(12)), 1)
    pos = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(xml.replace(pos * 10, pos * 12, 1), zero=True)


@pytest.mark.parametrize("kind,spelling", [("float", "true"), ("float", "1"), ("enum", "true")])
def test_exact_complete_xml_truth_spelling_omission_metadata_and_existing_connection(
    kind, spelling
):
    original = example(kind=kind, spelling=spelling, zero=True)
    c = CafReliabilityCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="539"')
    end = xml.index(f'<object classid="530" classVersion="1.0" ref="{REF}.5_20"')
    clone = xml[start:end].replace(".539_10", ".539_31")
    for typ, old, new in [(539, 10, 31), (5, 11, 32), (19 if kind == "enum" else 2, 12, 33)]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="5">30</BACoid></array>',
        '<BACoid id="5">30</BACoid><BACoid id="539">31</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2), shorts(0, 3, 1, 2), 1)
    oldpos = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    newpos = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(oldpos * 3, oldpos * 3 + newpos, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode() and len(a.objects) == len(c.archive.objects) + 3
    assert (
        c.archive.original == original
        and s["profile"] == PROFILE
        and s["object_count"] == 3
        and s["setup_code"] is None
    )
    assert (
        s["operator_meaning_verified"] is False
        and s["reliability_semantics_verified"] is False
        and s["enum_semantics_verified"] is False
    )
    assert s["children"][0]["recorded_default"] == (None if kind == "enum" else spelling)
    assert s["children"][1]["recorded_default"] is None
    assert s["children"][1]["states_text_code"] == (349 if kind == "enum" else None)
    assert (
        s["new_output_ref"] == s["new_ref"] + ".5_32"
        and report["new_output_sha256"] == report["new_child_sha256"][0]
    )
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    ) and report["output_sha256"] == sha(output)
    for key in (
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "extra",
        "internal_attr",
        "external_attr",
        "create_system",
    ):
        assert getattr(a.info, key) == getattr(c.archive.info, key)
    assert a.comment == c.archive.comment
    linked, _ = CafGraph(output).add_connections(
        [
            {
                "diagram_ref": REF,
                "prototype_diagram_ref": REF,
                "prototype_wire_index": 0,
                "prototype_old": [0, 85, 1, 513],
                "source_ref": s["new_ref"],
                "target_ref": REF + ".5_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(linked).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafReliabilityCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".539_34.5_35" in CafArchive(second).objects


@pytest.mark.parametrize("kind", ["float", "enum"])
def test_exact_last_three_ids_and_one_slot_too_few(kind):
    xml = CafArchive(example(kind=kind)).xml
    marker = b'<BACoid id="5">4194299</BACoid>'
    c = CafReliabilityCopies(
        packed(xml.replace(b"<string>Unrelated graph metadata</string>", marker))
    )
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == 4194300
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + f".{19 if kind == 'enum' else 2}_4194302" in CafArchive(output).objects
    with pytest.raises(ValueError, match="identities"):
        CafReliabilityCopies(
            packed(
                xml.replace(
                    b"<string>Unrelated graph metadata</string>",
                    marker.replace(b"4194299", b"4194300"),
                )
            )
        ).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "kind,old,new",
    [
        ("float", 'classid="539"', 'classid="559"'),
        ("float", 'classid="539" classVersion="1.0"', 'classid="539" classVersion="2.0"'),
        ("float", 'set="432">21', 'set="432">22'),
        ("enum", 'set="432">22', 'set="432">21'),
        ("float", prop(3113, "<boolean>true</boolean>"), prop(3113, "<boolean>false</boolean>")),
        ("float", prop(3113, "<boolean>true</boolean>"), prop(3113, "<float>1</float>")),
        (
            "float",
            '<property id="3670">',
            '<property id="518"><data><enum set="287">1</enum></data></property><property id="3670">',
        ),
        ("float", '<BACoid id="5">11', '<BACoid id="2">11'),
        ("float", 'classid="526"', 'classid="528"'),
        ("enum", 'set="802">349', 'set="647">349'),
        ("enum", 'set="802">349', 'set="802">350'),
        (
            "enum",
            prop(74, "<unsignedShort>2</unsignedShort>"),
            prop(74, "<unsignedShort>3</unsignedShort>"),
        ),
        (
            "enum",
            '<property id="931">',
            '<property id="3113"><data><enum set="647">1</enum></data></property><property id="931">',
        ),
        ("float", '<property id="3365">', '<property id="3365" unknown="yes">'),
        (
            "float",
            '<property id="3373"><data><boolean>true</boolean></data></property>',
            '<property id="3373"><data><boolean>false</boolean></data></property>',
        ),
    ],
)
def test_unknown_reliability_shape_refused_without_changing_original(kind, old, new):
    xml = CafArchive(example(kind=kind)).xml.decode()
    assert old != new and old in xml
    original = packed(xml.replace(old, new, 1))
    c = CafReliabilityCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_mixed_fixture_retains_all_previous_families_and_both_reliability_variants():
    c = CafReliabilityCopies(mixed_example())
    ref = "8-1/575_1"
    assert len(c.graph.diagram(ref)["blocks"]) == 12
    assert c.inspect(ref, ref + ".539_110")["children"][1]["bacnet_type"] == 2
    assert c.inspect(ref, ref + ".539_120")["children"][1]["bacnet_type"] == 19
