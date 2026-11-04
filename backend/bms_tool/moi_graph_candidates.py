"""Bounded candidate search over actual native members, pins and directed paths.

Search proposes a witness only. The existing profile inspector independently
re-checks it before any source-qualified capability is reported. No file is
compiled, written, allocated or transferred here.
"""


def members(mask):
    while mask:
        bit = mask & -mask
        yield bit.bit_length() - 1
        mask ^= bit


class GraphCandidates:
    def __init__(self, graph, wires, signatures):
        self.graph, self.wires = graph, wires
        self.blocks = {row["index"]: row for row in graph["blocks"]}
        self.signatures = signatures
        self.groups, self.outputs, self.occupied = {}, {}, {}
        self.ancestors = {i: 1 << i for i in self.blocks}
        for i, row in self.blocks.items():
            signature = signatures[row["ref"]]
            self.groups[signature] = self.groups.get(signature, 0) | (1 << i)
        for wire in wires:
            src, _, dst, port = wire["old"]
            output = (signatures[wire["source_ref"]], wire["source_port"])
            self.outputs[output] = self.outputs.get(output, 0) | (1 << src)
            self.occupied[port] = self.occupied.get(port, 0) | (1 << dst)
            self.ancestors[dst] |= 1 << src
        # Warshall with at most 512-bit sets: each member pair is considered once,
        # rather than reparsing a diagram/DFS for every edge and candidate source.
        for via in self.blocks:
            bit, predecessors = 1 << via, self.ancestors[via]
            for target in self.blocks:
                if self.ancestors[target] & bit:
                    self.ancestors[target] |= predecessors
        self.later, self.earlier = {}, {}
        seen, all_members = 0, (1 << len(self.blocks)) - 1
        for i in graph["execution_order"]:
            self.earlier[i] = seen
            seen |= 1 << i
            self.later[i] = all_members ^ seen

    def sources(self, wire):
        return self.outputs[(self.signatures[wire["source_ref"]], wire["source_port"])]

    def addition(self):
        for wire in self.wires:
            targets = (
                self.groups[self.signatures[wire["target_ref"]]]
                & ~self.occupied[wire["target_port"]]
            )
            if not targets:
                continue
            for src in members(self.sources(wire)):
                choices = targets & self.later[src] & ~self.ancestors[src]
                if choices:
                    return wire["index"], src, next(members(choices))
        return None

    def replacement(self):
        for wire in self.wires:
            old, _, dst, _ = wire["old"]
            choices = self.sources(wire) & self.earlier[dst] & ~(1 << old)
            limit = 1 << (8 * wire["source_index_bytes"])
            for src in members(choices):
                # Removing the selected incoming edge to dst cannot change paths
                # starting at dst: any return to that start is a removable cycle.
                if src < limit and not self.ancestors[src] & (1 << dst):
                    return wire["index"]
        return None


def eligible_wire(editor):
    failure = None
    for diagram in editor.reader.summary()["diagrams"]:
        try:
            graph, _, _, wires = editor.graph(diagram["ref"])
            index = GraphCandidates(graph, wires, editor.signatures).replacement()
            if index is not None:
                info = editor.inspect(diagram["ref"], index)
                if not info["available"]:
                    raise ValueError("Native source search disagrees with its profile inspector.")
                return {
                    "diagram_ref": diagram["ref"],
                    "wire_index": index,
                    "candidate_count": len(info["candidates"]) - 1,
                }, failure
        except ValueError as exc:
            failure = str(exc)[:512]
    return None, failure


def eligible_connection(compiler):
    failure = None
    for diagram in compiler.wire.reader.summary()["diagrams"]:
        try:
            ref = diagram["ref"]
            initial = compiler.inspect(ref, 0)
            if not initial["prototype"]:
                continue
            if not initial["budget_available"]:
                failure = "A new native connection exceeds the existing connection/tag budget."
                continue
            graph, _, _, wires = compiler.wire.graph(ref)
            found = GraphCandidates(graph, wires, compiler.wire.signatures).addition()
            if found is None:
                continue
            index, src, dst = found
            blocks = {row["index"]: row for row in graph["blocks"]}
            source_ref, target_ref = blocks[src]["ref"], blocks[dst]["ref"]
            info = compiler.inspect(ref, index, source_ref)
            if not info["available"] or not any(
                row["ref"] == target_ref for row in info["targets"]
            ):
                raise ValueError("Native connection search disagrees with its profile inspector.")
            return {
                "diagram_ref": ref,
                "prototype_index": index,
                "prototype_old": info["prototype"]["old"],
                "source_ref": source_ref,
                "target_ref": target_ref,
                "source_index": src,
                "target_index": dst,
                "source_candidate_count": len(info["sources"]),
                "target_candidate_count": len(info["targets"]),
                "connection_count": info["connection_count"],
                "block_count": info["block_count"],
                "continuation_metadata": info["continuation_metadata"],
                "source_sha256": compiler.editor.source_sha256,
                "record_sha256": info["record_sha256"],
                "property_sha256": info["property_sha256"],
                "metadata_property_sha256": info["metadata_property_sha256"],
            }, failure
        except ValueError as exc:
            failure = str(exc)[:512]
    return None, failure
