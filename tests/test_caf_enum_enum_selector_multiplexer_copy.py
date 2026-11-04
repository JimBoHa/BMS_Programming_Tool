"""Authored Enum I/O / Enum selector records; no controller programs distributed."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_enum_enum_selector_multiplexer_copy import (
    PROFILE,
    CafEnumEnumSelectorMultiplexerCopies,
)
from bms_tool.caf_enum_multiplexer_copy import CafEnumMultiplexerCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts
from tests.test_caf_float_multiplexer_copy import PROTOTYPE, REF, options
from tests.test_caf_float_multiplexer_copy import example as float_example

CHILDREN = [(529, 19, 11, 85), (528, 19, 12, 961), (528, 19, 13, 7000), (528, 19, 14, 7001)]


def example(*, zero=False):
    parent = (
        f'<object classid="562" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="562">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(2381, "<listof>" + shorts(0, 1, 0, 0) + "</listof>")
        + prop(3122, "<unsignedShort>2</unsignedShort>")
        + prop(
            3184,
            "<array>"
            + "".join(f'<enum set="509">{n}</enum>' for n in [961, 7000, 7001, 85])
            + "</array>",
        )
        + prop(3670, '<enum set="432">17</enum>')
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
            + prop(74, f"<unsignedShort>{4 if port == 961 else 2}</unsignedShort>")
            + prop(931, f'<enum set="802">{345 if port == 961 else 418}</enum>')
            + (prop(3670, '<enum set="433">0</enum>') if port == 961 else "")
            + "</object>"
        )
    xml = CafArchive(float_example()).xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    return packed(xml[:start] + parent + children + xml[end:], zero=zero)


@pytest.mark.parametrize("zero", [False, True])
def test_complete_independent_xml_distinct_selector_metadata_all_omissions_and_zip(zero):
    original = example(zero=zero)
    c = CafEnumEnumSelectorMultiplexerCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    clone = xml[start:end].replace(".562_10", ".562_31")
    for typ, old, new in [(562, 10, 31), (19, 11, 32), (19, 12, 33), (19, 13, 34), (19, 14, 35)]:
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
    )
    expected = expected.replace(shorts(0, 1, 2), shorts(0, 3, 1, 2), 1)
    pos = record("<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>")
    moved = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(pos * 3, pos * 3 + moved, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode() and c.archive.original == original
    assert (
        s["profile"] == PROFILE
        and s["object_count"] == 5
        and s["setup_code"] is None
        and s["standard_name_code"] == 17
    )
    assert (
        s["recorded_property_2381"] == ["0", "1", "0", "0"] and s["recorded_property_3122"] == "2"
    )
    assert (
        not s["operator_meaning_verified"]
        and not s["multiplexer_semantics_verified"]
        and not s["enum_semantics_verified"]
    )
    assert [
        (r["class_id"], r["bacnet_type"], r["port"], r["direction"]) for r in s["children"]
    ] == [
        ("529", 19, 85, "output"),
        ("528", 19, 961, "input"),
        ("528", 19, 7000, "input"),
        ("528", 19, 7001, "input"),
    ]
    assert [r["number_of_states"] for r in s["children"]] == [2, 4, 2, 2]
    assert [r["states_text_code"] for r in s["children"]] == [418, 345, 418, 418]
    for i, r in enumerate(s["children"]):
        assert r["exposed"] and r["recorded_metadata_661"] is None and r["recorded_default"] is None
        assert r["default_encoding_set"] is None and r["states_text_encoding_set"] == 802
        assert r["recorded_standard_name_code"] == (0 if i == 1 else None)
    assert s["new_output_ref"] == REF + ".562_31.19_32"
    assert report["new_output_sha256"] == report["new_child_sha256"][0]
    assert report["output_sha256"] == sha(output)
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert (
        not report["controller_write"]
        and not report["field_transfer_enabled"]
        and not report["vendor_acceptance_verified"]
    )
    assert CafGraph(a).diagram(REF)["connections"] == c.graph.diagram(REF)["connections"]
    for attr in [
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "extra",
        "internal_attr",
        "external_attr",
        "create_system",
    ]:
        assert getattr(a.info, attr) == getattr(c.archive.info, attr)
    assert a.comment == c.archive.comment


def test_repeated_creation_and_last_five_ids_keep_enum_identity_domains():
    c = CafEnumEnumSelectorMultiplexerCopies(example())
    first, _ = c.compile(**options(c))
    second = CafEnumEnumSelectorMultiplexerCopies(first)
    output, _ = second.compile(**options(second))
    assert REF + ".562_36.19_40" in CafArchive(output).objects
    xml = c.archive.xml.replace(
        b"<string>Unrelated graph metadata</string>", b'<BACoid id="2">4194297</BACoid>'
    )
    boundary = CafEnumEnumSelectorMultiplexerCopies(packed(xml))
    last, _ = boundary.compile(**options(boundary))
    assert REF + ".562_4194298.19_4194302" in CafArchive(last).objects
    with pytest.raises(ValueError, match="identities"):
        CafEnumEnumSelectorMultiplexerCopies(packed(xml.replace(b"4194297", b"4194298"))).inspect(
            REF, PROTOTYPE
        )
    with pytest.raises(ValueError):
        CafEnumMultiplexerCopies(example()).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="562"', 'classid="561"'),
        ('classid="562" classVersion="1.0"', 'classid="562" classVersion="2.0"'),
        ('set="432">17', 'set="432">16'),
        ('set="432">17', 'set="432">19'),
        ('set="432">17', 'set="433">17'),
        (shorts(0, 1, 0, 0), shorts(0, 1, 0, 1)),
        (shorts(0, 1, 0, 0), shorts(0, 1, 0)),
        (
            prop(3122, "<unsignedShort>2</unsignedShort>"),
            prop(3122, "<unsignedShort>1</unsignedShort>"),
        ),
        ('<property id="2381">', '<property id="2381" extra="yes">'),
        ("<listof><unsignedShort>0", '<listof unknown="yes"><unsignedShort>0'),
        ('classid="529"', 'classid="527"'),
        ('classid="528"', 'classid="530"'),
        ('<BACoid id="19">12', '<BACoid id="5">12'),
        ('<enum set="509">961</enum>', '<enum set="509">7000</enum>'),
        ('<enum set="802">345</enum>', '<enum set="802">418</enum>'),
        ('<enum set="802">418</enum>', '<enum set="802">345</enum>'),
        ('<enum set="802">345</enum>', '<enum set="803">345</enum>'),
        (
            prop(74, "<unsignedShort>4</unsignedShort>"),
            prop(74, "<unsignedShort>2</unsignedShort>"),
        ),
        (
            prop(74, "<unsignedShort>2</unsignedShort>"),
            prop(74, "<unsignedShort>4</unsignedShort>"),
        ),
        ('<enum set="433">0</enum>', '<enum set="433">1</enum>'),
        (prop(3670, '<enum set="433">0</enum>'), ""),
        ('<property id="3365">', prop(3113, '<enum set="647">0</enum>') + '<property id="3365">'),
        ('<property id="74">', '<property id="74" extra="yes">'),
        (prop(3373, "<boolean>true</boolean>"), prop(3373, "<boolean>false</boolean>")),
    ],
)
def test_unknown_shapes_are_refused_without_changing_the_original(old, new):
    xml = CafArchive(example()).xml.decode()
    assert old in xml and old != new
    original = packed(xml.replace(old, new, 1))
    c = CafEnumEnumSelectorMultiplexerCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def mixed_example():
    from tests.test_caf_constant_copy import REF as FREF
    from tests.test_caf_enum_multiplexer_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    own = CafArchive(example(zero=True)).xml.decode()
    start = own.index('<object classid="562"')
    end = own.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    subtree = own[start:end].replace(REF, FREF).replace(".562_10", ".562_160")
    for typ, old, new in [(562, 10, 160), *[(typ, n, n + 150) for _, typ, n, _ in CHILDREN]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="562">150</BACoid></array>',
        '<BACoid id="562">150</BACoid><BACoid id="562">160</BACoid></array>',
        1,
    )
    xml = xml.replace(shorts(*range(15)), shorts(*range(16)), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 15, position * 16, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


def test_mixed_four_profile_facade_keeps_distinct_selector_and_output_domains():
    from bms_tool.caf_float_multiplexer_service import CafFloatMultiplexerService

    c = CafFloatMultiplexerService(mixed_example())
    ref = "8-1/575_1"
    for instance, standard, typ in [(130, 14, 2), (140, 15, 2), (150, 16, 19), (160, 17, 19)]:
        s = c.inspect(ref, ref + f".562_{instance}")
        assert (
            s["standard_name_code"] == standard
            and s["new_output_ref"] == ref + f".562_165.{typ}_166"
        )
        output, report = c.compile(
            diagram_ref=ref,
            prototype_ref=ref + f".562_{instance}",
            selection_sha256=s["selection_sha256"],
            **s["suggested_position"],
        )
        assert report["selection"] == s and len(CafGraph(output).diagram(ref)["blocks"]) == 17
        assert not report["vendor_acceptance_verified"]
