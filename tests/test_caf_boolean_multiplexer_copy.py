"""Authored Boolean I/O Multiplexer records; no controller programs distributed."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_boolean_enum_selector_multiplexer_copy import (
    PROFILE as ENUM_PROFILE,
)
from bms_tool.caf_boolean_enum_selector_multiplexer_copy import (
    CafBooleanEnumSelectorMultiplexerCopies,
)
from bms_tool.caf_boolean_multiplexer_copy import PROFILE, CafBooleanMultiplexerCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts
from tests.test_caf_float_multiplexer_copy import PROTOTYPE, REF, options
from tests.test_caf_float_multiplexer_copy import example as float_example

CASES = {
    "boolean": (18, 5, None, None, [1, 2], 0),
    "enum-two": (19, 19, 2, 350, [1, 2], 0),
    "enum-five-a": (19, 19, 5, 1347, [1, 0, 0, 0, 0], 2),
    "enum-five-b": (19, 19, 5, 359, [0, 0, 0, 2, 0], 1),
}


def compiler(kind, original):
    return (
        CafBooleanMultiplexerCopies
        if kind == "boolean"
        else CafBooleanEnumSelectorMultiplexerCopies
    )(original)


def example(kind="boolean", *, value="1", zero=False):
    standard, selector_type, states, text, modes, retained = CASES[kind]
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
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    children = ""
    for cid, typ, instance, port in [
        (531, 5, 11, 85),
        (528 if selector_type == 19 else 530, selector_type, 12, 961),
        (530, 5, 13, 7000),
        (530, 5, 14, 7001),
    ]:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        child = (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + prop(32527, f"<string>{ref}</string>")
            + prop(3365, f'<enum set="509">{port}</enum>')
        )
        if typ == 19:
            child += prop(74, f"<unsignedShort>{states}</unsignedShort>") + prop(
                931, f'<enum set="802">{text}</enum>'
            )
        if port == 961:
            child += prop(3670, '<enum set="433">0</enum>')
        if standard == 19 and port == 7001:
            child += prop(3113, f"<boolean>{value}</boolean>")
        children += child + "</object>"
    xml = CafArchive(float_example()).xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    return packed(xml[:start] + parent + children + xml[end:], zero=zero)


SOURCE_FORMS = [("boolean", None)] + [
    (k, v) for k in ["enum-two", "enum-five-a", "enum-five-b"] for v in ["1", "true", "0", "false"]
]


@pytest.mark.parametrize("kind,value", SOURCE_FORMS)
@pytest.mark.parametrize("zero", [False, True])
def test_independent_complete_xml_boolean_spellings_typed_selector_omissions_and_zip(
    kind, value, zero
):
    original = example(kind, value=value, zero=zero)
    c = compiler(kind, original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="562"')
    end = xml.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    clone = xml[start:end].replace(".562_10", ".562_31")
    selector_type = CASES[kind][1]
    for typ, old, new in [
        (562, 10, 31),
        (5, 11, 32),
        (selector_type, 12, 33),
        (5, 13, 34),
        (5, 14, 35),
    ]:
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
    pos = record("<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>")
    moved = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(pos * 3, pos * 3 + moved, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode() and c.archive.original == original
    standard, typ, states, text, modes, retained = CASES[kind]
    assert (
        s["profile"] == (PROFILE if standard == 18 else ENUM_PROFILE)
        and s["standard_name_code"] == standard
        and s["setup_code"] is None
        and s["object_count"] == 5
    )
    assert s["recorded_property_2381"] == [str(v) for v in modes] and s[
        "recorded_property_3122"
    ] == str(retained)
    assert [r["bacnet_type"] for r in s["children"]] == [5, typ, 5, 5]
    assert [r["class_id"] for r in s["children"]] == [
        "531",
        "528" if typ == 19 else "530",
        "530",
        "530",
    ]
    assert [r["recorded_default"] for r in s["children"]] == [None, None, None, value]
    assert [r["number_of_states"] for r in s["children"]] == [None, states, None, None]
    assert [r["states_text_code"] for r in s["children"]] == [None, text, None, None]
    for i, r in enumerate(s["children"]):
        assert (
            r["exposed"]
            and r["recorded_metadata_661"] is None
            and r["default_encoding_set"] is None
        )
        assert r["direction"] == ("output" if i == 0 else "input")
        assert r["states_text_encoding_set"] == (802 if i == 1 and typ == 19 else None)
        assert r["recorded_standard_name_code"] == (0 if i == 1 else None)
    assert not s["operator_meaning_verified"] and not s["multiplexer_semantics_verified"]
    if standard == 19:
        assert s["enum_semantics_verified"] is False
    assert (
        s["new_output_ref"] == REF + ".562_31.5_32"
        and report["new_output_sha256"] == report["new_child_sha256"][0]
    )
    assert report["output_sha256"] == sha(output) and report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert (
        not report["controller_write"]
        and not report["field_transfer_enabled"]
        and not report["vendor_acceptance_verified"]
    )
    assert CafGraph(output).diagram(REF)["connections"] == c.graph.diagram(REF)["connections"]
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


@pytest.mark.parametrize("kind", ["boolean", "enum-two"])
def test_repeated_creation_and_last_five_ids_use_boolean_output_domain(kind):
    c = compiler(kind, example(kind))
    first, _ = c.compile(**options(c))
    second = compiler(kind, first)
    output, _ = second.compile(**options(second))
    assert REF + ".562_36.5_40" in CafArchive(output).objects
    xml = c.archive.xml.replace(
        b"<string>Unrelated graph metadata</string>", b'<BACoid id="2">4194297</BACoid>'
    )
    last = compiler(kind, packed(xml))
    out, _ = last.compile(**options(last))
    assert REF + ".562_4194298.5_4194302" in CafArchive(out).objects
    with pytest.raises(ValueError, match="identities"):
        compiler(kind, packed(xml.replace(b"4194297", b"4194298"))).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize("kind", ["boolean", "enum-two"])
def test_separate_direct_engines_do_not_admit_the_other_selector_profile(kind):
    wrong = (
        CafBooleanEnumSelectorMultiplexerCopies
        if kind == "boolean"
        else CafBooleanMultiplexerCopies
    )
    with pytest.raises(ValueError):
        wrong(example(kind)).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize("value", ["True", "FALSE", "2", "-1", "1.0", "yes", ""])
def test_unknown_boolean_default_spellings_are_refused(value):
    c = compiler("enum-two", example("enum-two", value=value))
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)


@pytest.mark.parametrize("kind", ["boolean", "enum-two"])
@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="562"', 'classid="561"'),
        ('classid="562" classVersion="1.0"', 'classid="562" classVersion="2.0"'),
        ('<property id="2381">', '<property id="2381" extra="yes">'),
        ("<listof><unsignedShort>1", '<listof unknown="yes"><unsignedShort>1'),
        (shorts(1, 2), shorts(1, 1)),
        (
            prop(3122, "<unsignedShort>0</unsignedShort>"),
            prop(3122, "<unsignedShort>1</unsignedShort>"),
        ),
        ('classid="531"', 'classid="527"'),
        ('<BACoid id="5">11', '<BACoid id="2">11'),
        ('<enum set="509">961</enum>', '<enum set="509">7000</enum>'),
        ('<enum set="433">0</enum>', '<enum set="433">1</enum>'),
        (prop(3670, '<enum set="433">0</enum>'), ""),
        ('<property id="3365">', prop(3113, "<boolean>true</boolean>") + '<property id="3365">'),
        (prop(3373, "<boolean>true</boolean>"), prop(3373, "<boolean>false</boolean>")),
    ],
)
def test_unknown_parent_child_or_selector_shapes_keep_the_original_and_refuse(kind, old, new):
    xml = CafArchive(example(kind)).xml.decode()
    assert old in xml and old != new
    original = packed(xml.replace(old, new, 1))
    c = compiler(kind, original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


@pytest.mark.parametrize(
    "old,new",
    [
        ('<enum set="802">350</enum>', '<enum set="802">359</enum>'),
        ('<enum set="802">350</enum>', '<enum set="803">350</enum>'),
        (
            prop(74, "<unsignedShort>2</unsignedShort>"),
            prop(74, "<unsignedShort>5</unsignedShort>"),
        ),
        ("<boolean>1</boolean>", '<enum set="647">1</enum>'),
        (prop(3113, "<boolean>1</boolean>"), ""),
    ],
)
def test_enum_selector_metadata_and_stored_default_are_separately_required(old, new):
    xml = CafArchive(example("enum-two")).xml.decode()
    assert old in xml
    with pytest.raises(ValueError):
        compiler("enum-two", packed(xml.replace(old, new, 1))).inspect(REF, PROTOTYPE)


def mixed_example():
    from tests.test_caf_constant_copy import REF as FREF
    from tests.test_caf_enum_enum_selector_multiplexer_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    subtrees = ""
    for kind, parent in [("boolean", 170), ("enum-two", 180)]:
        own = CafArchive(example(kind, zero=True)).xml.decode()
        start = own.index('<object classid="562"')
        end = own.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
        subtree = own[start:end].replace(REF, FREF).replace(".562_10", f".562_{parent}")
        for typ, old, new in [
            (562, 10, parent),
            (5, 11, parent + 1),
            (CASES[kind][1], 12, parent + 2),
            (5, 13, parent + 3),
            (5, 14, parent + 4),
        ]:
            subtree = (
                subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
                .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
                .replace(f'objectid="{old}"', f'objectid="{new}"')
                .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
            )
        subtrees += subtree
    xml = xml.replace(
        '<BACoid id="562">160</BACoid></array>',
        '<BACoid id="562">160</BACoid><BACoid id="562">170</BACoid>'
        '<BACoid id="562">180</BACoid></array>',
        1,
    ).replace(shorts(*range(16)), shorts(*range(18)), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 16, position * 18, 1).replace("</objects>", subtrees + "</objects>"),
        zero=True,
    )


def test_mixed_six_profile_facade_keeps_all_selector_and_output_domains():
    from bms_tool.caf_float_multiplexer_service import CafFloatMultiplexerService

    c = CafFloatMultiplexerService(mixed_example())
    ref = "8-1/575_1"
    for instance, standard, typ in [
        (130, 14, 2),
        (140, 15, 2),
        (150, 16, 19),
        (160, 17, 19),
        (170, 18, 5),
        (180, 19, 5),
    ]:
        s = c.inspect(ref, ref + f".562_{instance}")
        assert s["standard_name_code"] == standard
        assert s["new_output_ref"] == ref + f".562_185.{typ}_186"
        output, report = c.compile(
            diagram_ref=ref,
            prototype_ref=ref + f".562_{instance}",
            selection_sha256=s["selection_sha256"],
            **s["suggested_position"],
        )
        assert report["selection"] == s and len(CafGraph(output).diagram(ref)["blocks"]) == 19
        assert not report["vendor_acceptance_verified"]
