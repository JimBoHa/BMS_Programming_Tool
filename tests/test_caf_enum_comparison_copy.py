"""Authored Enum comparison examples and independent exact local-copy expectations."""

import pytest
from bms_tool.caf import CafArchive
from bms_tool.caf_comparison_copy import CafComparisonCopies
from bms_tool.caf_comparison_service import CafComparisonService
from bms_tool.caf_enum_comparison_copy import PROFILE, CafEnumComparisonCopies
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

from tests.test_caf_comparison_copy import PROTOTYPE, REF
from tests.test_caf_comparison_copy import example as float_example
from tests.test_caf_constant_copy import packed, prop, record, shorts


def example(*, states=6, encoding=647, omitted=False, values=None, zero=False):
    text = 366 if states == 4 else 387
    encoding = text if encoding == "matching" else encoding
    if values is None:
        values = (None, None) if omitted else (None, "1") if states == 4 else ("3", "5")
    xml = CafArchive(float_example(setup=5, standard=34, expose=False, value=None)).xml.decode()
    children = ""
    for cid, typ, instance, port, value in [
        (531, 5, 11, 85, None),
        (526, 2, 12, 637, None),
        (528, 19, 13, 50083, values[0]),
        (528, 19, 14, 50084, values[1]),
    ]:
        ref = f"{PROTOTYPE}.{typ}_{instance}"
        children += (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(32527, f"<string>{ref}</string>")
            + prop(75, f'<BACoid id="{typ}">{instance}</BACoid>')
            + (
                prop(74, f"<unsignedShort>{states}</unsignedShort>")
                + prop(931, f'<enum set="802">{text}</enum>')
                if typ == 19
                else ""
            )
            + (prop(3113, f'<enum set="{encoding}">{value}</enum>') if value is not None else "")
            + prop(3365, f'<enum set="509">{port}</enum>')
            + "</object>"
        )
    start = xml.index(f'<object classid="531" classVersion="1.0" ref="{PROTOTYPE}.5_11"')
    end = xml.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    return packed(xml[:start] + children + xml[end:], zero=zero)


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
    from tests.test_caf_math_copy import mixed_example as previous

    xml = CafArchive(previous()).xml.decode()
    enum = CafArchive(example()).xml.decode()
    start = enum.index('<object classid="560"')
    end = enum.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    subtree = enum[start:end].replace(REF, FREF).replace(".560_10", ".560_80")
    for typ, old, new in [(560, 10, 80), (5, 11, 81), (2, 12, 82), (19, 13, 83), (19, 14, 84)]:
        subtree = (
            subtree.replace(f'.{typ}_{old}"', f'.{typ}_{new}"')
            .replace(f".{typ}_{old}</string>", f".{typ}_{new}</string>")
            .replace(f'objectid="{old}"', f'objectid="{new}"')
            .replace(f'id="{typ}">{old}<', f'id="{typ}">{new}<')
        )
    xml = xml.replace(
        '<BACoid id="561">70</BACoid></array>',
        '<BACoid id="561">70</BACoid><BACoid id="560">80</BACoid></array>',
        1,
    ).replace(shorts(0, 1, 2, 3, 4, 5, 6), shorts(0, 1, 2, 3, 4, 5, 6, 7), 1)
    position = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    return packed(
        xml.replace(position * 7, position * 8, 1).replace("</objects>", subtree + "</objects>"),
        zero=True,
    )


@pytest.mark.parametrize("states", [4, 6])
@pytest.mark.parametrize("encoding", [647, "matching"])
@pytest.mark.parametrize("omitted", [False, True])
def test_exact_expected_xml_metadata_namespaces_hidden_input_and_existing_connection(
    states, encoding, omitted
):
    original = example(states=states, encoding=encoding, omitted=omitted, zero=True)
    c = CafEnumComparisonCopies(original)
    s = c.inspect(REF, PROTOTYPE)
    output, report = c.compile(**options(c))
    xml = c.archive.xml.decode()
    start = xml.index('<object classid="560"')
    end = xml.index(f'<object classid="531" classVersion="1.0" ref="{REF}.5_20"')
    clone = xml[start:end].replace(".560_10", ".560_31")
    for typ, old, new in [(560, 10, 31), (5, 11, 32), (2, 12, 33), (19, 13, 34), (19, 14, 35)]:
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
    old = record("<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>5</unsignedShort>")
    new = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>5</unsignedShort>"
    )
    expected = expected.replace(old * 3, old * 3 + new, 1).replace(
        "</objects>", clone + "</objects>"
    )
    a = CafArchive(output)
    assert a.xml == expected.encode() and len(a.objects) == 13 and c.archive.original == original
    assert (
        s["profile"] == PROFILE
        and s["enum_semantics_verified"] is False
        and s["operator_meaning_verified"] is False
    )
    assert [(r["class_id"], r["bacnet_type"], r["port"], r["exposed"]) for r in s["children"]] == [
        ("531", 5, 85, True),
        ("526", 2, 637, False),
        ("528", 19, 50083, True),
        ("528", 19, 50084, True),
    ]
    assert s["children"][2]["number_of_states"] == states and s["children"][2][
        "states_text_code"
    ] == (366 if states == 4 else 387)
    assert s["children"][3]["default_encoding_set"] == (
        None if omitted else 647 if encoding == 647 else 366 if states == 4 else 387
    )
    assert report["new_output_sha256"] == report["new_child_sha256"][0] and report[
        "output_sha256"
    ] == sha(output)
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert CafComparisonService(original).inspect(REF, PROTOTYPE) == s and CafComparisonService(
        original
    ).compile(**options(c)) == (output, report)
    with pytest.raises(ValueError):
        CafComparisonCopies(original).inspect(REF, PROTOTYPE)
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
    again = CafEnumComparisonCopies(output)
    second, _ = again.compile(**options(again))
    assert REF + ".560_36.19_40" in CafArchive(second).objects


def test_opaque_uint32_codes_do_not_infer_number_of_states_membership():
    c = CafEnumComparisonCopies(example(states=4, values=("4294967295", "0")))
    s = c.inspect(REF, PROTOTYPE)
    out, _ = c.compile(**options(c))
    assert (
        s["children"][2]["recorded_default"] == "4294967295"
        and b'<enum set="647">4294967295</enum>' in CafArchive(out).xml
    )
    assert s["enum_semantics_verified"] is False


def test_last_five_local_ids_and_insufficient_space_keep_existing_ceiling():
    xml = CafArchive(example()).xml
    marker = b"<string>Unrelated graph metadata</string>"
    c = CafEnumComparisonCopies(packed(xml.replace(marker, b'<BACoid id="2">4194297</BACoid>')))
    s = c.inspect(REF, PROTOTYPE)
    out, _ = c.compile(**options(c))
    assert s["new_instance"] == 4194298 and s["new_ref"] + ".19_4194302" in CafArchive(out).objects
    with pytest.raises(ValueError, match="Five fresh"):
        CafEnumComparisonCopies(
            packed(xml.replace(marker, b'<BACoid id="2">4194298</BACoid>'))
        ).inspect(REF, PROTOTYPE)


@pytest.mark.parametrize(
    "old,new",
    [
        ('set="287">5', 'set="287">1'),
        ('set="432">34', 'set="432">28'),
        ('classid="560" classVersion="1.0"', 'classid="560" classVersion="2.0"'),
        ('classid="528"', 'classid="529"'),
        ('<BACoid id="19">13', '<BACoid id="2">13'),
        ('<enum set="802">387</enum>', '<enum set="802">366</enum>'),
        ('<enum set="802">387</enum>', '<enum set="803">387</enum>'),
        ("<unsignedShort>6</unsignedShort>", "<unsignedShort>4</unsignedShort>"),
        ('<enum set="647">3</enum>', '<enum set="351">3</enum>'),
        ('<enum set="647">3</enum>', '<enum set="647">4294967296</enum>'),
        ('<enum set="647">3</enum>', '<enum set="647">-1</enum>'),
        ('<enum set="647">3</enum>', "<unsignedInt>3</unsignedInt>"),
        ('<enum set="509">50083</enum>', '<enum set="509">637</enum>'),
        ('<enum set="509">637</enum>', '<enum set="509">50083</enum>'),
        ('<property id="931">', '<property id="931" unknown="yes">'),
        (
            '<enum set="509">85</enum></array>',
            '<enum set="509">85</enum><enum set="509">637</enum></array>',
        ),
    ],
)
def test_unknown_enum_schema_or_configuration_is_refused_without_fallback(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    c = CafEnumComparisonCopies(original)
    with pytest.raises(ValueError):
        c.inspect(REF, PROTOTYPE)
    with pytest.raises(ValueError):
        CafComparisonService(original).inspect(REF, PROTOTYPE)
    assert c.archive.original == original


def test_invalid_enum_child_never_falls_back_to_float_inspection(monkeypatch):
    original = packed(
        CafArchive(example()).xml.replace(b'<enum set="647">3</enum>', b'<enum set="351">3</enum>')
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid Enum source fell back to Float")

    monkeypatch.setattr(CafComparisonCopies, "_prototype", forbidden)
    with pytest.raises(ValueError):
        CafComparisonService(original).inspect(REF, PROTOTYPE)


def test_float_facade_preserves_exact_source_report_and_artifact():
    original = float_example(zero=True)
    direct = CafComparisonCopies(original)
    facade = CafComparisonService(original)
    assert facade.inspect(REF, PROTOTYPE) == direct.inspect(REF, PROTOTYPE)
    assert facade.compile(**options(direct)) == direct.compile(**options(direct))


def test_both_comparison_input_families_share_a_diagram_without_changing_other_families():
    a = CafArchive(mixed_example())
    ref = "8-1/575_1"
    service = CafComparisonService(a)
    assert len(CafGraph(a).diagram(ref)["blocks"]) == 8
    assert service.inspect(ref, ref + ".560_80")["profile"] == PROFILE
    assert (
        service.inspect(ref, ref + ".560_60")["profile"] == "caf-recorded-float-comparison-copy/1"
    )
