"""Independent authored Float Multiplexer records, not controller fixtures."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_float_multiplexer_copy import PROFILE, CafFloatMultiplexerCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts
from tests.test_caf_math_copy import example as graph_example

REF = "8-1/536_4"
PROTOTYPE = REF + ".562_10"
CHILDREN = [(527, 2, 11, 85), (530, 5, 12, 961), (526, 2, 13, 7000), (526, 2, 14, 7001)]


def example(*, zero=False):
    parent = (
        f'<object classid="562" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="562">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(
            2381,
            "<listof><unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort></listof>",
        )
        + prop(3122, "<unsignedShort>1</unsignedShort>")
        + prop(
            3184,
            "<array>"
            + "".join(f'<enum set="509">{n}</enum>' for n in [961, 7000, 7001, 85])
            + "</array>",
        )
        + prop(3670, '<enum set="432">14</enum>')
        + "</object>"
    )
    children = ""
    for cid, typ, instance, port in CHILDREN:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        children += (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + prop(32527, f"<string>{ref}</string>")
            + prop(3365, f'<enum set="509">{port}</enum>')
            + "</object>"
        )
    xml = CafArchive(graph_example(defaults="omitted")).xml.decode()
    start = xml.index('<object classid="561"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    xml = (xml[:start] + parent + children + xml[end:]).replace(
        '<BACoid id="561">10</BACoid>', '<BACoid id="562">10</BACoid>', 1
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
    from tests.test_caf_constant_copy import REF as FREF
    from tests.test_caf_reliability_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    own = CafArchive(example()).xml.decode()
    start = own.index('<object classid="562"')
    end = own.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    subtree = own[start:end].replace(REF, FREF).replace(".562_10", ".562_130")
    for typ, old, new in [(562, 10, 130), *[(typ, n, n + 120) for _, typ, n, _ in CHILDREN]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="539">120</BACoid></array>',
        '<BACoid id="539">120</BACoid><BACoid id="562">130</BACoid></array>',
        1,
    ).replace(shorts(*range(12)), shorts(*range(13)), 1)
    pos = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(pos * 12, pos * 13, 1).replace("</objects>", subtree + "</objects>"), zero=True
    )


@pytest.mark.parametrize("zero", [False, True])
def test_exact_complete_xml_bookkeeping_all_ports_omissions_and_existing_connection(zero):
    original = example(zero=zero)
    c = CafFloatMultiplexerCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    clone = xml[start:end].replace(".562_10", ".562_31")
    for typ, old, new in [(562, 10, 31), *[(typ, n, n + 21) for _, typ, n, _ in CHILDREN]]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="2">30</BACoid></array>',
        '<BACoid id="2">30</BACoid><BACoid id="562">31</BACoid></array>',
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
    assert (
        a.xml == expected.encode()
        and len(a.objects) == len(c.archive.objects) + 5
        and c.archive.original == original
    )
    assert (
        s["profile"] == PROFILE
        and s["object_count"] == 5
        and s["setup_code"] is None
        and s["standard_name_code"] == 14
    )
    assert s["operator_meaning_verified"] is False and s["multiplexer_semantics_verified"] is False
    assert s["recorded_property_2381"] == ["0", "2"] and s["recorded_property_3122"] == "1"
    assert [(r["bacnet_type"], r["port"], r["direction"]) for r in s["children"]] == [
        (2, 85, "output"),
        (5, 961, "input"),
        (2, 7000, "input"),
        (2, 7001, "input"),
    ]
    assert all(
        r["recorded_default"] is None and r["recorded_metadata_661"] is None and r["exposed"]
        for r in s["children"]
    )
    assert (
        s["new_output_ref"] == s["new_ref"] + ".2_32"
        and report["new_output_sha256"] == report["new_child_sha256"][0]
    )
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    ) and report["output_sha256"] == sha(output)
    for key in [
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "extra",
        "internal_attr",
        "external_attr",
        "create_system",
    ]:
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
                "target_ref": REF + ".2_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(linked).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafFloatMultiplexerCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".562_36.2_37" in CafArchive(second).objects


def test_last_five_ids_and_one_slot_too_few():
    xml = CafArchive(example()).xml
    marker = b'<BACoid id="2">4194297</BACoid>'
    c = CafFloatMultiplexerCopies(
        packed(xml.replace(b"<string>Unrelated graph metadata</string>", marker))
    )
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == 4194298
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + ".2_4194302" in CafArchive(output).objects
    with pytest.raises(ValueError, match="identities"):
        CafFloatMultiplexerCopies(
            packed(
                xml.replace(
                    b"<string>Unrelated graph metadata</string>",
                    marker.replace(b"4194297", b"4194298"),
                )
            )
        ).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="562"', 'classid="561"'),
        ('classid="562" classVersion="1.0"', 'classid="562" classVersion="2.0"'),
        ('set="432">14', 'set="432">15'),
        ('set="432">14', 'set="433">14'),
        (
            prop(
                2381,
                "<listof><unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort></listof>",
            ),
            prop(
                2381,
                "<listof><unsignedShort>0</unsignedShort><unsignedShort>1</unsignedShort></listof>",
            ),
        ),
        ('<property id="2381">', '<property id="2381" extra="yes">'),
        ('<property id="2381"><data><listof>', '<property id="2381"><data><listof unknown="yes">'),
        (
            prop(3122, "<unsignedShort>1</unsignedShort>"),
            prop(3122, "<unsignedShort>0</unsignedShort>"),
        ),
        (
            prop(3122, "<unsignedShort>1</unsignedShort>"),
            prop(3122, "<unsignedInt>1</unsignedInt>"),
        ),
        ('classid="530"', 'classid="526"'),
        ('<BACoid id="5">12', '<BACoid id="2">12'),
        ('<enum set="509">961</enum>', '<enum set="509">7000</enum>'),
        (
            '<property id="3365">',
            '<property id="3113"><data><boolean>false</boolean></data></property><property id="3365">',
        ),
        (
            '<property id="3670">',
            '<property id="518"><data><enum set="287">1</enum></data></property><property id="3670">',
        ),
        (
            '<property id="3373"><data><boolean>true</boolean></data></property>',
            '<property id="3373"><data><boolean>false</boolean></data></property>',
        ),
    ],
)
def test_unknown_float_multiplexer_shape_refused_without_changing_original(old, new):
    xml = CafArchive(example()).xml.decode()
    assert old != new and old in xml
    original = packed(xml.replace(old, new, 1))
    c = CafFloatMultiplexerCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_mixed_fixture_retains_prior_families_and_fresh_typed_output():
    c = CafFloatMultiplexerCopies(mixed_example())
    ref = "8-1/575_1"
    s = c.inspect(ref, ref + ".562_130")
    assert (
        len(c.graph.diagram(ref)["blocks"]) == 13
        and s["new_instance"] == 135
        and s["new_output_ref"] == ref + ".562_135.2_136"
    )
