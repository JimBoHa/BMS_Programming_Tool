"""Authored schema examples, plus opt-in checks on undistributed local CAFs.

The synthetic examples test editing behavior. They are not manufacturer fixtures
and cannot establish acceptance by CCT/PCT or real firmware.
"""

import io
import os
import zipfile
from collections import defaultdict
from pathlib import Path

import pytest
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_graph import CafGraph

REF = "8-1/575_1"


def prop(pid, value):
    return f'<property id="{pid}"><data>{value}</data></property>'


def record(*values):
    return "<struct>" + "".join(f"<structElement>{v}</structElement>" for v in values) + "</struct>"


def shorts(*values):
    return [f"<unsignedShort>{v}</unsignedShort>" for v in values]


def make_graph(*, version="1.0", boolean="1", extra_wire=None, sequence=None, wires=None):
    """Make an explicitly synthetic native-container example; no site data."""
    blocks = [(526, 2, 10), (526, 2, 11), (527, 2, 12), (527, 2, 13)]
    wires = list(wires) if wires is not None else [(0, 663, 2, 513), (1, 663, 3, 513)]
    if extra_wire is not None:
        wires.append(extra_wire)
    sequence = sequence if sequence is not None else [0, 1, 2, 3]
    graph = (
        f'<object classid="575" classVersion="{version}" ref="{REF}" objectid="1">'
        + prop("2390", "<string>Authored example</string>")
        + prop(
            "3375",
            "<array>"
            + "".join(f'<BACoid id="{t}">{i}</BACoid>' for _, t, i in blocks)
            + "</array>",
        )
        + prop("3117", "<array>" + "".join(shorts(*sequence)) + "</array>")
        + prop("3118", "<array>" + "".join(record(*shorts(*w)) for w in wires) + "</array>")
        + prop(
            "3383",
            "<listof>"
            + "".join(
                record(
                    "<float>1.000</float>",
                    "<float>2.000</float>",
                    "<unsignedShort>0</unsignedShort>",
                )
                for _ in blocks
            )
            + "</listof>",
        )
        + prop(
            "3384",
            "<listof>"
            + "".join(
                record(f"<boolean>{boolean}</boolean>", "<string>Opaque &amp; retained</string>")
                for _ in wires
            )
            + "</listof>",
        )
        + prop("9999", "<opaque><string>Unknown graph metadata</string></opaque>")
        + "</object>"
    )
    children = ""
    for cid, type_id, instance in blocks:
        ref = f"{REF}.{type_id}_{instance}"
        children += (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop("75", f'<BACoid id="{type_id}">{instance}</BACoid>')
            + prop("32527", f"<string>{ref}</string>")
            + prop("2390", f"<string>Block {instance}</string>")
            + prop("3113", f"<float>{instance}.000</float>")
            + prop("117", '<enum set="507">98</enum>')
            + prop("3365", '<enum set="509">7000</enum>')
            + prop("3184", '<array><enum set="509">663</enum><enum set="509">513</enum></array>')
            + prop("9998", "<opaque><unsignedShort>44</unsignedShort></opaque>")
            + '<simulationProperty id="3113"><data><float>800</float></data></simulationProperty>'
            + "</object>"
        )
    xml = f'<objects xmlns="{NS}">{graph}{children}<jobInfo><string>Preserve job</string></jobInfo></objects>'.encode()
    return pack(xml)


def pack(xml):
    out = io.BytesIO()
    info = zipfile.ZipInfo("authored.caf.xml", date_time=(2020, 2, 3, 4, 5, 6))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.comment = b"entry-comment"
    info.external_attr = 0o600 << 16
    with zipfile.ZipFile(out, "w") as archive:
        archive.comment = b"archive-comment"
        archive.writestr(info, xml)
    return out.getvalue()


def change(**updates):
    result = {
        "diagram_ref": REF,
        "wire_index": 0,
        "old": [0, 663, 2, 513],
        "source_ref": REF + ".2_11",
    }
    result.update(updates)
    return result


def test_native_graph_resolves_hierarchical_bacnet_identity_and_execution_order():
    graph = CafGraph(make_graph())
    inventory = graph.diagrams()
    assert not inventory["errors"]
    assert inventory["diagrams"][0]["connections"] == 2
    diagram = graph.diagram(REF)
    assert diagram["execution_order"] == [0, 1, 2, 3]
    assert diagram["blocks"][0]["class_id"] == "526"
    assert diagram["blocks"][0]["bacnet_type"] == 2
    assert diagram["blocks"][0]["layout"] == {"x": "1.000", "y": "2.000", "opaque_code": 0}
    assert diagram["connections"][0]["source_ref"] == REF + ".2_10"
    assert diagram["connections"][0]["continuation"] == {"flag": True, "text": "Opaque & retained"}
    assert not inventory["capabilities"]["native_compile"]


@pytest.mark.parametrize("axis,original", [("x", "1.000"), ("y", "2.000")])
@pytest.mark.parametrize(
    "value",
    ["NaN", "Infinity", "-INF", "1e309", "-1e309", "1_000", "١", "1.2.3", "", ".", "\u00a01"],
)
def test_invalid_native_coordinates_block_inspection_and_graph_edits(axis, original, value):
    data = CafArchive(make_graph(wires=[(0, 663, 2, 513)]))
    xml = data.xml.replace(
        f"<float>{original}</float>".encode(), f"<float>{value}</float>".encode(), 1
    )
    graph = CafGraph(pack(xml))
    inventory = graph.diagrams()
    assert not inventory["diagrams"]
    assert inventory["errors"] == [
        {"ref": REF, "error": "CAF graph layout coordinates require finite native floats."}
    ]
    with pytest.raises(ValueError, match="finite native floats"):
        graph.diagram(REF)
    with pytest.raises(ValueError, match="finite native floats"):
        graph.rewire_sources([change()])
    with pytest.raises(ValueError, match="finite native floats"):
        graph.add_connections([connection()])
    assert graph.archive.xml == xml


@pytest.mark.parametrize(
    "x,y",
    [("-0.0", "+12.500"), (".5", "1."), ("6.25E+1", " \t-2.50e-2 \n")],
)
def test_finite_native_coordinate_spellings_survive_inspection_and_rewire(x, y):
    original = CafArchive(make_graph()).xml
    original = original.replace(b"<float>1.000</float>", f"<float>{x}</float>".encode(), 1)
    original = original.replace(b"<float>2.000</float>", f"<float>{y}</float>".encode(), 1)
    graph = CafGraph(pack(original))
    assert not graph.diagrams()["errors"]
    assert graph.diagram(REF)["blocks"][0]["layout"] == {
        "x": x,
        "y": y,
        "opaque_code": 0,
    }
    result, _ = graph.rewire_sources([change()])
    assert CafArchive(result).xml == original.replace(
        record(*shorts(0, 663, 2, 513)).encode(), record(*shorts(1, 663, 2, 513)).encode(), 1
    )
    assert CafGraph(result).diagram(REF)["blocks"][0]["layout"] == {
        "x": x,
        "y": y,
        "opaque_code": 0,
    }
    assert graph.archive.xml == original


@pytest.mark.parametrize(
    "boolean,expected", [("0", False), ("1", True), ("false", False), ("true", True)]
)
def test_native_boolean_spellings_are_preserved(boolean, expected):
    graph = CafGraph(make_graph(boolean=boolean))
    assert graph.diagram(REF)["connections"][0]["continuation"]["flag"] is expected
    result, _ = graph.rewire_sources([change()])
    assert f"<boolean>{boolean}</boolean>".encode() in CafArchive(result).xml


def test_rewire_changes_only_one_native_source_index_and_preserves_archive_metadata():
    graph = CafGraph(make_graph())
    original = graph.archive.xml
    result, report = graph.rewire_sources([change()])
    old = record(*shorts(0, 663, 2, 513)).encode()
    new = record(*shorts(1, 663, 2, 513)).encode()
    assert CafArchive(result).xml == original.replace(old, new, 1)
    assert report[0]["old"] == [0, 663, 2, 513]
    assert report[0]["new"] == [1, 663, 2, 513]
    assert "unverified" in report[0]["validation"]
    assert report[0]["source_sha256"] != report[0]["result_sha256"]
    with zipfile.ZipFile(io.BytesIO(result)) as archive:
        assert archive.comment == b"archive-comment"
        info = archive.infolist()[0]
        assert info.comment == b"entry-comment"
        assert info.date_time == (2020, 2, 3, 4, 5, 6)
        assert info.external_attr == 0o600 << 16
    assert graph.archive.xml == original


def test_rewire_no_op_is_byte_exact():
    data = make_graph()
    graph = CafGraph(data)
    assert graph.rewire_sources([]) == (data, [])
    assert graph.rewire_sources([change(source_ref=REF + ".2_10")]) == (data, [])


def test_batch_source_swaps_are_staged_before_native_bytes_are_changed():
    graph = CafGraph(make_graph())
    result, report = graph.rewire_sources(
        [change(), change(wire_index=1, old=[1, 663, 3, 513], source_ref=REF + ".2_10")]
    )
    assert len(report) == 2
    assert [wire["raw"] for wire in CafGraph(result).diagram(REF)["connections"]] == [
        [1, 663, 2, 513],
        [0, 663, 3, 513],
    ]
    with pytest.raises(ValueError, match="conflict"):
        graph.rewire_sources([change(), change(wire_index=1, old=[0, 663, 3, 513])])
    assert graph.archive.xml == CafArchive(make_graph()).xml


@pytest.mark.parametrize(
    "updates,message",
    [
        ({"old": [1, 663, 2, 513]}, "conflict"),
        ({"old": [False, 663, 2, 513]}, "conflict"),
        ({"wire_index": True}, "invalid"),
        ({"wire_index": -1}, "invalid"),
        ({"wire_index": 99}, "not found"),
        ({"source_ref": REF + ".2_99"}, "existing block"),
        ({"source_ref": REF + ".2_12"}, "configuration/type"),
        ({"unexpected": True}, "require"),
    ],
)
def test_rewire_rejects_ambiguous_requests(updates, message):
    with pytest.raises(ValueError, match=message):
        CafGraph(make_graph()).rewire_sources([change(**updates)])


def test_rewire_rejects_duplicate_changes_and_unknown_versions():
    with pytest.raises(ValueError, match="Duplicate"):
        CafGraph(make_graph()).rewire_sources([change(), change()])
    with pytest.raises(ValueError, match="version 1.0"):
        CafGraph(make_graph(version="2.0")).rewire_sources([change()])


def test_rewire_keeps_opaque_type_configuration_and_simulation_metadata_in_signature():
    graph = CafGraph(make_graph())
    old = prop("9998", "<opaque><unsignedShort>44</unsignedShort></opaque>").encode()
    xml = graph.archive.xml
    start = xml.index((f'ref="{REF}.2_11"').encode())
    prefix, suffix = xml[:start], xml[start:]
    xml = prefix + suffix.replace(old, old.replace(b"44", b"45"), 1)
    with pytest.raises(ValueError, match="configuration/type"):
        CafGraph(pack(xml)).rewire_sources([change()])


def test_rewire_requires_preexisting_outgoing_port_and_prior_execution():
    graph = CafGraph(make_graph())
    xml = graph.archive.xml.replace(
        record(*shorts(1, 663, 3, 513)).encode(), record(*shorts(1, 85, 3, 513)).encode()
    )
    with pytest.raises(ValueError, match="already be used"):
        CafGraph(pack(xml)).rewire_sources([change()])
    with pytest.raises(ValueError, match="execute before"):
        CafGraph(make_graph(sequence=[0, 2, 1, 3])).rewire_sources([change()])


def test_opaque_leaf_text_whitespace_is_significant_to_native_source_comparison():
    original = CafArchive(make_graph()).xml
    original = original.replace(
        b"<opaque><unsignedShort>44</unsignedShort></opaque>",
        b"<opaque><string>space-sensitive</string></opaque>",
    )
    start = original.index((f'ref="{REF}.2_11"').encode())
    xml = original[:start] + original[start:].replace(
        b"<string>space-sensitive</string>", b"<string> space-sensitive </string>", 1
    )
    with pytest.raises(ValueError, match="configuration/type"):
        CafGraph(pack(xml)).rewire_sources([change()])


def test_rewire_cannot_join_feedback_even_if_source_precedes_target():
    graph = CafGraph(make_graph(extra_wire=(2, 85, 1, 513)))
    with pytest.raises(ValueError, match="feedback cycle"):
        graph.rewire_sources([change()])


@pytest.mark.parametrize(
    "old,new,message",
    [
        (b'<BACoid id="2">10</BACoid>', b'<BACoid id="2">99</BACoid>', "missing"),
        (b'objectid="10"', b'objectid="99"', "identity"),
        (
            b"<unsignedShort>663</unsignedShort>",
            b"<unsignedShort>999999</unsignedShort>",
            "unsigned range",
        ),
        (b"<boolean>1</boolean>", b"<boolean>maybe</boolean>", "boolean"),
    ],
)
def test_malformed_native_graph_is_reported_without_guessing(old, new, message):
    original = CafArchive(make_graph())
    graph = CafGraph(pack(original.xml.replace(old, new, 1)))
    inventory = graph.diagrams()
    assert not inventory["diagrams"]
    assert message in inventory["errors"][0]["error"]
    with pytest.raises(ValueError, match=message):
        graph.diagram(REF)


def test_duplicate_native_graph_properties_are_rejected_before_inspection():
    original = CafArchive(make_graph())
    malformed = original.xml.replace(b'<property id="3117">', b'<property id="3118">', 1)
    with pytest.raises(ValueError, match="duplicate property identifiers"):
        CafGraph(pack(malformed))


def test_byte_rewriter_refuses_unobserved_lexical_serialization_without_reformatting():
    xml = CafArchive(make_graph()).xml.replace(b'<property id="3118">', b"<property id='3118'>")
    graph = CafGraph(pack(xml))
    assert graph.diagram(REF)["connections"]
    with pytest.raises(ValueError, match="serialization"):
        graph.rewire_sources([change()])


def connection(**updates):
    result = {
        "diagram_ref": REF,
        "prototype_diagram_ref": REF,
        "prototype_wire_index": 0,
        "prototype_old": [0, 663, 2, 513],
        "source_ref": REF + ".2_11",
        "target_ref": REF + ".2_13",
        "old_connection_count": 1,
    }
    result.update(updates)
    return result


def test_add_native_connection_appends_only_tuple_and_parallel_continuation_record():
    graph = CafGraph(make_graph(wires=[(0, 663, 2, 513)]))
    original = graph.archive.xml
    original_crc, original_size = graph.archive.info.CRC, graph.archive.info.file_size
    result, report = graph.add_connections([connection()])
    expected = original.replace(
        prop("3118", "<array>" + record(*shorts(0, 663, 2, 513)) + "</array>").encode(),
        prop(
            "3118",
            "<array>"
            + record(*shorts(0, 663, 2, 513))
            + record(*shorts(1, 663, 3, 513))
            + "</array>",
        ).encode(),
    ).replace(
        b'</listof></data></property><property id="9999">',
        record("<boolean>0</boolean>", "<string />").encode()
        + b'</listof></data></property><property id="9999">',
    )
    assert CafArchive(result).xml == expected
    converted = CafGraph(result).diagram(REF)
    assert converted["connections"][-1]["raw"] == [1, 663, 3, 513]
    assert converted["connections"][-1]["continuation"] == {"flag": False, "text": ""}
    assert len(CafArchive(result).objects) == len(graph.archive.objects)
    assert converted["execution_order"] == graph.diagram(REF)["execution_order"]
    assert report[0]["prototype_old"] == [0, 663, 2, 513]
    assert report[0]["old_connection_count"] == 1
    assert "unverified" in report[0]["validation"]
    assert graph.archive.xml == original
    assert (graph.archive.info.CRC, graph.archive.info.file_size) == (original_crc, original_size)
    assert graph.add_connections([]) == (graph.archive.original, [])


@pytest.mark.parametrize(
    "updates,message",
    [
        ({"old_connection_count": 0}, "original connection count"),
        ({"old_connection_count": True}, "invalid"),
        ({"prototype_wire_index": True}, "invalid"),
        ({"prototype_wire_index": 99}, "prototype index"),
        ({"prototype_old": [True, 663, 2, 513]}, "prototype tuple"),
        ({"prototype_old": [1, 663, 2, 513]}, "prototype tuple"),
        ({"source_ref": REF + ".2_12"}, "configuration/type"),
        ({"target_ref": REF + ".2_11"}, "configuration/type"),
        ({"target_ref": REF + ".2_12"}, "already has a writer"),
        ({"source_ref": "missing"}, "existing blocks"),
        ({"extra": "never ignore"}, "require"),
    ],
)
def test_native_connection_creation_rejects_stale_or_unproven_schema(updates, message):
    graph = CafGraph(make_graph(wires=[(0, 663, 2, 513)]))
    with pytest.raises(ValueError, match=message):
        graph.add_connections([connection(**updates)])


def test_native_connection_creation_rejects_order_feedback_duplicate_writers_and_future_versions():
    with pytest.raises(ValueError, match="execute before"):
        CafGraph(make_graph(wires=[(0, 663, 2, 513)], sequence=[0, 2, 3, 1])).add_connections(
            [connection()]
        )
    with pytest.raises(ValueError, match="feedback cycle"):
        CafGraph(make_graph(wires=[(0, 663, 2, 513), (3, 85, 1, 513)])).add_connections(
            [connection(old_connection_count=2)]
        )
    with pytest.raises(ValueError, match="already has a writer"):
        CafGraph(make_graph(wires=[(0, 663, 2, 513)])).add_connections([connection(), connection()])
    with pytest.raises(ValueError, match="class/version 1.0"):
        CafGraph(make_graph(version="2.0", wires=[(0, 663, 2, 513)])).add_connections(
            [connection()]
        )


def test_native_connection_creation_rejects_unknown_endpoint_configuration():
    graph = CafGraph(make_graph(wires=[(0, 663, 2, 513)]))
    xml = graph.archive.xml
    start = xml.index((f'ref="{REF}.2_13"').encode())
    xml = xml[:start] + xml[start:].replace(
        b"<unsignedShort>44</unsignedShort>", b"<unsignedShort>45</unsignedShort>", 1
    )
    with pytest.raises(ValueError, match="configuration/type"):
        CafGraph(pack(xml)).add_connections([connection()])


def test_native_connection_can_use_a_same_archive_prototype_to_populate_empty_lists():
    first = CafArchive(make_graph(wires=[(0, 663, 2, 513)])).xml
    second = CafArchive(make_graph(wires=[])).xml
    second = second.replace(REF.encode(), REF.replace("575_1", "575_2").encode())
    second = second.replace(b"<array></array>", b"<array />").replace(
        b"<listof></listof>", b"<listof />"
    )
    body = second[second.index(b">", second.index(b"<objects")) + 1 : second.rindex(b"</objects>")]
    graph = CafGraph(pack(first.replace(b"</objects>", body + b"</objects>")))
    new_ref = REF.replace("575_1", "575_2")
    result, _ = graph.add_connections(
        [
            connection(
                diagram_ref=new_ref,
                source_ref=new_ref + ".2_11",
                target_ref=new_ref + ".2_13",
                old_connection_count=0,
            )
        ]
    )
    assert CafGraph(result).diagram(new_ref)["connections"][0]["raw"] == [1, 663, 3, 513]
    assert CafGraph(result).diagram(REF) == graph.diagram(REF)


def test_all_authorized_local_native_graphs_and_guarded_rewire_when_available():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR for undistributed authorized local CAFs.")
    files = list(Path(directory).rglob("*.caf"))
    assert files
    for path in files:
        data = path.read_bytes()
        graph = CafGraph(data)
        inventory = graph.diagrams()
        assert inventory["diagrams"] and not inventory["errors"]
        assert graph.rewire_sources([]) == (data, [])
        found = False
        for listed in inventory["diagrams"]:
            diagram = graph.diagram(listed["ref"])
            for wire in diagram["connections"]:
                signature = graph._source_signature(wire["source_ref"])
                for source in diagram["blocks"]:
                    if (
                        source["ref"] == wire["source_ref"]
                        or graph._source_signature(source["ref"]) != signature
                    ):
                        continue
                    try:
                        result, report = graph.rewire_sources(
                            [
                                {
                                    "diagram_ref": diagram["ref"],
                                    "wire_index": wire["index"],
                                    "old": wire["raw"],
                                    "source_ref": source["ref"],
                                }
                            ]
                        )
                    except ValueError:
                        continue
                    assert report and result != data
                    assert CafGraph(result).diagrams()["errors"] == []
                    assert path.read_bytes() == data
                    found = True
                    break
                if found:
                    break
            if found:
                break
        assert found, "No guarded existing-source substitution was established in this archive."


def test_add_connection_in_each_authorized_local_archive_when_available():
    directory = os.environ.get("BMS_TEST_CAF_DIR")
    if not directory:
        pytest.skip("Set BMS_TEST_CAF_DIR for undistributed authorized local CAFs.")
    files = list(Path(directory).rglob("*.caf"))
    assert files
    for path in files:
        data = path.read_bytes()
        graph = CafGraph(data)
        found = False
        for listed in graph.diagrams()["diagrams"]:
            diagram = graph.diagram(listed["ref"])
            groups = defaultdict(list)
            for block in diagram["blocks"]:
                groups[graph._source_signature(block["ref"])].append(block)
            for wire in diagram["connections"]:
                targets = groups[graph._source_signature(wire["target_ref"])]
                sources = groups[graph._source_signature(wire["source_ref"])]
                for target in targets:
                    if any(
                        w["target_ref"] == target["ref"] and w["target_port"] == wire["target_port"]
                        for w in diagram["connections"]
                    ):
                        continue
                    for source in sources:
                        if source["execution_index"] >= target["execution_index"]:
                            continue
                        try:
                            result, report = graph.add_connections(
                                [
                                    {
                                        "diagram_ref": diagram["ref"],
                                        "prototype_diagram_ref": diagram["ref"],
                                        "prototype_wire_index": wire["index"],
                                        "prototype_old": wire["raw"],
                                        "source_ref": source["ref"],
                                        "target_ref": target["ref"],
                                        "old_connection_count": len(diagram["connections"]),
                                    }
                                ]
                            )
                        except ValueError:
                            continue
                        actual = CafGraph(result)
                        assert (
                            len(actual.diagram(diagram["ref"])["connections"])
                            == len(diagram["connections"]) + 1
                        )
                        assert list(actual.archive.objects) == list(graph.archive.objects)
                        assert report and path.read_bytes() == data
                        found = True
                        break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        assert found, "No native connection addition from an existing prototype was established."
