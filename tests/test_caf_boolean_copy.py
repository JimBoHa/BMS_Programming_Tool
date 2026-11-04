"""Independently authored Boolean constant/output examples, not vendor files."""

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_boolean_copy import PROFILE, CafBooleanCopies
from bms_tool.caf_constant_copy import CafConstantCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import example as float_example
from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_2"
PROTOTYPE = REF + ".552_10"


def example(value="true", *, zero=False):
    constant = (
        f'<object classid="552" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(75, '<BACoid id="552">10</BACoid>')
        + prop(3184, '<array><enum set="509">85</enum></array>')
        + prop(3670, '<enum set="432">13</enum>')
        + "</object>"
    )
    output = (
        f'<object classid="531" classVersion="1.0" ref="{PROTOTYPE}.5_11" objectid="11">'
        + prop(32527, f"<string>{PROTOTYPE}.5_11</string>")
        + prop(75, '<BACoid id="5">11</BACoid>')
        + prop(3113, f"<boolean>{value}</boolean>")
        + prop(3365, '<enum set="509">85</enum>')
        + "</object>"
    )
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    parent = (
        f'<object classid="536" classVersion="1.0" ref="{REF}" objectid="2">'
        + prop(
            3375,
            '<array><BACoid id="552">10</BACoid><BACoid id="558">20</BACoid><BACoid id="558">30</BACoid></array>',
        )
        + prop(3117, "<array>" + shorts(0, 1, 2) + "</array>")
        + prop(3383, "<listof>" + position * 3 + "</listof>")
        + prop(
            3118,
            "<array>"
            + record(*[f"<unsignedShort>{n}</unsignedShort>" for n in (0, 85, 1, 513)])
            + "</array>",
        )
        + prop(
            3384,
            "<listof>"
            + record("<boolean>0</boolean>", "<string>Preserve &amp; retain</string>")
            + "</listof>",
        )
        + prop(9999, "<opaque><string>Unknown metadata stays exact</string></opaque>")
        + "</object>"
    )
    targets = "".join(
        f'<object classid="558" classVersion="1.0" ref="{REF}.558_{n}" objectid="{n}">'
        + prop(75, f'<BACoid id="558">{n}</BACoid>')
        + prop(2390, "<string>Authored Boolean target</string>")
        + prop(3184, '<array><enum set="509">513</enum></array>')
        + "</object>"
        for n in (20, 30)
    )
    return packed(
        f'<objects xmlns="{NS}">{parent}{constant}{output}{targets}<jobInfo /></objects>', zero=zero
    )


def options(c, **updates):
    source = c.inspect(REF, PROTOTYPE)
    return {
        "diagram_ref": REF,
        "prototype_ref": PROTOTYPE,
        "selection_sha256": source["selection_sha256"],
        "x": "81.000",
        "y": "+42.000",
        **updates,
    }


def mixed_example():
    """Add an authored Boolean prototype to the ordinary authored Float diagram."""
    from tests.test_caf_constant_copy import REF as FREF

    float_xml = CafArchive(float_example(zero=True)).xml.decode()
    boolean = CafArchive(example()).xml.decode()
    start = boolean.index('<object classid="552"')
    end = boolean.index('<object classid="558"', start)
    pair = (
        boolean[start:end]
        .replace(REF, FREF)
        .replace(".552_10", ".552_40")
        .replace(".5_11", ".5_41")
        .replace('objectid="10"', 'objectid="40"')
        .replace('objectid="11"', 'objectid="41"')
        .replace('id="552">10<', 'id="552">40<')
        .replace('id="5">11<', 'id="5">41<')
    )
    float_xml = float_xml.replace(
        '<BACoid id="2">30</BACoid></array>',
        '<BACoid id="2">30</BACoid><BACoid id="552">40</BACoid></array>',
        1,
    )
    float_xml = float_xml.replace(shorts(0, 1, 2), shorts(0, 1, 2, 3), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    float_xml = float_xml.replace(position * 3, position * 4, 1).replace(
        "</objects>", pair + "</objects>"
    )
    return packed(float_xml, zero=True)


@pytest.mark.parametrize("value", ["true", "false", "0", "1"])
@pytest.mark.parametrize("zero", [False, True])
def test_independent_exact_boolean_pair_creation_and_existing_connection(value, zero):
    original = example(value, zero=zero)
    c = CafBooleanCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="552"')
    end = xml.index('<object classid="558"', start)
    pair = (
        xml[start:end]
        .replace(".552_10", ".552_31")
        .replace(".5_11", ".5_32")
        .replace('objectid="10"', 'objectid="31"')
        .replace('objectid="11"', 'objectid="32"')
        .replace('id="552">10<', 'id="552">31<')
        .replace('id="5">11<', 'id="5">32<')
    )
    expected = xml.replace(
        '<BACoid id="558">30</BACoid></array>',
        '<BACoid id="558">30</BACoid><BACoid id="552">31</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2), shorts(0, 3, 1, 2), 1)
    old = record("<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>")
    new = record(
        "<float>81.000</float>", "<float>+42.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(old * 3, old * 3 + new, 1).replace(
        "</objects>", pair + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode()
    assert c.archive.original == original
    assert (
        s["profile"] == PROFILE and s["recorded_value"] == value and s["standard_name_code"] == 13
    )
    assert s["new_ref"] == REF + ".552_31" and s["new_output_ref"] == REF + ".552_31.5_32"
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert report["output_sha256"] == sha(output)
    for name in (
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "extra",
        "internal_attr",
        "external_attr",
        "create_system",
    ):
        assert getattr(a.info, name) == getattr(c.archive.info, name)
    assert a.comment == c.archive.comment
    connected, _ = CafGraph(output).add_connections(
        [
            {
                "diagram_ref": REF,
                "prototype_diagram_ref": REF,
                "prototype_wire_index": 0,
                "prototype_old": [0, 85, 1, 513],
                "source_ref": s["new_ref"],
                "target_ref": REF + ".558_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(connected).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafBooleanCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".552_33.5_34" in CafArchive(second).objects


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="552"', 'classid="551"'),
        ('classid="531"', 'classid="527"'),
        ('classid="552" classVersion="1.0"', 'classid="552" classVersion="2.0"'),
        ('classid="531" classVersion="1.0"', 'classid="531" classVersion="2.0"'),
        ('id="552">10', 'id="551">10'),
        ('id="5">11', 'id="2">11'),
        ('set="432">13', 'set="432">11'),
        ('set="432">13', 'set="433">13'),
        ("<boolean>true</boolean>", "<boolean>True</boolean>"),
        ("<boolean>true</boolean>", "<boolean>2</boolean>"),
        ("<boolean>true</boolean>", "<boolean />"),
        ("<boolean>true</boolean>", "<float>1</float>"),
        ("<boolean>true</boolean>", "<boolean><![CDATA[true]]></boolean>"),
        ('<property id="3113">', '<property id="3113" unknown="yes">'),
        ('<property id="3113"><data><boolean>true</boolean></data></property>', ""),
        (
            '<property id="3113"><data><boolean>true</boolean></data></property>',
            prop(3113, "<boolean>true</boolean>") + prop(117, '<enum set="507">98</enum>'),
        ),
    ],
)
def test_unknown_boolean_schema_or_cross_type_configuration_refused(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    c = CafBooleanCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_mixed_diagram_keeps_float_and_boolean_profiles_distinct():
    from tests.test_caf_constant_copy import PROTOTYPE as FPROTO
    from tests.test_caf_constant_copy import REF as FREF

    original = mixed_example()
    f = CafConstantCopies(original)
    b = CafBooleanCopies(original)
    fs = f.inspect(FREF, FPROTO)
    bs = b.inspect(FREF, FREF + ".552_40")
    assert fs["new_ref"] == FREF + ".551_42" and bs["new_ref"] == FREF + ".552_42"
    for c, proto in ((f, FREF + ".552_40"), (b, FPROTO)):
        with pytest.raises(ValueError):
            c.inspect(FREF, proto)
    with pytest.raises(ValueError, match="source changed"):
        b.compile(
            diagram_ref=FREF,
            prototype_ref=FREF + ".552_40",
            selection_sha256=fs["selection_sha256"],
            x="1",
            y="2",
        )
