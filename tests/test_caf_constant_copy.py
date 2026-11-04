"""Authored local creation examples; no vendor acceptance fixtures or site data."""

import html
import io
import zipfile

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_constant_copy import CafConstantCopies, coordinate
from bms_tool.caf_graph import CafGraph
from bms_tool.moi_identity import seal, sha

REF = "8-1/575_1"
PROTOTYPE = REF + ".551_10"


def prop(pid, value):
    return f'<property id="{pid}"><data>{value}</data></property>'


def record(*values):
    return "<struct>" + "".join(f"<structElement>{v}</structElement>" for v in values) + "</struct>"


def shorts(*values):
    return "".join(f"<unsignedShort>{v}</unsignedShort>" for v in values)


def packed(xml, *, zero=False):
    out = io.BytesIO()
    info = zipfile.ZipInfo("authored.xml", (2020, 2, 3, 4, 5, 6))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.comment = b"entry evidence"
    info.extra = b"\xfe\xca\x02\x00OK"
    info.internal_attr = 1
    info.external_attr = 0 if zero else 0o640 << 16
    with zipfile.ZipFile(out, "w") as z:
        z.comment = b"original archive evidence"
        z.writestr(info, xml if isinstance(xml, bytes) else xml.encode())
        if zero:
            info.external_attr = 0
    return out.getvalue()


def example(*, standard=11, graph_class=575, zero=False, value="1.000000"):
    def member(n):
        return f'<BACoid id="{551 if n == 10 else 2}">{n}</BACoid>'

    layout = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    constant = (
        f'<object classid="551" classVersion="1.0" ref="{PROTOTYPE}" objectid="10">'
        + prop(75, member(10))
        + prop(32527, f"<string>{PROTOTYPE}</string>")
        + prop(3184, '<array><enum set="509">85</enum></array>')
        + prop(3670, f'<enum set="432">{standard}</enum>')
        + "</object>"
    )
    child = (
        f'<object classid="527" classVersion="1.0" ref="{PROTOTYPE}.2_11" objectid="11">'
        + prop(75, '<BACoid id="2">11</BACoid>')
        + prop(32527, f"<string>{PROTOTYPE}.2_11</string>")
        + prop(3365, '<enum set="509">85</enum>')
        + (prop(3113, f"<float>{value}</float>") if value is not None else "")
        + "</object>"
    )
    parent = (
        f'<object classid="{graph_class}" classVersion="1.0" ref="{REF}" objectid="1">'
        + prop(3375, "<array>" + "".join(member(n) for n in (10, 20, 30)) + "</array>")
        + prop(3117, "<array>" + shorts(0, 1, 2) + "</array>")
        + prop(3383, "<listof>" + layout * 3 + "</listof>")
        + prop(
            3118,
            "<array>"
            + record(*[f"<unsignedShort>{n}</unsignedShort>" for n in (0, 85, 1, 513)])
            + "</array>",
        )
        + prop(
            3384,
            "<listof>"
            + record("<boolean>true</boolean>", "<string>Retain &amp; remember</string>")
            + "</listof>",
        )
        + prop(3373, "<boolean>true</boolean>")
        + prop(9999, "<opaque><string>Preserve this exactly.</string></opaque>")
        + "</object>"
    )
    targets = "".join(
        f'<object classid="527" classVersion="1.0" ref="{REF}.2_{n}" objectid="{n}">'
        + prop(75, member(n))
        + prop(2390, "<string>Authored target</string>")
        + prop(3184, '<array><enum set="509">513</enum></array>')
        + "</object>"
        for n in (20, 30)
    )
    return packed(
        f'<objects xmlns="{NS}">{parent}{constant}{child}{targets}<jobInfo /></objects>', zero=zero
    )


def options(compiler, **updates):
    selected = compiler.inspect(REF, PROTOTYPE)
    return {
        "diagram_ref": REF,
        "prototype_ref": PROTOTYPE,
        "selection_sha256": selected["selection_sha256"],
        "x": "+81.000",
        "y": "4.2E+1",
        **updates,
    }


@pytest.mark.parametrize("standard", [11, 796])
@pytest.mark.parametrize("graph_class", [536, 575])
@pytest.mark.parametrize("zero", [False, True])
def test_exact_independently_constructed_xml_and_existing_connection_path(
    standard, graph_class, zero
):
    original = example(standard=standard, graph_class=graph_class, zero=zero)
    compiler = CafConstantCopies(original)
    xml = compiler.archive.xml.decode()
    output, report = compiler.compile(**options(compiler))
    start = xml.index('<object classid="551"')
    end = xml.index("</object>", start) + len("</object>")
    new_object = (
        xml[start:end]
        .replace(PROTOTYPE, REF + ".551_31")
        .replace('objectid="10"', 'objectid="31"')
        .replace('id="551">10<', 'id="551">31<')
    )
    child_start = xml.index(f'<object classid="527" classVersion="1.0" ref="{PROTOTYPE}.2_11"')
    child_end = xml.index("</object>", child_start) + len("</object>")
    new_output = (
        xml[child_start:child_end]
        .replace(PROTOTYPE + ".2_11", REF + ".551_31.2_32")
        .replace('objectid="11"', 'objectid="32"')
        .replace('id="2">11<', 'id="2">32<')
    )
    old_members = '<BACoid id="551">10</BACoid><BACoid id="2">20</BACoid><BACoid id="2">30</BACoid>'
    expected = xml.replace(old_members, old_members + '<BACoid id="551">31</BACoid>', 1)
    expected = expected.replace(shorts(0, 1, 2), shorts(0, 3, 1, 2), 1)
    layout = record(
        "<float>1.000</float>", "<float>2.000</float>", "<unsignedShort>12</unsignedShort>"
    )
    new_layout = record(
        "<float>+81.000</float>", "<float>4.2E+1</float>", "<unsignedShort>12</unsignedShort>"
    )
    expected = expected.replace(layout * 3, layout * 3 + new_layout, 1).replace(
        "</objects>", new_object + new_output + "</objects>"
    )
    reopened = CafArchive(output)
    assert reopened.xml == expected.encode()
    assert compiler.archive.original == original
    assert report["output_sha256"] == sha(output)
    assert report["creation_sha256"] == seal(
        {k: v for k, v in report.items() if k != "creation_sha256"}
    )
    assert (
        not report["controller_write"]
        and not report["field_transfer_enabled"]
        and not report["vendor_acceptance_verified"]
    )
    assert reopened.comment == compiler.archive.comment
    for name in (
        "filename",
        "date_time",
        "compress_type",
        "comment",
        "extra",
        "internal_attr",
        "external_attr",
        "create_system",
    ):
        assert getattr(reopened.info, name) == getattr(compiler.archive.info, name)
    connected, _ = CafGraph(output).add_connections(
        [
            {
                "diagram_ref": REF,
                "prototype_diagram_ref": REF,
                "prototype_wire_index": 0,
                "prototype_old": [0, 85, 1, 513],
                "source_ref": REF + ".551_31",
                "target_ref": REF + ".2_30",
                "old_connection_count": 1,
            }
        ]
    )
    assert CafGraph(connected).diagram(REF)["connections"][-1]["raw"] == [3, 85, 2, 513]
    again = CafConstantCopies(output)
    second, _ = again.compile(**options(again))
    assert CafGraph(second).diagram(REF)["execution_order"] == [0, 4, 3, 1, 2]
    assert REF + ".551_33" in CafArchive(second).objects


@pytest.mark.parametrize(
    "x,y",
    [
        ("-0.0", " .5 "),
        ("1.", "+1.2e-3"),
        ("3.4028234e38", "-3.4028234e38"),
        ("1e-90", "\t4\n"),
        ("\r\n1.25\t", "4"),
    ],
)
def test_exact_coordinate_spelling_and_single_quoted_source(x, y):
    archive = CafArchive(example())
    # Single quotes, embedded > and an unrelated lookalike in a comment are retained.
    xml = archive.xml.replace(b'"', b"'").replace(
        b"<jobInfo />", b"<!-- <object ref='fake'> --> <jobInfo />"
    )
    compiler = CafConstantCopies(packed(xml))
    output, report = compiler.compile(**options(compiler, x=x, y=y))
    assert report["position"] == {"x": x, "y": y}
    assert CafGraph(output).diagram(REF)["blocks"][-1]["layout"]["x"] == x
    assert b"<!-- <object ref='fake'> -->" in CafArchive(output).xml


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "nan",
        "Infinity",
        "1e100",
        "-1e100",
        "3.5e38",
        "١",
        "1_000",
        "\u00a01",
        "1" * 81,
        3,
        True,
        None,
    ],
)
def test_unfinished_invalid_or_overflowing_coordinate_is_refused(value):
    with pytest.raises(ValueError):
        coordinate(value)


@pytest.mark.parametrize(
    "old,new",
    [
        ('classid="551"', 'classid="552"'),
        ('classid="551" classVersion="1.0"', 'classid="551" classVersion="2.0"'),
        ('classid="575" classVersion="1.0"', 'classid="575" classVersion="2.0"'),
        ('objectid="10"', 'objectid="010"'),
        ('id="551">10</BACoid>', 'id="551">010</BACoid>'),
        ('set="432">11', 'set="433">11'),
        ('set="432">11', 'set="432">12'),
        ('set="509">85', 'set="509">86'),
        (f"<string>{PROTOTYPE}</string>", "<string>wrong</string>"),
        (prop(3373, "<boolean>true</boolean>"), prop(3373, "<boolean>false</boolean>")),
        ("<jobInfo />", '<jobInfo nextId="30" />'),
        ("<jobInfo />", "<allocation><unsignedLong>30</unsignedLong></allocation>"),
        ('<array><enum set="509">85', '<array other="unknown"><enum set="509">85'),
        ('<property id="3670">', '<property id="3670" extra="unknown">'),
        ('<enum set="432">11</enum>', '<enum set="432"><![CDATA[11]]></enum>'),
        ("<string>Preserve this exactly.</string>", '<BACoid id="2">4194302</BACoid>'),
        ("<string>Preserve this exactly.</string>", '<BACoid id="2">4194303</BACoid>'),
        ("<string>Preserve this exactly.</string>", '<BACoid id="2">0030</BACoid>'),
        ("<string>Preserve this exactly.</string>", '<BACoid id="1024">30</BACoid>'),
        ("<objects xmlns=", '<objects allocator="unknown" xmlns='),
    ],
)
def test_unknown_or_incoherent_source_refused_without_modifying_original(old, new):
    original = packed(CafArchive(example()).xml.decode().replace(old, new, 1))
    compiler = CafConstantCopies(original)
    with pytest.raises(ValueError):
        compiler.inspect(REF, PROTOTYPE)
    assert compiler.archive.original == original


def test_fresh_identity_includes_unresolved_typed_references():
    xml = CafArchive(example()).xml.replace(
        b"<string>Preserve this exactly.</string>", b'<BACoid id="721">3000014</BACoid>'
    )
    compiler = CafConstantCopies(packed(xml))
    selected = compiler.inspect(REF, PROTOTYPE)
    assert selected["new_instance"] == 3000015
    output, _ = compiler.compile(**options(compiler))
    assert REF + ".551_3000015" in CafArchive(output).objects
    with pytest.raises(ValueError, match="source changed"):
        compiler.compile(**options(compiler, selection_sha256="0" * 64))


@pytest.mark.parametrize(
    "extras",
    [
        "",
        prop(117, '<enum set="507">98</enum>'),
        prop(661, '<enum set="0">4</enum>'),
        prop(117, '<enum set="507">98</enum>')
        + prop(661, '<enum set="0">4</enum>')
        + prop(2390, "<string>A &amp; B</string>")
        + prop(3807, "<boolean>false</boolean>"),
    ],
)
def test_recorded_output_metadata_is_copied_without_interpreting_values(extras):
    a = CafArchive(example())
    marker = (
        f'<object classid="527" classVersion="1.0" ref="{PROTOTYPE}.2_11" objectid="11">'.encode()
    )
    xml = a.xml.replace(marker, marker + extras.encode(), 1)
    # Exercise the second observed namespace declaration and empty jobInfo namespace too.
    xml = xml.replace(
        b"<objects xmlns=",
        b'<objects xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns=',
        1,
    ).replace(b"<jobInfo />", b'<jobInfo xmlns="" />')
    c = CafConstantCopies(packed(xml))
    output, report = c.compile(**options(c))
    assert extras.encode() in CafArchive(output).xml
    assert report["selection"]["recorded_value"] == "1.000000"


def test_omitted_numeric_value_stays_omitted_in_the_new_output():
    c = CafConstantCopies(example(value=None))
    output, report = c.compile(**options(c))
    new = CafArchive(output).objects[report["selection"]["new_output_ref"]]
    assert len(new) == 3 and all(p.get("id") != "3113" for p in new)
    assert report["selection"]["recorded_value"] is None


def test_unicode_and_escaped_references_clone_exact_logical_identities():
    reference = 'source/é & "quoted"/575_1'
    xml = CafArchive(example()).xml.decode().replace(REF, html.escape(reference, quote=True))
    c = CafConstantCopies(packed(xml))
    selected = c.inspect(reference, reference + ".551_10")
    output, _ = c.compile(
        diagram_ref=reference,
        prototype_ref=reference + ".551_10",
        selection_sha256=selected["selection_sha256"],
        x="1",
        y="2",
    )
    new = CafArchive(output)
    assert selected["new_ref"] in new.objects
    assert selected["new_output_ref"] in new.objects
    assert c.graph.diagram(reference)["ref"] == reference


@pytest.mark.parametrize(
    "old,new",
    [
        ('<enum set="509">85</enum>', '<enum set="509">86</enum>'),
        ("<float>1.000000</float>", "<double>1.000000</double>"),
        ("<float>1.000000</float>", "<float>1e100</float>"),
        ("<float>1.000000</float>", "<float><![CDATA[1.0]]></float>"),
        ('<property id="3113">', '<property id="3113" other="unknown">'),
    ],
)
def test_unknown_output_configuration_is_refused(old, new):
    original = CafArchive(example()).xml
    start = original.index(
        f'<object classid="527" classVersion="1.0" ref="{PROTOTYPE}.2_11"'.encode()
    )
    xml = original[:start] + original[start:].replace(old.encode(), new.encode(), 1)
    with pytest.raises(ValueError):
        CafConstantCopies(packed(xml)).inspect(REF, PROTOTYPE)


def test_child_ownership_and_incoming_connection_refused():
    original = CafArchive(example()).xml
    child = (
        f'<object classid="551" classVersion="1.0" ref="{PROTOTYPE}.2_40" objectid="40"/>'.encode()
    )
    for xml in (
        original.replace(b"</objects>", child + b"</objects>"),
        original.replace(
            record(*[f"<unsignedShort>{n}</unsignedShort>" for n in (0, 85, 1, 513)]).encode(),
            record(*[f"<unsignedShort>{n}</unsignedShort>" for n in (1, 85, 0, 513)]).encode(),
            1,
        ),
    ):
        compiler = CafConstantCopies(packed(xml))
        with pytest.raises(ValueError):
            compiler.inspect(REF, PROTOTYPE)
