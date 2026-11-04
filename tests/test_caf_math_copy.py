"""Independent authored Math subtrees; no physical/vendor acceptance fixtures."""

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_math_copy import PROFILE, CafMathCopies
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_4"
PROTOTYPE = REF + ".561_10"
ORDERS = ((85, 7000, 7001), (85, 7000, 7002, 7001), (7002, 85, 7000, 7001), (85, 7002, 7000, 7001))
CASES = [
    (s, n, ORDERS[0]) for s, n in ((12, 42), (13, 43), (14, 41), (15, 40), (17, 58), (18, 59))
] + [(15, 40, ORDERS[1]), (17, 58, ORDERS[2]), (17, 58, ORDERS[3])]


def example(*, setup=17, standard=58, order=ORDERS[0], defaults="metadata", zero=False):
    exposed = [7000, 7001, 85] + ([7002] if 7002 in order else [])
    parent = (
        f'<object classid="561" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(75, '<BACoid id="561">10</BACoid>')
        + prop(518, f'<enum set="288">{setup}</enum>')
        + prop(
            3184, "<array>" + "".join(f'<enum set="509">{p}</enum>' for p in exposed) + "</array>"
        )
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    children = ""
    for instance, port in enumerate(order, 11):
        ref = f"{PROTOTYPE}.2_{instance}"
        children += (
            f'<object classid="{527 if port == 85 else 526}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(32527, f"<string>{ref}</string>")
            + prop(75, f'<BACoid id="2">{instance}</BACoid>')
            + (
                prop(3113, "<float>100.000000</float>")
                if port == 7000 and defaults == "plain"
                else ""
            )
            + (
                prop(661, '<enum set="0">9</enum>') + prop(3113, "<float>0.002000</float>")
                if port == 7001 and defaults == "metadata"
                else ""
            )
            + (
                prop(3113, "<float>1.500000</float>")
                if port == 7001 and defaults == "plain"
                else ""
            )
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
            '<array><BACoid id="561">10</BACoid><BACoid id="2">20</BACoid><BACoid id="2">30</BACoid></array>',
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
        f'<object classid="527" classVersion="1.0" ref="{REF}.2_{n}" objectid="{n}">'
        + prop(75, f'<BACoid id="2">{n}</BACoid>')
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
    from tests.test_caf_comparison_copy import mixed_example as previous
    from tests.test_caf_constant_copy import REF as FREF

    xml = CafArchive(previous()).xml.decode()
    math = CafArchive(example(order=ORDERS[2])).xml.decode()
    start = math.index('<object classid="561"')
    end = math.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    subtree = math[start:end].replace(REF, FREF).replace(".561_10", ".561_70")
    for typ, old, new in [(561, 10, 70), (2, 11, 71), (2, 12, 72), (2, 13, 73), (2, 14, 74)]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="560">60</BACoid></array>',
        '<BACoid id="560">60</BACoid><BACoid id="561">70</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2, 3, 4, 5), shorts(0, 1, 2, 3, 4, 5, 6), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 6, position * 7, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


@pytest.mark.parametrize("setup,standard,order", CASES)
@pytest.mark.parametrize("defaults", ["omitted", "plain", "metadata"])
def test_exact_complete_xml_variable_children_output_position_and_existing_connection(
    setup, standard, order, defaults
):
    original = example(setup=setup, standard=standard, order=order, defaults=defaults, zero=True)
    c = CafMathCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="561"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    clone = xml[start:end].replace(".561_10", ".561_31")
    for typ, old, new in [(561, 10, 31), *[(2, i, i + 21) for i in range(11, 11 + len(order))]]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="2">30</BACoid></array>',
        '<BACoid id="2">30</BACoid><BACoid id="561">31</BACoid></array>',
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
        and s["new_output_ref"] == s["new_ref"] + f".2_{32 + output_index}"
    )
    assert report["new_output_sha256"] == report["new_child_sha256"][output_index]
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    ) and report["output_sha256"] == sha(output)
    assert next(r for r in s["children"] if r["port"] == 7000)["recorded_default"] == (
        "100.000000" if defaults == "plain" else None
    )
    assert next(r for r in s["children"] if r["port"] == 7001)["recorded_metadata_661"] == (
        "9" if defaults == "metadata" else None
    )
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
                "target_ref": REF + ".2_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(linked).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafMathCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + f".561_{32 + len(order)}" in CafArchive(second).objects


@pytest.mark.parametrize("order", [ORDERS[0], ORDERS[2]])
def test_exact_last_available_ids_and_one_slot_too_few(order):
    count = len(order) + 1
    first = 4194303 - count
    xml = CafArchive(example(order=order)).xml
    maximum = b'<BACoid id="2">' + str(first - 1).encode() + b"</BACoid>"
    c = CafMathCopies(packed(xml.replace(b"<string>Unrelated graph metadata</string>", maximum)))
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == first
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + ".2_4194302" in CafArchive(output).objects
    bad = CafMathCopies(
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
        ('classid="561"', 'classid="560"'),
        ('classid="561" classVersion="1.0"', 'classid="561" classVersion="2.0"'),
        ('set="288">17', 'set="288">18'),
        ('set="432">58', 'set="432">59'),
        ('set="288">17', 'set="287">17'),
        ('classid="526"', 'classid="528"'),
        ('classid="527"', 'classid="531"'),
        ('<BACoid id="2">11', '<BACoid id="5">11'),
        ('<enum set="509">7000</enum>', '<enum set="509">7001</enum>'),
        ('<enum set="433">0</enum>', '<enum set="433">1</enum>'),
        ('<enum set="433">0</enum>', '<enum set="432">0</enum>'),
        ("<float>0.002000</float>", "<float>NaN</float>"),
        ("<float>0.002000</float>", "<double>0.002000</double>"),
        ('<enum set="0">9</enum>', '<enum set="1">9</enum>'),
        ('<enum set="0">9</enum>', '<enum set="0">4294967296</enum>'),
        ('<property id="518">', '<property id="518" unknown="yes">'),
        (
            '<property id="3373"><data><boolean>true</boolean></data></property>',
            '<property id="3373"><data><boolean>false</boolean></data></property>',
        ),
    ],
)
def test_unknown_math_shape_is_refused_without_changing_original(old, new):
    original = packed(CafArchive(example(order=ORDERS[2])).xml.decode().replace(old, new, 1))
    c = CafMathCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_mixed_fixture_retains_all_existing_families_and_actual_output_child():
    c = CafMathCopies(mixed_example())
    ref = "8-1/575_1"
    s = c.inspect(ref, ref + ".561_70")
    assert [b["class_id"] for b in c.graph.diagram(ref)["blocks"]] == [
        "551",
        "527",
        "527",
        "552",
        "568",
        "560",
        "561",
    ]
    assert s["children"][0]["port"] == 7002 and s["new_output_instance"] == s["new_instance"] + 2
