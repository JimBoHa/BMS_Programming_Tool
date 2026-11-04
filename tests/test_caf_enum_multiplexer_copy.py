"""Authored Enum Multiplexer records; no vendor or controller programs distributed."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_enum_multiplexer_copy import PROFILE, CafEnumMultiplexerCopies
from bms_tool.caf_float_multiplexer_copy import CafFloatMultiplexerCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts
from tests.test_caf_float_multiplexer_copy import PROTOTYPE, REF, options
from tests.test_caf_float_multiplexer_copy import example as float_example

CASES = {
    "two-generic": (2, 418, [1, 2], 0, True, None, (647, "1")),
    "two-native": (2, 418, [1, 2], 0, True, None, (418, "1")),
    "two-no-text": (2, None, [1, 2], 0, True, None, (647, "1")),
    "four-generic": (4, 366, [0, 2], 1, True, (647, "0"), (647, "1")),
    "four-native": (4, 366, [0, 2], 1, True, (366, "0"), (366, "1")),
    "four-omitted": (4, 366, [0, 2], 1, False, None, None),
}
CHILDREN = [(529, 19, 11, 85), (530, 5, 12, 961), (528, 19, 13, 7000), (528, 19, 14, 7001)]


def example(kind="two-generic", *, zero=False, second_value=None):
    states, text, modes, retained, named, first, second = CASES[kind]
    parent = (
        f'<object classid="562" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="562">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(2381, "<listof>" + shorts(*modes) + "</listof>")
        + prop(3122, f"<unsignedShort>{retained}</unsignedShort>")
        + prop(
            3184,
            "<array>"
            + "".join(f'<enum set="509">{n}</enum>' for n in [961, 7000, 7001, 85])
            + "</array>",
        )
        + prop(3670, '<enum set="432">16</enum>')
        + "</object>"
    )
    children = ""
    for cid, typ, instance, port in CHILDREN:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        child = (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + prop(32527, f"<string>{ref}</string>")
            + prop(3365, f'<enum set="509">{port}</enum>')
        )
        if typ == 19:
            child += prop(74, f"<unsignedShort>{states}</unsignedShort>")
            if text is not None:
                child += prop(931, f'<enum set="802">{text}</enum>')
            default = first if port == 7000 else second if port == 7001 else None
            if default:
                encoding, value = default
                if port == 7001 and second_value is not None:
                    value = second_value
                child += prop(3113, f'<enum set="{encoding}">{value}</enum>')
        elif named:
            child += prop(3670, '<enum set="433">0</enum>')
        children += child + "</object>"
    xml = CafArchive(float_example()).xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    return packed(xml[:start] + parent + children + xml[end:], zero=zero)


@pytest.mark.parametrize("kind", CASES)
@pytest.mark.parametrize("zero", [False, True])
def test_independent_complete_xml_preserves_enum_namespaces_omissions_and_bookkeeping(kind, zero):
    original = example(kind, zero=zero)
    c = CafEnumMultiplexerCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    clone = xml[start:end].replace(".562_10", ".562_31")
    for typ, old, new in [(562, 10, 31), (19, 11, 32), (5, 12, 33), (19, 13, 34), (19, 14, 35)]:
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
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>"
    )
    moved = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(position * 3, position * 3 + moved, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode() and c.archive.original == original
    assert (
        s["profile"] == PROFILE
        and s["object_count"] == 5
        and s["setup_code"] is None
        and s["standard_name_code"] == 16
    )
    states, text, modes, retained, named, first, second = CASES[kind]
    assert s["recorded_property_2381"] == [str(n) for n in modes]
    assert s["recorded_property_3122"] == str(retained)
    assert (
        not s["enum_semantics_verified"]
        and not s["multiplexer_semantics_verified"]
        and not s["operator_meaning_verified"]
    )
    assert [
        (r["class_id"], r["bacnet_type"], r["port"], r["direction"]) for r in s["children"]
    ] == [
        ("529", 19, 85, "output"),
        ("530", 5, 961, "input"),
        ("528", 19, 7000, "input"),
        ("528", 19, 7001, "input"),
    ]
    for i, row in enumerate(s["children"]):
        assert row["exposed"] and row["recorded_metadata_661"] is None
        assert row["number_of_states"] == (None if i == 1 else states)
        assert row["states_text_code"] == (None if i == 1 else text)
        assert row["states_text_encoding_set"] == (802 if i != 1 and text is not None else None)
        default = first if i == 2 else second if i == 3 else None
        assert row["recorded_default"] == (default[1] if default else None)
        assert row["default_encoding_set"] == (default[0] if default else None)
        assert row["recorded_standard_name_code"] == (0 if i == 1 and named else None)
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
    assert CafGraph(a).diagram(REF)["connections"] == c.graph.diagram(REF)["connections"]


def test_repeated_creation_and_last_five_id_boundary():
    c = CafEnumMultiplexerCopies(example())
    first, _ = c.compile(**options(c))
    second = CafEnumMultiplexerCopies(first)
    output, _ = second.compile(**options(second))
    assert REF + ".562_36.19_40" in CafArchive(output).objects
    xml = c.archive.xml.replace(
        b"<string>Unrelated graph metadata</string>", b'<BACoid id="2">4194297</BACoid>'
    )
    boundary = CafEnumMultiplexerCopies(packed(xml))
    last, _ = boundary.compile(**options(boundary))
    assert REF + ".562_4194298.19_4194302" in CafArchive(last).objects
    with pytest.raises(ValueError, match="identities"):
        CafEnumMultiplexerCopies(packed(xml.replace(b"4194297", b"4194298"))).inspect(
            REF, PROTOTYPE
        )


def test_unsigned_default_capacity_is_not_enum_membership_or_a_float_value():
    c = CafEnumMultiplexerCopies(example(second_value="4294967295"))
    output, _ = c.compile(**options(c))
    read = CafEnumMultiplexerCopies(output).inspect(REF, REF + ".562_31")
    assert read["children"][3]["recorded_default"] == "4294967295"
    assert read["children"][3]["default_encoding_set"] == 647
    assert not read["enum_semantics_verified"]
    with pytest.raises(ValueError):
        CafFloatMultiplexerCopies(example()).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize("value", ["-1", "4294967296", "01", "1e0", "true", "NaN"])
def test_noncanonical_or_out_of_capacity_enum_defaults_are_refused(value):
    c = CafEnumMultiplexerCopies(example(second_value=value))
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="562"', 'classid="561"'),
        ('classid="562" classVersion="1.0"', 'classid="562" classVersion="2.0"'),
        ('set="432">16', 'set="432">17'),
        ('set="432">16', 'set="433">16'),
        (
            "<unsignedShort>1</unsignedShort><unsignedShort>2</unsignedShort>",
            "<unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort>",
        ),
        (
            prop(3122, "<unsignedShort>0</unsignedShort>"),
            prop(3122, "<unsignedShort>1</unsignedShort>"),
        ),
        ('<property id="2381">', '<property id="2381" extra="yes">'),
        ("<listof><unsignedShort>1", '<listof unknown="yes"><unsignedShort>1'),
        ('classid="529"', 'classid="527"'),
        ('<BACoid id="19">11', '<BACoid id="2">11'),
        ('<enum set="509">961</enum>', '<enum set="509">7000</enum>'),
        ('<enum set="802">418</enum>', '<enum set="802">366</enum>'),
        ('<enum set="802">418</enum>', '<enum set="803">418</enum>'),
        (
            '<unsignedShort>2</unsignedShort></data></property><property id="931">',
            '<unsignedShort>3</unsignedShort></data></property><property id="931">',
        ),
        ('<enum set="647">1</enum>', '<enum set="999">1</enum>'),
        ('<enum set="647">1</enum>', "<boolean>true</boolean>"),
        ('<enum set="433">0</enum>', '<enum set="433">1</enum>'),
        (
            '<property id="3670">',
            '<property id="518"><data><enum set="287">1</enum></data></property><property id="3670">',
        ),
        (prop(3373, "<boolean>true</boolean>"), prop(3373, "<boolean>false</boolean>")),
    ],
)
def test_unknown_enum_multiplexer_shapes_preserve_the_original_and_refuse(old, new):
    xml = CafArchive(example()).xml.decode()
    assert old in xml and old != new
    original = packed(xml.replace(old, new, 1))
    c = CafEnumMultiplexerCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def mixed_example():
    from tests.test_caf_constant_copy import REF as FREF
    from tests.test_caf_enum_selector_multiplexer_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    own = CafArchive(example(zero=True)).xml.decode()
    start = own.index('<object classid="562"')
    end = own.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    subtree = own[start:end].replace(REF, FREF).replace(".562_10", ".562_150")
    for typ, old, new in [(562, 10, 150), *[(typ, n, n + 140) for _, typ, n, _ in CHILDREN]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="562">140</BACoid></array>',
        '<BACoid id="562">140</BACoid><BACoid id="562">150</BACoid></array>',
        1,
    )
    xml = xml.replace(shorts(*range(14)), shorts(*range(15)), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 14, position * 15, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


def test_mixed_enum_and_float_multiplexers_keep_their_separate_output_types():
    from bms_tool.caf_float_multiplexer_service import CafFloatMultiplexerService

    c = CafFloatMultiplexerService(mixed_example())
    ref = "8-1/575_1"
    for instance, profile, typ in [
        (130, "caf-recorded-float-multiplexer-copy/1", 2),
        (140, "caf-recorded-float-enum-selector-multiplexer-copy/1", 2),
        (150, PROFILE, 19),
    ]:
        s = c.inspect(ref, ref + f".562_{instance}")
        assert s["profile"] == profile and s["new_output_ref"] == ref + f".562_155.{typ}_156"
        output, report = c.compile(
            diagram_ref=ref,
            prototype_ref=ref + f".562_{instance}",
            selection_sha256=s["selection_sha256"],
            **s["suggested_position"],
        )
        assert report["selection"] == s and len(CafGraph(output).diagram(ref)["blocks"]) == 16
        assert not report["vendor_acceptance_verified"]
