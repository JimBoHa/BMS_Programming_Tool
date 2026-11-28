"""Encode and reopen typed Activity boundaries in a local inline program draft."""

from collections import Counter, defaultdict
from dataclasses import dataclass

from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    Unsigned,
)

from .moi_application import _list, _structs
from .moi_identity import MoiIdentity, sha
from .native_inline_activity_plan import ACTIVITY_LIMIT, ROOT, boundary, plan_activities
from .native_inline_monitor import atoms, record
from .native_inline_sequence import _wire, get_ref
from .native_inputs import archive, encoded, record_instance, replace_properties
from .native_root_layout import CONTINUATION, POSITION, _row


@dataclass(frozen=True)
class Port:
    scope: str
    origin: tuple
    output: bool


class ActivityDrawing:
    def __init__(self, original, image, report):
        self.app = MoiIdentity(image)
        self.root_ref = report["root_ref"]
        self.refs = self.app.reader.records
        self.plan = plan_activities(original, self.app, report)
        self.origins = {}
        self.attributes = {}
        self.identifiers = {i: ObjectIdentifier(b["object"]) for i, b in self.plan.blocks.items()}
        self.instances = {}
        self.pin_class = {}
        self.connections = {}
        self._add_ports(report)
        self._route_connections()

    def _add_ports(self, report):
        plan = self.plan
        taken = {record_instance(self.app, r) for r in self.app.records}
        declared = (self.app.reader.scalar(r, 75) for r in self.app.records)
        taken.update(int(ObjectIdentifier(oid)[1]) for oid in declared if oid)
        next_id = max(
            max(int(ObjectIdentifier(o)[1]) for o in report["added_objects"]) + 1,
            report["first_instance"],
        )

        def allocate():
            nonlocal next_id
            while next_id in taken:
                next_id += 1
            if next_id >= 4_194_303:
                raise ValueError("Insufficient object instances for the nested inline program.")
            value = next_id
            taken.add(value)
            next_id += 1
            return value

        source_ports = defaultdict(list)
        for ref, r in self.refs.items():
            if r["class_id"] in (526, 527, 530, 531):
                source_ports[ref.rpartition(".")[0], self.app.reader.scalar(r, 3365)].append(r)
        for scope in plan.children:
            inside = [i for i in plan.blocks if scope in plan.ancestors(i)]
            incoming, outgoing = boundary(plan.edges, inside)
            self.origins[scope] = incoming, outgoing
            if scope == ROOT:
                continue
            self.instances[scope] = allocate()
            self.identifiers[scope] = ObjectIdentifier((536, self.instances[scope]))
            for output, signals in ((False, incoming), (True, outgoing)):
                for number, origin in enumerate(signals):
                    node, attribute = origin
                    ref = plan.blocks[node]["ref"]
                    port = self.refs[ref]
                    if port["class_id"] not in (526, 530) or attribute != 663:
                        matches = source_ports[ref, attribute]
                        if len(matches) != 1:
                            raise ValueError(
                                f"The source connection at {ref}, attribute {attribute}, has no unique typed native port."
                            )
                        port = matches[0]
                    public_type = int(ObjectIdentifier(self.app.reader.scalar(port, 75))[0])
                    if (port["class_id"], public_type) not in (
                        (526, 2),
                        (527, 2),
                        (530, 5),
                        (531, 5),
                    ):
                        raise ValueError(
                            "The Activity boundary requires a Float or Boolean signal."
                        )
                    key = Port(scope, origin, output)
                    self.pin_class[key] = (526 if public_type == 2 else 530) + int(output)
                    self.identifiers[key] = ObjectIdentifier((public_type, allocate()))
                    self.attributes[key] = (8000 if output else 7000) + number

    def _route_connections(self):
        plan = self.plan
        ancestors = {i: set(plan.ancestors(i)) for i in plan.blocks}
        for scope in plan.children:
            wires = {}
            for source, src_port, target, dst_port in plan.edges:
                inside_source = scope in ancestors[source]
                inside_target = scope in ancestors[target]
                if not (inside_source or inside_target):
                    continue
                origin = source, src_port
                start = (
                    plan.child_of(source, scope) if inside_source else Port(scope, origin, False)
                )
                end = plan.child_of(target, scope) if inside_target else Port(scope, origin, True)
                if start == end and isinstance(start, str):
                    continue
                if isinstance(start, str):
                    src_port = self.attributes[Port(start, origin, True)]
                elif isinstance(start, Port):
                    src_port = 663
                if isinstance(end, str):
                    dst_port = self.attributes[Port(end, origin, False)]
                elif isinstance(end, Port):
                    dst_port = 513
                wires[start, src_port, end, dst_port] = None
            self.connections[scope] = list(wires)

    def path(self, scope):
        if scope == ROOT:
            return self.root_ref
        return self.path(self.plan.parent[scope]) + f".536_{self.instances[scope]}"

    def members(self, scope, *, execution=False):
        ins, outs = self.origins[scope]
        body = self.plan.root_order if execution and scope == ROOT else self.plan.children[scope]
        return [*(Port(scope, k, False) for k in ins), *body, *(Port(scope, k, True) for k in outs)]

    def _existing_layout(self):
        app = self.app
        root = self.refs[self.root_ref]
        owners = [
            r
            for r in app.records
            if (r["class_id"] == 127 or r["offset"] == root["offset"])
            and {3383, 3384} & r["properties"].keys()
        ]
        if not owners:
            return None, [], []
        if len(owners) != 1:
            raise ValueError("Conflicting root drawing owners.")
        owner = owners[0]
        if (
            {3383, 3384} - owner["properties"].keys()
            or record_instance(app, owner) != record_instance(app, root)
            or (owner["class_id"] == 127 and owner["offset"] != app.records[-1]["offset"])
        ):
            raise ValueError("Incomplete or misplaced root drawing.")
        pos = _structs(owner["properties"][3383]["tags"], POSITION)
        rows = _structs(owner["properties"][3384]["tags"], CONTINUATION)
        if len(pos) != len(self.plan.blocks) or len(rows) != len(self.plan.edges):
            raise ValueError("Root positions or continuations do not match the flat drawing.")
        return owner, pos, rows

    def _drawings(self):
        owner, positions, continuations = self._existing_layout()
        styles = {}
        for rec in self.app.records:
            props = rec["properties"]
            if rec["class_id"] != 536 or not {3375, 3383} <= props.keys():
                continue
            members = _list(props[3375]["tags"], ObjectIdentifier)
            flags = _structs(props[3383]["tags"], POSITION)
            if len(members) == len(flags):
                for obj, value in zip(members, flags, strict=True):
                    styles.setdefault(int(obj[0]), int(value[2]))
        original_wires = dict(zip(self.plan.edges, continuations, strict=bool(continuations)))
        result = {}
        for scope in self.plan.children:
            members = self.members(scope)
            index = {member: n for n, member in enumerate(members)}
            wires = self.connections[scope]
            geometry = []
            for n, member in enumerate(members):
                if positions and scope == ROOT and isinstance(member, int):
                    x, y, style = positions[member]
                else:
                    x, y, style = (
                        (n % 7) * 120,
                        (n // 7) * 72,
                        styles.get(int(self.identifiers[member][0]), 0),
                    )
                geometry.append(_row(Real(x), Real(y), Unsigned(style)))
            continuation_rows = []
            for wire in wires:
                enabled, label = (
                    original_wires.get(wire, (False, "")) if scope == ROOT else (False, "")
                )
                continuation_rows.append(_row(Boolean(enabled), CharacterString(label)))
            result[scope] = {
                3375: atoms(ObjectIdentifier, [self.identifiers[m] for m in members]),
                3117: atoms(Unsigned, [index[m] for m in self.members(scope, execution=True)]),
                3118: b"".join(_wire(index[a], p, index[b], q) for a, p, b, q in wires),
                3383: b"".join(geometry),
                3384: b"".join(continuation_rows),
            }
        return owner, result

    def _records(self, drawings):
        additions = []
        for scope, instance in self.instances.items():
            prefix, number = scope.split("-")
            label = ("Airflow samples " if prefix == "samples" else "Inline calculation ") + number
            pins = [p for p in self.members(scope) if isinstance(p, Port)]
            fields = {
                2390: encoded(CharacterString(label)),
                3373: encoded(Boolean(True)),
                3670: encoded(Enumerated(0)),
                3184: atoms(Enumerated, [self.attributes[p] for p in pins]),
            }
            additions.append(
                record(536, instance, 536, self.path(scope), {**drawings[scope], **fields})
            )
            for p in pins:
                obj = self.identifiers[p]
                cid = self.pin_class[p]
                label = self.plan.blocks[p.origin[0]]["name"][:46]
                fields = {
                    2390: encoded(CharacterString(label)),
                    3365: encoded(Enumerated(self.attributes[p])),
                    3670: encoded(Enumerated({526: 230, 527: 233, 530: 232, 531: 235}[cid])),
                }
                additions.append(
                    record(
                        cid,
                        int(obj[1]),
                        int(obj[0]),
                        self.path(scope) + f".{int(obj[0])}_{int(obj[1])}",
                        fields,
                    )
                )
        return additions

    def encode(self):
        owner, drawings = self._drawings()
        additions = self._records(drawings)
        app = self.app
        if len(app.records) + len(additions) > 3000:
            raise ValueError("Nested inline drawing exceeds the supported native object budget.")
        moved = {
            b["ref"]: self.path(self.plan.parent[i]) + "." + b["ref"].rsplit(".", 1)[-1]
            for i, b in self.plan.blocks.items()
            if self.plan.parent[i] != ROOT
        }
        blocks = {k: drawings[ROOT][k] for k in (3375, 3117, 3118)}
        layout = {k: drawings[ROOT][k] for k in (3383, 3384)}
        root_offset = self.refs[self.root_ref]["offset"]
        owner_offset = owner["offset"] if owner else None
        insertion = len(app.records) - int(app.records[-1]["class_id"] == 127)
        ordered = []
        unchanged = {}
        for i, r in enumerate(app.records):
            if i == insertion:
                ordered.extend(additions)
            off = r["offset"]
            ref = get_ref(app, r) or ""
            top = (
                self.root_ref + "." + ref[len(self.root_ref) + 1 :].split(".", 1)[0]
                if ref.startswith(self.root_ref + ".")
                else None
            )
            fields = {}
            if off == root_offset:
                fields.update(blocks)
            if off == owner_offset:
                fields.update(layout)
            if top in moved:
                fields[32527] = encoded(CharacterString(moved[top] + ref[len(top) :]))
            if fields:
                raw = replace_properties(app, r, fields)
            else:
                raw = app.data[off : r["end_offset"]]
                unchanged[raw[6:10]] = r["sha256"]
            ordered.append(raw)
        if insertion == len(app.records):
            ordered.extend(additions)
        payload = archive(app, ordered)
        reopened = MoiIdentity(payload)
        if reopened.reader.errors or len(reopened.records) != len(ordered):
            raise ValueError("The complete nested application could not be reopened.")
        images = {
            reopened.data[r["offset"] + 6 : r["offset"] + 10]: r["sha256"] for r in reopened.records
        }
        if len(images) != len(ordered) or any(
            images.get(oid) != digest for oid, digest in unchanged.items()
        ):
            raise ValueError("An unchanged native record differs in the nested application.")
        self.verify(reopened)
        return payload, {
            "activities_added": len(self.instances),
            "boundary_records_added": len(self.attributes),
            "added_objects": [
                str(oid) for k, oid in self.identifiers.items() if not isinstance(k, int)
            ],
            "root_members": len(self.members(ROOT)),
            "largest_activity_members": max(len(self.members(k)) for k in self.instances),
            "signal_connections_traced": len(self.plan.edges),
            "unchanged_records_checked": len(unchanged),
            "flattened_schedule_verified": True,
            "record_count": len(reopened.records),
            "flat_sha256": sha(app.source),
        }

    def verify(self, reopened):
        """Trace the reparsed hierarchy back to every original signal and execution dependency."""
        by_id = {str(oid): k for k, oid in self.identifiers.items()}
        if len(by_id) != len(self.identifiers):
            raise ValueError("Duplicate native public identifier in the grouped drawing.")
        links = defaultdict(list)
        orders = {}
        for scope in self.plan.children:
            graph = reopened.reader.diagram(self.path(scope), retained_activity_refs=True)
            blocks = graph["blocks"]
            if scope != ROOT:
                parent = reopened.reader.records[self.path(scope)]
                declared = _list(parent["properties"][3184]["tags"], Enumerated)
                expected = [self.attributes[p] for p in self.members(scope) if isinstance(p, Port)]
                if parent["class_id"] != 536 or list(map(int, declared)) != expected:
                    raise ValueError(
                        "Activity port declarations differ from their captured signal types."
                    )
                positions = _structs(parent["properties"][3383]["tags"], POSITION)
                bends = _structs(parent["properties"][3384]["tags"], CONTINUATION)
                if len(positions) != len(blocks) or len(bends) != len(graph["connections"]):
                    raise ValueError(
                        "An Activity layout does not cover its blocks and connections."
                    )
            if scope != ROOT and len(blocks) > ACTIVITY_LIMIT:
                raise ValueError("A new Activity exceeded its drawing bound.")
            keys = [by_id[b["object"]] for b in blocks]
            local = {b["ref"]: k for b, k in zip(blocks, keys, strict=True)}
            orders[scope] = [keys[i] for i in graph["execution_order"]]
            if keys != self.members(scope) or orders[scope] != self.members(scope, execution=True):
                raise ValueError("A reparsed Activity member or execution position differs.")
            for b, k in zip(blocks, keys, strict=True):
                if not isinstance(k, Port):
                    continue
                descriptor = reopened.reader.records[b["ref"]]
                att = reopened.reader.scalar(descriptor, 3365)
                if descriptor["class_id"] != self.pin_class[k] or att != self.attributes[k]:
                    raise ValueError("A reparsed Activity port has a different type or assignment.")
                if k.output:
                    links[k, 513].append((scope, att))
                else:
                    links[scope, att].append((k, 663))
            wires = [
                (local[w["source_ref"]], w["source_port"], local[w["target_ref"]], w["target_port"])
                for w in graph["connections"]
            ]
            if wires != self.connections[scope]:
                raise ValueError("A reparsed Activity wire differs.")
            for a, p, b, q in wires:
                links[a, p].append((b, q))

        def destinations(node, path):
            if node in path:
                raise ValueError("Cycle across Activity boundary ports.")
            for endpoint in links[node]:
                if isinstance(endpoint[0], int):
                    yield endpoint
                else:
                    yield from destinations(endpoint, path | {node})

        flat = Counter(
            (a, p, b, q)
            for a, p in {(a, p) for a, p, _, _ in self.plan.edges}
            for b, q in destinations((a, p), set())
        )
        if flat != Counter(self.plan.edges):
            raise ValueError("A nested Activity changes the logical signal connections.")

        def leaves(scope):
            for m in orders[scope]:
                if isinstance(m, int):
                    yield m
                elif isinstance(m, str):
                    yield from leaves(m)

        self.plan.verify_order(list(leaves(ROOT)))
