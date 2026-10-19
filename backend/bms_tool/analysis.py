"""Bounded dependency and edit-impact analysis, including feedback boundaries."""

from .engine import execution_order


def dependencies(program, node_id):
    nodes = {n.id: n for n in program.nodes}
    if node_id not in nodes:
        raise ValueError("Select an existing block to trace dependencies.")
    edges = [e for e in program.edges if e.source in nodes and e.target in nodes]
    incoming = {node: [] for node in nodes}
    outgoing = {node: [] for node in nodes}
    for edge in edges:
        incoming[edge.target].append(edge)
        outgoing[edge.source].append(edge)

    def closure(backwards):
        seen, pending = {node_id}, [node_id]
        while pending:
            current = pending.pop()
            for edge in (incoming if backwards else outgoing)[current]:
                related = edge.source if backwards else edge.target
                if related not in seen:
                    seen.add(related)
                    pending.append(related)
        return sorted(seen - {node_id})

    def describe(id):
        node = nodes[id]
        return {"id": id, "kind": node.kind, "label": node.label, "unit": node.unit}

    def wire(edge):
        return {**edge.model_dump(), "previous_scan": nodes[edge.target].kind == "Delay"}

    upstream, downstream = closure(True), closure(False)
    reachable = {node_id, *downstream}
    try:
        scan_index = execution_order(program).index(node_id)
    except ValueError:
        scan_index = None
    return {
        "scope": "Portable core graph",
        "native_extension_present": "native_sedona" in program.metadata,
        "node": describe(node_id),
        "incoming": [wire(e) for e in incoming[node_id]],
        "outgoing": [wire(e) for e in outgoing[node_id]],
        "upstream": [describe(id) for id in upstream],
        "downstream": [describe(id) for id in downstream],
        "affected_outputs": [
            describe(id) for id in [node_id, *downstream] if nodes[id].kind == "Output"
        ],
        "feedback_boundaries": [
            wire(e) for e in edges if e.source in reachable and nodes[e.target].kind == "Delay"
        ],
        "scan_index": scan_index,
        "broken_links": len(program.edges) - len(edges),
    }
