"""Authored enum constant/output pairs; no vendor source files or semantic grants."""

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_enum_copy import PROFILE, CafEnumCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_3"
PROTOTYPE = REF + ".568_10"


def example(value="10", *, default_set=647, states_text=351, count=7, zero=False):
    constant = (
        f'<object classid="568" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(75, '<BACoid id="568">10</BACoid>')
        + prop(3184, '<array><enum set="509">85</enum></array>')
        + prop(3670, '<enum set="432">12</enum>')
        + "</object>"
    )
    metadata = prop(74, f"<unsignedShort>{count}</unsignedShort>") + prop(
        931, f'<enum set="802">{states_text}</enum>'
    )
    default = prop(3113, f'<enum set="{default_set}">{value}</enum>') if value is not None else ""
    output = (
        f'<object classid="529" classVersion="1.0" ref="{PROTOTYPE}.19_11" objectid="11">'
        + prop(32527, f"<string>{PROTOTYPE}.19_11</string>")
        + metadata
        + prop(75, '<BACoid id="19">11</BACoid>')
        + default
        + prop(3365, '<enum set="509">85</enum>')
        + "</object>"
    )
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    parent = (
        f'<object classid="536" classVersion="1.0" ref="{REF}" objectid="3">'
        + prop(
            3375,
            '<array><BACoid id="568">10</BACoid><BACoid id="19">20</BACoid><BACoid id="19">30</BACoid></array>',
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
            + record("<boolean>false</boolean>", "<string>Keep &amp; retain</string>")
            + "</listof>",
        )
        + prop(9999, "<opaque><string>Retain source metadata</string></opaque>")
        + "</object>"
    )
    targets = "".join(
        f'<object classid="529" classVersion="1.0" ref="{REF}.19_{n}" objectid="{n}">'
        + prop(75, f'<BACoid id="19">{n}</BACoid>')
        + metadata
        + default
        + prop(2390, "<string>Authored enum target</string>")
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
    """Three authored constant families in one existing diagram."""
    from tests.test_caf_boolean_copy import mixed_example as previous
    from tests.test_caf_constant_copy import REF as FREF

    xml = CafArchive(previous()).xml.decode()
    enum = CafArchive(example()).xml.decode()
    start = enum.index('<object classid="568"')
    end = enum.index(f'<object classid="529" classVersion="1.0" ref="{REF}.19_20"')
    pair = (
        enum[start:end]
        .replace(REF, FREF)
        .replace(".568_10", ".568_50")
        .replace(".19_11", ".19_51")
        .replace('objectid="10"', 'objectid="50"')
        .replace('objectid="11"', 'objectid="51"')
        .replace('id="568">10<', 'id="568">50<')
        .replace('id="19">11<', 'id="19">51<')
    )
    xml = xml.replace(
        '<BACoid id="552">40</BACoid></array>',
        '<BACoid id="552">40</BACoid><BACoid id="568">50</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2, 3), shorts(0, 1, 2, 3, 4), 1)
    old = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    xml = xml.replace(old * 4, old * 5, 1).replace("</objects>", pair + "</objects>")
    return packed(xml, zero=True)


@pytest.mark.parametrize(
    "value,default_set,states_text,count",
    [
        ("10", 647, 351, 7),
        ("6", 351, 351, 7),
        ("2", 886, 886, 11),
        ("0", 405, 405, 7),
        (None, 647, 351, 7),
        ("4294967295", 647, 351, 65535),
    ],
)
@pytest.mark.parametrize("zero", [False, True])
def test_independent_exact_enum_pair_metadata_and_existing_connection(
    value, default_set, states_text, count, zero
):
    original = example(
        value, default_set=default_set, states_text=states_text, count=count, zero=zero
    )
    c = CafEnumCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="568"')
    end = xml.index(f'<object classid="529" classVersion="1.0" ref="{REF}.19_20"')
    pair = (
        xml[start:end]
        .replace(".568_10", ".568_31")
        .replace(".19_11", ".19_32")
        .replace('objectid="10"', 'objectid="31"')
        .replace('objectid="11"', 'objectid="32"')
        .replace('id="568">10<', 'id="568">31<')
        .replace('id="19">11<', 'id="19">32<')
    )
    expected = xml.replace(
        '<BACoid id="19">30</BACoid></array>',
        '<BACoid id="19">30</BACoid><BACoid id="568">31</BACoid></array>',
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
        s["profile"] == PROFILE and s["recorded_value"] == value and s["standard_name_code"] == 12
    )
    assert s["new_ref"] == REF + ".568_31" and s["new_output_ref"] == REF + ".568_31.19_32"
    assert (
        s["number_of_states"] == count
        and s["states_text_code"] == states_text
        and s["states_text_encoding_set"] == 802
    )
    assert s["default_encoding_set"] == (default_set if value is not None else None)
    assert s["enum_semantics_verified"] is False and report["controller_write"] is False
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert report["output_sha256"] == sha(output)
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
    connected, _ = CafGraph(output).add_connections(
        [
            {
                "diagram_ref": REF,
                "prototype_diagram_ref": REF,
                "prototype_wire_index": 0,
                "prototype_old": [0, 85, 1, 513],
                "source_ref": s["new_ref"],
                "target_ref": REF + ".19_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(connected).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafEnumCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".568_33.19_34" in CafArchive(second).objects


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="568"', 'classid="552"'),
        ('classid="529"', 'classid="531"'),
        ('classid="568" classVersion="1.0"', 'classid="568" classVersion="2.0"'),
        ('classid="529" classVersion="1.0"', 'classid="529" classVersion="2.0"'),
        ('id="568">10', 'id="552">10'),
        ('id="19">11', 'id="5">11'),
        ('set="432">12', 'set="432">13'),
        ('set="432">12', 'set="433">12'),
        ('set="802">351', 'set="802">999'),
        ('set="802">351', 'set="803">351'),
        ('set="647">10', 'set="999">10'),
        ('set="647">10', 'set="647">-1'),
        ('set="647">10', 'set="647">4294967296'),
        ('set="647">10', 'set="647">01'),
        ('set="647">10', 'set="647">1.0'),
        ("<unsignedShort>7</unsignedShort>", "<unsignedLong>7</unsignedLong>"),
        ("<unsignedShort>7</unsignedShort>", "<unsignedShort>65536</unsignedShort>"),
        ('<enum set="647">10</enum>', '<enum set="647"><![CDATA[10]]></enum>'),
        ('<property id="74">', '<property id="74" unknown="yes">'),
        ('<property id="931"><data><enum set="802">351</enum></data></property>', ""),
    ],
)
def test_unknown_enum_schema_or_unsigned_representation_is_refused(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    c = CafEnumCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original
