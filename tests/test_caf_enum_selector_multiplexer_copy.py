"""Independent authored Float Multiplexer records, not controller fixtures."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_enum_selector_multiplexer_copy import PROFILE, CafEnumSelectorMultiplexerCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_constant_copy import packed, prop, record, shorts
from tests.test_caf_math_copy import example as graph_example

REF = "8-1/536_4"
PROTOTYPE = REF + ".562_10"
CHILDREN = [
    (527, 2, 11, 85),
    (526, 2, 12, 7002),
    (526, 2, 13, 7003),
    (526, 2, 14, 7000),
    (526, 2, 15, 7001),
    (528, 19, 16, 961),
]


def example(*, zero=False, spelling="100.000000"):
    parent = (
        f'<object classid="562" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, '<BACoid id="562">10</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(
            2381,
            "<listof><unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort><unsignedShort>0</unsignedShort><unsignedShort>0</unsignedShort><unsignedShort>3</unsignedShort><unsignedShort>4</unsignedShort></listof>",
        )
        + prop(3122, "<unsignedShort>1</unsignedShort>")
        + prop(
            3184,
            "<array>"
            + "".join(f'<enum set="509">{n}</enum>' for n in [961, 7000, 7001, 85, 7002, 7003])
            + "</array>",
        )
        + prop(3670, '<enum set="432">15</enum>')
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
            + (prop(3670, '<enum set="433">0</enum>') if port in {7002, 7003, 961} else "")
            + (prop(3113, f"<float>{spelling}</float>") if port == 7001 else "")
            + (
                prop(74, "<unsignedShort>6</unsignedShort>")
                + prop(931, '<enum set="802">900</enum>')
                if port == 961
                else ""
            )
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
    from tests.test_caf_float_multiplexer_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    own = CafArchive(example()).xml.decode()
    start = own.index('<object classid="562"')
    end = own.index(f'<object classid="527" classVersion="1.0" ref="{REF}.2_20"')
    subtree = own[start:end].replace(REF, FREF).replace(".562_10", ".562_140")
    for typ, old, new in [(562, 10, 140), *[(typ, n, n + 130) for _, typ, n, _ in CHILDREN]]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="562">130</BACoid></array>',
        '<BACoid id="562">130</BACoid><BACoid id="562">140</BACoid></array>',
        1,
    ).replace(shorts(*range(13)), shorts(*range(14)), 1)
    pos = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(pos * 13, pos * 14, 1).replace("</objects>", subtree + "</objects>"), zero=True
    )


@pytest.mark.parametrize("zero", [False, True])
@pytest.mark.parametrize("spelling", ["100.000000", "100", "+2.50", "1e-3"])
def test_exact_complete_xml_bookkeeping_all_ports_omissions_and_existing_connection(zero, spelling):
    original = example(zero=zero, spelling=spelling)
    c = CafEnumSelectorMultiplexerCopies(original)
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
        and len(a.objects) == len(c.archive.objects) + 7
        and c.archive.original == original
    )
    assert (
        s["profile"] == PROFILE
        and s["object_count"] == 7
        and s["setup_code"] is None
        and s["standard_name_code"] == 15
    )
    assert s["operator_meaning_verified"] is False and s["multiplexer_semantics_verified"] is False
    assert (
        s["recorded_property_2381"] == ["0", "2", "0", "0", "3", "4"]
        and s["recorded_property_3122"] == "1"
    )
    assert [(r["bacnet_type"], r["port"], r["direction"]) for r in s["children"]] == [
        (2, 85, "output"),
        (2, 7002, "input"),
        (2, 7003, "input"),
        (2, 7000, "input"),
        (2, 7001, "input"),
        (19, 961, "input"),
    ]
    assert [r["recorded_default"] for r in s["children"]] == [
        None,
        None,
        None,
        None,
        spelling,
        None,
    ]
    assert [r["recorded_standard_name_code"] for r in s["children"]] == [None, 0, 0, None, None, 0]
    assert all(
        r["recorded_metadata_661"] is None and r["default_encoding_set"] is None and r["exposed"]
        for r in s["children"]
    )
    assert (
        s["children"][5]["number_of_states"] == 6
        and s["children"][5]["states_text_code"] == 900
        and s["children"][5]["states_text_encoding_set"] == 802
        and s["enum_semantics_verified"] is False
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
    again = CafEnumSelectorMultiplexerCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".562_38.2_39" in CafArchive(second).objects


def test_last_seven_ids_and_one_slot_too_few():
    xml = CafArchive(example()).xml
    marker = b'<BACoid id="2">4194295</BACoid>'
    c = CafEnumSelectorMultiplexerCopies(
        packed(xml.replace(b"<string>Unrelated graph metadata</string>", marker))
    )
    s = c.inspect(REF, PROTOTYPE)
    assert s["new_instance"] == 4194296
    output, _ = c.compile(**options(c))
    assert s["new_ref"] + ".19_4194302" in CafArchive(output).objects
    with pytest.raises(ValueError, match="identities"):
        CafEnumSelectorMultiplexerCopies(
            packed(
                xml.replace(
                    b"<string>Unrelated graph metadata</string>",
                    marker.replace(b"4194295", b"4194296"),
                )
            )
        ).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="562"', 'classid="561"'),
        ('classid="562" classVersion="1.0"', 'classid="562" classVersion="2.0"'),
        ('set="432">15', 'set="432">14'),
        ('set="432">15', 'set="433">15'),
        ('<property id="2381">', '<property id="2381" extra="yes">'),
        ('<property id="2381"><data><listof>', '<property id="2381"><data><listof unknown="yes">'),
        (
            prop(
                2381,
                "<listof><unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort><unsignedShort>0</unsignedShort><unsignedShort>0</unsignedShort><unsignedShort>3</unsignedShort><unsignedShort>4</unsignedShort></listof>",
            ),
            prop(
                2381,
                "<listof><unsignedShort>0</unsignedShort><unsignedShort>2</unsignedShort></listof>",
            ),
        ),
        (
            prop(3122, "<unsignedShort>1</unsignedShort>"),
            prop(3122, "<unsignedShort>0</unsignedShort>"),
        ),
        ('classid="528"', 'classid="530"'),
        ('<BACoid id="19">16', '<BACoid id="5">16'),
        ('<enum set="509">961</enum>', '<enum set="509">7000</enum>'),
        (
            prop(74, "<unsignedShort>6</unsignedShort>"),
            prop(74, "<unsignedShort>5</unsignedShort>"),
        ),
        ('set="802">900', 'set="802">901'),
        ('set="802">900', 'set="647">900'),
        ('set="433">0', 'set="433">1'),
        ("<float>100.000000</float>", "<float>NaN</float>"),
        ("<float>100.000000</float>", "<double>100.000000</double>"),
        (
            '<property id="931">',
            '<property id="3113"><data><enum set="647">1</enum></data></property><property id="931">',
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
def test_unknown_enum_selector_multiplexer_shape_refused_without_changing_original(old, new):
    xml = CafArchive(example()).xml.decode()
    assert old != new and old in xml
    original = packed(xml.replace(old, new, 1))
    c = CafEnumSelectorMultiplexerCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_mixed_fixture_retains_both_selector_variants():
    c = CafEnumSelectorMultiplexerCopies(mixed_example())
    ref = "8-1/575_1"
    s = c.inspect(ref, ref + ".562_140")
    assert (
        len(c.graph.diagram(ref)["blocks"]) == 14
        and s["new_instance"] == 147
        and s["new_output_ref"] == ref + ".562_147.2_148"
    )


def test_facade_results_exact_for_old_and_new_profiles_and_engines_stay_separate():
    from bms_tool.caf_float_multiplexer_copy import CafFloatMultiplexerCopies
    from bms_tool.caf_float_multiplexer_service import CafFloatMultiplexerService

    from tests.test_caf_float_multiplexer_copy import example as old_example

    for original, engine in [
        (old_example(), CafFloatMultiplexerCopies),
        (example(), CafEnumSelectorMultiplexerCopies),
    ]:
        direct = engine(original)
        facade = CafFloatMultiplexerService(original)
        assert facade.inspect(REF, PROTOTYPE) == direct.inspect(REF, PROTOTYPE)
        assert facade.compile(**options(direct)) == direct.compile(**options(direct))
    with pytest.raises(ValueError):
        CafFloatMultiplexerCopies(example()).inspect(REF, PROTOTYPE)
    with pytest.raises(ValueError):
        CafEnumSelectorMultiplexerCopies(old_example()).inspect(REF, PROTOTYPE)


def test_enum_facade_does_not_fall_back_to_float_only_admission(monkeypatch):
    from bms_tool.caf_float_multiplexer_copy import CafFloatMultiplexerCopies
    from bms_tool.caf_float_multiplexer_service import CafFloatMultiplexerService

    def wrong(*args, **kwargs):
        raise AssertionError("Wrong Float-only fallback")

    monkeypatch.setattr(CafFloatMultiplexerCopies, "_prototype", wrong)
    facade = CafFloatMultiplexerService(example())
    s = facade.inspect(REF, PROTOTYPE)
    output, _ = facade.compile(**options(facade))
    assert s["object_count"] == 7 and len(CafArchive(output).objects) == 17
