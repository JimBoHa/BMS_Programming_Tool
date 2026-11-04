"""Independent authored Float Comparison templates, not manufacturer artifacts."""

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_comparison_copy import PROFILE, CafComparisonCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts

REF = "8-1/536_4"
PROTOTYPE = REF + ".560_10"


def example(*, setup=1, standard=28, expose=True, value="0.00999999978", zero=False):
    ports = [637, 50083, 50084, 85] if expose else [50083, 50084, 85]
    parent = (
        f'<object classid="560" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(75, '<BACoid id="560">10</BACoid>')
        + prop(518, f'<enum set="287">{setup}</enum>')
        + prop(3184, "<array>" + "".join(f'<enum set="509">{p}</enum>' for p in ports) + "</array>")
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    children = ""
    for cid, typ, instance, port in [
        (531, 5, 11, 85),
        (526, 2, 12, 50083),
        (526, 2, 13, 50084),
        (526, 2, 14, 637),
    ]:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        children += (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(32527, f"<string>{ref}</string>")
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + (
                prop(661, '<enum set="0">4</enum>') + prop(3113, f"<float>{value}</float>")
                if port == 50084 and value is not None
                else ""
            )
            + prop(3365, f'<enum set="509">{port}</enum>')
            + "</object>"
        )
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    graph = (
        f'<object classid="536" classVersion="1.0" ref="{REF}" objectid="4">'
        + prop(
            3375,
            '<array><BACoid id="560">10</BACoid><BACoid id="5">20</BACoid><BACoid id="5">30</BACoid></array>',
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
        + prop(9999, "<opaque><string>Unrelated graph metadata</string></opaque>")
        + "</object>"
    )
    targets = "".join(
        f'<object classid="531" classVersion="1.0" ref="{REF}.5_{n}" objectid="{n}">'
        + prop(75, f'<BACoid id="5">{n}</BACoid>')
        + prop(2390, "<string>Authored Boolean target</string>")
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
    from tests.test_caf_enum_creation import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    comparison = CafArchive(example()).xml.decode()
    start = comparison.index('<object classid="560"')
    end = comparison.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    subtree = comparison[start:end].replace(REF, FREF).replace(".560_10", ".560_60")
    for typ, old, new in [(560, 10, 60), (5, 11, 61), (2, 12, 62), (2, 13, 63), (2, 14, 64)]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="568">50</BACoid></array>',
        '<BACoid id="568">50</BACoid><BACoid id="560">60</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2, 3, 4), shorts(0, 1, 2, 3, 4, 5), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    xml = xml.replace(position * 5, position * 6, 1).replace("</objects>", subtree + "</objects>")
    return packed(xml, zero=True)


def test_exact_last_five_ids_fit_without_relaxing_the_two_id_allocator():
    xml = CafArchive(example()).xml.replace(
        b"<string>Unrelated graph metadata</string>", b'<BACoid id="2">4194297</BACoid>'
    )
    c = CafComparisonCopies(packed(xml))
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == 4194298
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + ".2_4194302" in CafArchive(output).objects


@pytest.mark.parametrize("setup,standard", [(1, 28), (2, 31), (3, 32)])
@pytest.mark.parametrize("expose", [True, False])
@pytest.mark.parametrize("value", ["0.00999999978", None])
def test_exact_independent_five_object_copy_and_existing_connection(setup, standard, expose, value):
    original = example(setup=setup, standard=standard, expose=expose, value=value, zero=True)
    c = CafComparisonCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="560"')
    end = xml.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    clone = xml[start:end].replace(".560_10", ".560_31")
    for typ, old, new in [(560, 10, 31), (5, 11, 32), (2, 12, 33), (2, 13, 34), (2, 14, 35)]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="5">30</BACoid></array>',
        '<BACoid id="5">30</BACoid><BACoid id="560">31</BACoid></array>',
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
    assert a.xml == expected.encode()
    assert len(a.objects) == 13
    assert c.archive.original == original and s["profile"] == PROFILE and s["object_count"] == 5
    assert s["operator_meaning_verified"] is False and [r["port"] for r in s["children"]] == [
        85,
        50083,
        50084,
        637,
    ]
    assert [r["new_instance"] for r in s["children"]] == [32, 33, 34, 35]
    assert s["children"][2]["recorded_default"] == value and s["children"][3]["exposed"] == expose
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    ) and report["output_sha256"] == sha(output)
    assert (
        report["new_output_sha256"] == report["new_child_sha256"][0]
        and len(report["new_child_sha256"]) == 4
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
                "target_ref": REF + ".5_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(linked).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafComparisonCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".560_36.2_40" in CafArchive(second).objects


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="560"', 'classid="561"'),
        ('classid="560" classVersion="1.0"', 'classid="560" classVersion="2.0"'),
        ('set="287">1', 'set="287">5'),
        ('set="432">28', 'set="432">32'),
        ('set="287">1', 'set="288">1'),
        ('classid="526"', 'classid="528"'),
        ('classid="531"', 'classid="529"'),
        ('id="5">11', 'id="19">11'),
        (
            'set="509">50083</enum></data></property></object>',
            'set="509">50084</enum></data></property></object>',
        ),
        ('<enum set="509">637</enum>', '<enum set="509">50083</enum>'),
        ("<float>0.00999999978</float>", "<float>NaN</float>"),
        ("<float>0.00999999978</float>", "<double>0.00999999978</double>"),
        ('<enum set="0">4</enum>', '<enum set="1">4</enum>'),
        ('<property id="661"><data><enum set="0">4</enum></data></property>', ""),
        ('<property id="518">', '<property id="518" unknown="yes">'),
        ("<string>Unrelated graph metadata</string>", '<BACoid id="2">4194298</BACoid>'),
    ],
)
def test_unknown_comparison_shape_or_five_id_exhaustion_refused(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    c = CafComparisonCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original
