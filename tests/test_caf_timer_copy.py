"""Authored Timer subtrees and complete independent local-copy expectations."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_graph import CafGraph
from bms_tool.caf_timer_copy import PROFILE, CafTimerCopies
from bms_tool.moi_identity import seal, sha

from tests.test_caf_comparison_copy import REF
from tests.test_caf_comparison_copy import example as comparison
from tests.test_caf_constant_copy import packed, prop, record, shorts

PROTOTYPE = REF + ".558_10"
CHILDREN = [
    (531, 5, 11, 85),
    (530, 5, 12, 513),
    (530, 5, 13, 1082),
    (528, 19, 14, 518),
    (526, 2, 15, 1080),
    (528, 19, 16, 1083),
    (527, 2, 17, 1081),
]


def example(*, encoding=647, mode="2", duration="5.000000", zero=False):
    parent = (
        f'<object classid="558" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="558">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(
            3184,
            "<array>"
            + "".join(f'<enum set="509">{p}</enum>' for p in (513, 1080, 85))
            + "</array>",
        )
        + prop(3670, '<enum set="432">62</enum>')
        + "</object>"
    )
    children = ""
    for cid, typ, instance, port in CHILDREN:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        children += (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + prop(32527, f"<string>{ref}</string>")
            + (
                prop(74, f"<unsignedShort>{9 if port == 518 else 2}</unsignedShort>")
                + prop(931, f'<enum set="802">{21 if port == 518 else 22}</enum>')
                if typ == 19
                else ""
            )
            + (prop(3113, f'<enum set="{encoding}">{mode}</enum>') if port == 518 else "")
            + (
                prop(117, '<enum set="507">73</enum>') + prop(661, '<enum set="0">6</enum>')
                if typ == 2
                else ""
            )
            + (prop(3113, f"<float>{duration}</float>") if port == 1080 else "")
            + prop(3365, f'<enum set="509">{port}</enum>')
            + "</object>"
        )
    xml = CafArchive(comparison()).xml.decode()
    start = xml.index('<object classid="560"')
    end = xml.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    return packed(
        (xml[:start] + parent + children + xml[end:]).replace(
            '<BACoid id="560">10</BACoid>', '<BACoid id="558">10</BACoid>', 1
        ),
        zero=zero,
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
    from tests.test_caf_enum_comparison_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    timer = CafArchive(example()).xml.decode()
    start = timer.index('<object classid="558"')
    end = timer.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    subtree = timer[start:end].replace(REF, FREF).replace(".558_10", ".558_90")
    for typ, old, new in [(558, 10, 90), *[(t, i, i + 80) for _, t, i, _ in CHILDREN]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="560">80</BACoid></array>',
        '<BACoid id="560">80</BACoid><BACoid id="558">90</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2, 3, 4, 5, 6, 7), shorts(0, 1, 2, 3, 4, 5, 6, 7, 8), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 8, position * 9, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


@pytest.mark.parametrize("encoding", [647, 21])
@pytest.mark.parametrize("mode", ["2", "4"])
@pytest.mark.parametrize("duration", ["5.000000", "5"])
def test_exact_eight_object_xml_hidden_ports_both_outputs_and_existing_connection(
    encoding, mode, duration
):
    original = example(encoding=encoding, mode=mode, duration=duration, zero=True)
    c = CafTimerCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    out, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="558"')
    end = xml.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    clone = xml[start:end].replace(".558_10", ".558_31")
    for typ, old, new in [(558, 10, 31), *[(t, i, i + 21) for _, t, i, _ in CHILDREN]]:
        clone = (
            clone.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    expected = xml.replace(
        '<BACoid id="5">30</BACoid></array>',
        '<BACoid id="5">30</BACoid><BACoid id="558">31</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2), shorts(0, 3, 1, 2), 1)
    old = record("<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>")
    new = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(old * 3, old * 3 + new, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(out)
    assert a.xml == expected.encode() and len(a.objects) == 19 and c.archive.original == original
    assert s["profile"] == PROFILE and s["setup_code"] is None and s["object_count"] == 8
    assert s["timer_semantics_verified"] is False and s["enum_semantics_verified"] is False
    assert [r["port"] for r in s["children"]] == [85, 513, 1082, 518, 1080, 1083, 1081]
    assert [r["port"] for r in s["children"] if not r["exposed"]] == [1082, 518, 1083, 1081]
    assert [r["port"] for r in s["children"] if r["direction"] == "output"] == [85, 1081]
    assert (
        s["children"][3]["recorded_default"] == mode
        and s["children"][3]["default_encoding_set"] == encoding
    )
    assert s["children"][4]["recorded_default"] == duration and s["children"][4]["units_code"] == 73
    assert (
        s["children"][5]["recorded_default"] is None
        and s["children"][6]["recorded_default"] is None
    )
    assert (
        report["new_output_sha256"] == report["new_child_sha256"][0]
        and len(report["new_child_sha256"]) == 7
        and report["output_sha256"] == sha(out)
    )
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
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
    linked, _ = CafGraph(out).add_connections(
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
    again = CafTimerCopies(out)
    second, _ = again.compile(**options(again))
    assert REF + ".558_39.2_46" in CafArchive(second).objects


def test_last_eight_ids_fit_without_extending_allocation_ceiling():
    xml = CafArchive(example()).xml
    marker = b"<string>Unrelated graph metadata</string>"
    c = CafTimerCopies(packed(xml.replace(marker, b'<BACoid id="2">4194294</BACoid>')))
    s = c.inspect(REF, PROTOTYPE)
    out, _ = c.compile(**options(c))
    assert s["new_instance"] == 4194295 and s["new_ref"] + ".2_4194302" in CafArchive(out).objects
    with pytest.raises(ValueError, match="identities"):
        CafTimerCopies(packed(xml.replace(marker, b'<BACoid id="2">4194295</BACoid>'))).inspect(
            REF, PROTOTYPE
        )


def test_mode_code_is_preserved_as_opaque_uint32_not_inferred_enum_membership():
    c = CafTimerCopies(example(mode="4294967295"))
    s = c.inspect(REF, PROTOTYPE)
    out, _ = c.compile(**options(c))
    assert (
        s["children"][3]["recorded_default"] == "4294967295"
        and b'<enum set="647">4294967295</enum>' in CafArchive(out).xml
    )
    assert not s["enum_semantics_verified"] and not s["timer_semantics_verified"]


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="558" classVersion="1.0"', 'classid="558" classVersion="2.0"'),
        ('<enum set="432">62</enum>', '<enum set="432">63</enum>'),
        ('<enum set="509">513</enum>', '<enum set="509">1082</enum>'),
        ('classid="530"', 'classid="531"'),
        ('classid="527"', 'classid="526"'),
        ('<BACoid id="19">14', '<BACoid id="2">14'),
        ("<unsignedShort>9</unsignedShort>", "<unsignedShort>8</unsignedShort>"),
        ('<enum set="802">21</enum>', '<enum set="802">22</enum>'),
        ('<enum set="647">2</enum>', '<enum set="22">2</enum>'),
        ('<enum set="647">2</enum>', '<enum set="647">4294967296</enum>'),
        ('<enum set="507">73</enum>', '<enum set="507">72</enum>'),
        ('<enum set="507">73</enum>', '<enum set="508">73</enum>'),
        ('<enum set="0">6</enum>', '<enum set="0">5</enum>'),
        ("<float>5.000000</float>", "<float>NaN</float>"),
        ("<float>5.000000</float>", "<double>5.000000</double>"),
        ('<property id="3670">', '<property id="3670" unknown="yes">'),
    ],
)
def test_unknown_timer_schema_is_refused_without_touching_original(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    c = CafTimerCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_timer_mixed_fixture_retains_existing_families_and_hidden_second_output():
    c = CafTimerCopies(mixed_example())
    ref = "8-1/575_1"
    s = c.inspect(ref, ref + ".558_90")
    assert len(c.graph.diagram(ref)["blocks"]) == 9 and s["children"][-1]["port"] == 1081
    assert s["children"][-1]["direction"] == "output" and not s["children"][-1]["exposed"]
