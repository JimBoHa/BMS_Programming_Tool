"""Authored graph display metadata and module navigation fixtures."""

from bms_tool.caf import NS
from bms_tool.caf_graph import CafGraph

from .test_caf_graph import REF, make_graph, pack, prop, record, shorts


def nested_graph():
    module = REF + ".536_20"

    def diagram(ref, cid, instance, name, blocks):
        return (
            f'<object classid="{cid}" classVersion="1.0" ref="{ref}" objectid="{instance}">'
            + prop(75, f'<BACoid id="{cid}">{instance}</BACoid>')
            + prop(2390, f"<string>{name}</string>")
            + prop(
                3375,
                "<array>"
                + "".join(f'<BACoid id="{c}">{i}</BACoid>' for c, i in blocks)
                + "</array>",
            )
            + prop(3117, "<array>" + "".join(shorts(*range(len(blocks)))) + "</array>")
            + prop(3118, "<array/>")
            + prop(
                3383,
                "<listof>"
                + "".join(
                    record(
                        "<float>0</float>", "<float>0</float>", "<unsignedShort>0</unsignedShort>"
                    )
                    for _ in blocks
                )
                + "</listof>",
            )
            + prop(3384, "<listof/>")
            + "</object>"
        )

    root = diagram(REF, 575, 1, "Authored control sequence", [(536, 20)])
    child = diagram(module, 536, 20, "Valve module", [(2, 21)])
    leaf = (
        f'<object classid="526" classVersion="1.0" ref="{module}.2_21" objectid="21">'
        + prop(75, '<BACoid id="2">21</BACoid>')
        + prop(2390, "<string>Valve demand</string>")
        + prop(3113, "<float>35.000</float>")
        + "</object>"
    )
    return pack(f'<objects xmlns="{NS}">{root}{child}{leaf}</objects>'.encode())


def test_display_port_labels_cover_recorded_native_connections_without_changing_wire_records():
    graph = CafGraph(make_graph())
    before = graph.diagram(REF)
    assert set(before["port_labels"]) == {"526", "527"}
    assert "663" in before["port_labels"]["526"] and "513" in before["port_labels"]["527"]
    assert before["connections"][0]["raw"] == [0, 663, 2, 513]
    changed, _ = graph.rewire_sources(
        [
            {
                "diagram_ref": REF,
                "wire_index": 0,
                "old": [0, 663, 2, 513],
                "source_ref": REF + ".2_11",
            }
        ]
    )
    assert CafGraph(changed).diagram(REF)["port_labels"] == before["port_labels"]


def test_nested_module_refs_resolve_exactly_without_assuming_graph_class_is_bacnet_type():
    graph = CafGraph(nested_graph())
    inventory = graph.diagrams()
    assert not inventory["errors"] and len(inventory["diagrams"]) == 2
    root = graph.diagram(REF)
    assert root["blocks"][0]["ref"] == REF + ".536_20"
    child = graph.diagram(root["blocks"][0]["ref"])
    assert child["blocks"][0]["name"] == "Valve demand"
