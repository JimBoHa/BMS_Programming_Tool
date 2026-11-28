"""Partition a compiled release-62 inline sequence into native Activity drawings."""

import re
from collections import defaultdict
from dataclasses import dataclass

ROOT = "root"
PIN_LIMIT = 22
ACTIVITY_LIMIT = 40
SAMPLE_NAME = re.compile(r"Inline (?:airflow )?second (\d{2})(?: memory)?")
TUNINGS = {"VLV-LOCKOUT-CFM", "MAX-DA-T"}


def boundary(edges, members):
    members = set(members)
    inputs, outputs = set(), set()
    for source, port, target, _ in edges:
        if source in members:
            if target not in members:
                outputs.add((source, port))
        elif target in members:
            inputs.add((source, port))
    return sorted(inputs), sorted(outputs)


def _partition(segment, groups, group_of, edges):
    """Minimize subdrawings without cutting a backward dependency across Activities."""
    positions = {member: i for i, member in enumerate(segment)}
    forbidden = set()
    for source, _, target, _ in edges:
        before = positions.get(group_of[source])
        after = positions.get(group_of[target])
        if before is not None and after is not None and after < before:
            forbidden.update(range(after + 1, before + 1))
    # At each permitted cut retain the fewest drawings, then the smallest peak pin count.
    paths = {0: (0, 0, ())}
    for stop in range(1, len(segment) + 1):
        if stop in forbidden:
            continue
        for start in range(max(0, stop - ACTIVITY_LIMIT), stop):
            if start not in paths:
                continue
            members = segment[start:stop]
            ins, outs = boundary(edges, (i for member in members for i in groups[member]))
            pins = len(ins) + len(outs)
            if pins > PIN_LIMIT or len(members) + pins > ACTIVITY_LIMIT:
                continue
            count, peak, cuts = paths[start]
            cost = (count + 1, max(peak, pins))
            if stop not in paths or cost < paths[stop][:2]:
                paths[stop] = (*cost, (*cuts, stop))
    if len(segment) not in paths:
        raise ValueError("The inline sequence cannot fit the supported Activity drawing bounds.")
    cuts = (0, *paths[len(segment)][2])
    return [segment[a:b] for a, b in zip(cuts, cuts[1:], strict=False)]


@dataclass
class ActivityPlan:
    blocks: dict
    order: list
    edges: list
    protected: set
    children: dict
    parent: dict
    root_order: list

    def ancestors(self, key):
        while key in self.parent:
            key = self.parent[key]
            yield key

    def child_of(self, leaf, scope):
        while self.parent[leaf] != scope:
            leaf = self.parent[leaf]
        return leaf

    def verify_order(self, leaf_order):
        ranks = {node: i for i, node in enumerate(leaf_order)}
        flat = {node: i for i, node in enumerate(self.order)}
        if (
            len(leaf_order) != len(self.order)
            or set(ranks) != set(flat)
            or [i for i in leaf_order if i in self.protected]
            != [i for i in self.order if i in self.protected]
            or any((ranks[s] < ranks[t]) != (flat[s] < flat[t]) for s, _, t, _ in self.edges)
        ):
            raise ValueError(
                "Activity execution changes a block or the order of a signal dependency."
            )


def plan_activities(original, candidate, report):
    root = report["root_ref"]
    before = original.reader.diagram(root, retained_activity_refs=True)
    graph = candidate.reader.diagram(root, retained_activity_refs=True)
    blocks = {b["index"]: b for b in graph["blocks"]}
    by_ref = {b["ref"]: b["index"] for b in blocks.values()}
    order = graph["execution_order"]
    if len(blocks) > 512 or len(graph["connections"]) > 4096 or sorted(order) != sorted(blocks):
        raise ValueError("Incomplete or oversized native root schedule.")
    original_refs = {b["ref"] for b in before["blocks"]}
    if not original_refs <= by_ref.keys():
        raise ValueError("An original root member is missing from the inline program.")
    old = {by_ref[r] for r in original_refs}
    generated = set(report["added_objects"])
    if any(b["object"] not in generated for i, b in blocks.items() if i not in old):
        raise ValueError("An unaccounted native member appears in the proposed root.")
    tunings = [i for i, b in blocks.items() if i not in old and b["name"] in TUNINGS]
    if sorted(blocks[i]["name"] for i in tunings) != sorted(TUNINGS):
        raise ValueError("The inline drawing needs both exposed tuning values at the root.")
    protected = old | set(tunings)
    edges = [
        (by_ref[w["source_ref"]], w["source_port"], by_ref[w["target_ref"]], w["target_port"])
        for w in graph["connections"]
    ]
    sources = defaultdict(set)
    for source, _, target, _ in edges:
        sources[target].add(source)
    group_of, groups, clocks = {}, {}, []
    for node in order:
        name = blocks[node]["name"]
        group = node
        if node not in protected:
            match = SAMPLE_NAME.fullmatch(name)
            if match:
                second = int(match[1])
                if second >= 30:
                    raise ValueError("Unexpected sample outside the 30-second window.")
                group = f"samples-{second // 6 + 1}"
                if name == f"Inline second {second:02d}":
                    clocks.append(second)
            elif name.startswith(("Inline measured CFM sum", "Inline even clock sector")):
                inputs = {group_of.get(source) for source in sources[node]}
                if len(inputs) == 1:
                    common = next(iter(inputs))
                    if isinstance(common, str):
                        group = common
        group_of[node] = group
        groups.setdefault(group, []).append(node)
    if sorted(clocks) != list(range(30)):
        raise ValueError("Missing or duplicated sample gates in the 30-second inline program.")
    children = {
        k: v
        for k, v in sorted(
            ((k, v) for k, v in groups.items() if isinstance(k, str)), key=lambda item: item[0]
        )
    }
    for members in children.values():
        ins, outs = boundary(edges, members)
        if len(members) + len(ins) + len(outs) > ACTIVITY_LIMIT:
            raise ValueError("A six-second sample bank exceeds the Activity drawing bound.")
    stages, segment = [], []
    for item in [*groups, None]:
        if item is None or item in protected:
            if segment:
                stages.extend(_partition(segment, groups, group_of, edges))
                segment = []
        else:
            segment.append(item)
    children.update({f"stage-{n}": members for n, members in enumerate(stages, 1)})
    parent = {child: group for group, members in children.items() for child in members}
    original_positions = [i for i in blocks if i not in parent]
    if set(original_positions) != protected:
        raise ValueError("An existing member or an exposed setting would move into an Activity.")
    root_order = []
    for leaf in order:
        node = leaf
        while node in parent:
            node = parent[node]
        if node not in root_order:
            root_order.append(node)
    children[ROOT] = original_positions + [n for n in root_order if n not in protected]
    parent.update({node: ROOT for node in children[ROOT]})
    plan = ActivityPlan(blocks, order, edges, protected, children, parent, root_order)

    def expand(node):
        for child in root_order if node == ROOT else children[node]:
            if isinstance(child, int):
                yield child
            else:
                yield from expand(child)

    plan.verify_order(list(expand(ROOT)))
    return plan
