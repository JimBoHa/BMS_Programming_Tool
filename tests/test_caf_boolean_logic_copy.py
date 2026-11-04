"""Independent authored Boolean logic subtrees; no physical/vendor acceptance fixtures."""

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_boolean_logic_copy import PROFILE, CafBooleanLogicCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_4"
PROTOTYPE = REF + ".559_10"
ORDERS = ((85, 7000, 7001), (7002, 85, 7000, 7001), (85, 7002, 7000, 7001))
CASES = [(v, v + 23, ORDERS[0]) for v in (1, 2, 3)] + [(1, 24, ORDERS[1]), (1, 24, ORDERS[2])]


def example(*, setup=1, standard=24, order=ORDERS[0], zero=False):
    exposed = [7000, 7001, 85] + ([7002] if 7002 in order else [])
    parent = (
        f'<object classid="559" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(75, '<BACoid id="559">10</BACoid>')
        + prop(518, f'<enum set="286">{setup}</enum>')
        + prop(
            3184, "<array>" + "".join(f'<enum set="509">{p}</enum>' for p in exposed) + "</array>"
        )
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    children = ""
    for instance, port in enumerate(order, 11):
        ref = f"{PROTOTYPE}.5_{instance}"
        children += (
            f'<object classid="{531 if port == 85 else 530}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(32527, f"<string>{ref}</string>")
            + prop(75, f'<BACoid id="5">{instance}</BACoid>')
            + prop(3365, f'<enum set="509">{port}</enum>')
            + (prop(3670, '<enum set="433">0</enum>') if port == 7002 else "")
            + "</object>"
        )
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    graph = (
        f'<object classid="536" classVersion="1.0" ref="{REF}" objectid="4">'
        + prop(
            3375,
            '<array><BACoid id="559">10</BACoid><BACoid id="5">20</BACoid><BACoid id="5">30</BACoid></array>',
        )
        + prop(3117, "<array>" + shorts(0, 1, 2) + "</array>")
        + prop(3383, "<listof>" + position * 3 + "</listof>")
        + prop(
            3118,
            "<array>"
            + record(*[f"<unsignedShort>{v}</unsignedShort>" for v in (0, 85, 1, 513)])
            + "</array>",
        )
        + prop(
            3384,
            "<listof>"
            + record("<boolean>true</boolean>", "<string>Retain &amp; preserve</string>")
            + "</listof>",
        )
        + prop(3373, "<boolean>true</boolean>")
        + prop(9999, "<opaque><string>Unrelated graph metadata</string></opaque>")
        + "</object>"
    )
    targets = "".join(
        f'<object classid="530" classVersion="1.0" ref="{REF}.5_{n}" objectid="{n}">'
        + prop(75, f'<BACoid id="5">{n}</BACoid>')
        + prop(2390, "<string>Authored target</string>")
        + prop(3184, '<array><enum set="509">513</enum></array>')
        + "</object>"
        for n in (20, 30)
    )
    return packed(
        f'<objects xmlns="{NS}">{graph}{parent}{children}{targets}<jobInfo /></objects>', zero=zero
    )


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
    from tests.test_caf_timer_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    own = CafArchive(example(order=ORDERS[1])).xml.decode()
    start = own.index('<object classid="559"')
    end = own.index(f'<object classid="530" classVersion="1.0" ref="{REF}.5_20"')
    subtree = own[start:end].replace(REF, FREF).replace(".559_10", ".559_100")
    for typ, old, new in [(559, 10, 100), *[(5, i, i + 90) for i in range(11, 15)]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="558">90</BACoid></array>',
        '<BACoid id="558">90</BACoid><BACoid id="559">100</BACoid></array>',
        1,
    )
    xml = xml.replace(shorts(0, 1, 2, 3, 4, 5, 6, 7, 8), shorts(0, 1, 2, 3, 4, 5, 6, 7, 8, 9), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 9, position * 10, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


@pytest.mark.parametrize("setup,standard,order", CASES)
def test_exact_complete_xml_variable_children_output_position_and_existing_connection(
    setup, standard, order
):
    original = example(setup=setup, standard=standard, order=order, zero=True)
    c = CafBooleanLogicCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="559"')
    end = xml.index(f'<object classid="530" classVersion="1.0" ref="{REF}.5_20"')
    clone = xml[start:end].replace(".559_10", ".559_31")
    for typ, old, new in [(559, 10, 31), *[(5, i, i + 21) for i in range(11, 11 + len(order))]]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="5">30</BACoid></array>',
        '<BACoid id="5">30</BACoid><BACoid id="559">31</BACoid></array>',
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
    assert a.xml == expected.encode() and len(a.objects) == len(c.archive.objects) + len(order) + 1
    assert (
        c.archive.original == original
        and s["profile"] == PROFILE
        and s["object_count"] == len(order) + 1
    )
    assert s["operator_meaning_verified"] is False and [r["port"] for r in s["children"]] == list(
        order
    )
    output_index = order.index(85)
    assert (
        s["new_output_instance"] == 32 + output_index
        and s["new_output_ref"] == s["new_ref"] + f".5_{32 + output_index}"
    )
    assert report["new_output_sha256"] == report["new_child_sha256"][output_index]
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    ) and report["output_sha256"] == sha(output)
    assert all(
        r["recorded_default"] is None and r["recorded_metadata_661"] is None for r in s["children"]
    )
    assert [r["recorded_standard_name_code"] for r in s["children"]] == [
        0 if port == 7002 else None for port in order
    ]
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
    again = CafBooleanLogicCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + f".559_{32 + len(order)}" in CafArchive(second).objects


@pytest.mark.parametrize("order", [ORDERS[0], ORDERS[1]])
def test_exact_last_available_ids_and_one_slot_too_few(order):
    count = len(order) + 1
    first = 4194303 - count
    xml = CafArchive(example(order=order)).xml
    maximum = b'<BACoid id="5">' + str(first - 1).encode() + b"</BACoid>"
    c = CafBooleanLogicCopies(
        packed(xml.replace(b"<string>Unrelated graph metadata</string>", maximum))
    )
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == first
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + ".5_4194302" in CafArchive(output).objects
    bad = CafBooleanLogicCopies(
        packed(
            xml.replace(
                b"<string>Unrelated graph metadata</string>",
                maximum.replace(str(first - 1).encode(), str(first).encode()),
            )
        )
    )
    with pytest.raises(ValueError, match="identities"):
        bad.inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="559"', 'classid="560"'),
        ('classid="559" classVersion="1.0"', 'classid="559" classVersion="2.0"'),
        ('set="286">1', 'set="286">2'),
        ('set="432">24', 'set="432">25'),
        ('set="286">1', 'set="287">1'),
        ('classid="530"', 'classid="526"'),
        ('classid="531"', 'classid="530"'),
        ('<BACoid id="5">11', '<BACoid id="2">11'),
        ('<enum set="509">7000</enum>', '<enum set="509">7001</enum>'),
        ('<enum set="433">0</enum>', '<enum set="433">1</enum>'),
        ('<enum set="433">0</enum>', '<enum set="432">0</enum>'),
        ('<property id="518">', '<property id="518" unknown="yes">'),
        (
            '<property id="3365">',
            '<property id="3113"><data><boolean>false</boolean></data></property><property id="3365">',
        ),
        (
            '<property id="3373"><data><boolean>true</boolean></data></property>',
            '<property id="3373"><data><boolean>false</boolean></data></property>',
        ),
    ],
)
def test_unknown_boolean_logic_shape_refused_without_changing_original(old, new):
    original = packed(CafArchive(example(order=ORDERS[1])).xml.decode().replace(old, new, 1))
    c = CafBooleanLogicCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_large_profile_requires_setup_one_and_preserves_actual_output_in_mixed_fixture():
    for setup, standard in [(2, 25), (3, 26)]:
        with pytest.raises(ValueError):
            CafBooleanLogicCopies(example(setup=setup, standard=standard, order=ORDERS[1])).inspect(
                REF, PROTOTYPE
            )
    c = CafBooleanLogicCopies(mixed_example())
    ref = "8-1/575_1"
    s = c.inspect(ref, ref + ".559_100")
    assert len(c.graph.diagram(ref)["blocks"]) == 10
    assert s["children"][0]["port"] == 7002 and s["new_output_instance"] == s["new_instance"] + 2
