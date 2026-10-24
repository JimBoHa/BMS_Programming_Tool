"""Explicit version-two reusable activities with named, independently typed outputs.

Version-one macro schemas, services and emission remain a separate implementation.
Activity containers have no scalar value: a single shared instance graph supplies
one collision-checked ordinary alias per named output before execution.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from .models import Program, StrictModel
from .program_source import SourceMode, source_response

PROFILE = {
    "profile": "studio-activities/2",
    "library_version": 2,
    "archive_format": "bms-macro-library/2",
    "container": {"kind": "Activity", "value_type": "number", "unit": ""},
    "limits": {
        "definitions": 64,
        "definition_nodes": 4000,
        "depth": 8,
        "instances": 256,
        "expanded_nodes": 2000,
        "edges": 10000,
        "inputs": 32,
        "outputs": 32,
        "library_bytes": 4194304,
    },
    "aliases": {
        "encoding": "SHA256 of UTF-8 JSON.stringify string array, no whitespace; ASCII instance/output IDs under existing Node ID rules. Use first24 lowercase hex digits.",
        "output": "ao2_ + hash(['output', ...instance_path, output_id])",
        "node": "an2_ + hash(['node', ...instance_path, node_id])",
        "selector": "ac2_ + hash(['selector', ...instance_path])",
        "edge": "ae2_ + hash(['edge', ...edge_identity])",
        "collisions": "All aliases/ordinary/root/container IDs are checked; collision refuses instead of reseeding or replacing. No alias is a field address or authenticated native identity.",
    },
    "semantics": {
        "ports": "All definition Inputs are required. Each definition has1..32 named ordinary Output interfaces with exact Boolean/number type and unit. Source ports are case-sensitive Output node IDs; no implicitout. Ordinary nodes retainout only.",
        "state": "Each instance path expands once, sharing all Delay/PI/timer state among every output. Output aliases are zero-delay ordinary Switches, not extra published root outputs. No duplicated state per output or added feedback memory.",
        "nesting": "A v2 library contains Activity references only, no v1 Macro references or nested library objects. No hidden native extensions or physical terminals inside definitions. v1 libraries/archives remain unchanged until explicit promotion.",
        "migration": "Explicit preview/apply rewrites Macro containers to Activity/sentinel and each legacyout source port to the referenced single Output ID once across root/shared definitions. No state/force transfer. Review digest is stateless source/provenance admission, not server CAS or field permission.",
        "source": "Original hierarchy/IDs/parameter and metadata numeric atoms remain editable. Canonical source bytes plus definition name decide conflicts, including signed zero and integer/float distinctions; key reorder is idempotent. No source codec/numeric/symbol profile or arithmetic/SDK changes.",
        "bindings": "Executable expansion returns source/expanded digests and per-output aliases. Incomplete editor graphs retain catalog handles but no active resolve/force authority. Portable output forces name exact bound aliases in the existing force map; container scalar forces are unsupported. Source changes retire stale mappings/forces/sessions in the UI.",
        "targets": "Current portable JSON/STV3/PLCopen/GraphML and existing target source encoders consume ordinary expanded graphs. Each target still has its own numeric/clock/resources/quality/native acceptance limits. Native host forcing and private native activity-port visibility are not inferred.",
    },
    "sources": [
        {
            "document": "LIT-12011147",
            "title": "Controller Tool Help",
            "edition": "18.0",
            "date": "2025-10-06",
            "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
            "pdf_pages": [43, 224, 225, 905, 1278, 1279, 1297],
            "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
            "scope": "Multiple named typed output roles in reusable activities; not proprietary algorithms, Enum codes or native CAF encoding.",
        }
    ],
    "gaps": [
        "native JCI/ALC activity algorithms, Enum/reliability mapping, CAF/packages/compiler/transfer",
        "physical I/O, controller state/force migration, native internal-port probes/forcing and deployment acceptance",
    ],
}


def canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ValueError("Activity data requires bounded finite UTF-8 JSON.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)
Key = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,79}$")]
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


class ActivityDefinition(StrictModel):
    id: Key
    name: Annotated[str, Field(strict=True, min_length=1, max_length=200)]
    program: Program


class ActivityLibrary(StrictModel):
    version: Literal[2]
    definitions: list[ActivityDefinition] = Field(max_length=64)

    @field_validator("version", mode="before")
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError("Activity library requires the explicit integer version2.")
        return value


class ActivityArchive(StrictModel):
    format: Literal["bms-macro-library/2"]
    root: Key
    library: ActivityLibrary


class ActivityProgram(StrictModel):
    program: Program


class ActivitySelection(ActivityProgram):
    selected_ids: list[Key] = Field(min_length=1, max_length=2000)
    name: Annotated[str, Field(strict=True, min_length=1, max_length=200)]


class ActivityReference(ActivityProgram):
    definition: Key


class ActivityInstance(ActivityReference):
    x: Annotated[float, Field(strict=True)] = 0.0
    y: Annotated[float, Field(strict=True)] = 0.0


class ActivityImport(ActivityProgram):
    bundle: dict


class ActivityUpdate(ActivityReference):
    replacement: Program


class MigrationApply(ActivityProgram):
    profile_sha256: Hash
    review_sha256: Hash


class BundleMigration(StrictModel):
    bundle: dict


class BundleMigrationExport(BundleMigration):
    profile_sha256: Hash
    review_sha256: Hash


def _fresh(model, value):
    def plain(item):
        if isinstance(item, BaseModel):
            return plain(item.model_dump())
        if isinstance(item, dict):
            return {key: plain(child) for key, child in item.items()}
        if isinstance(item, list):
            return [plain(child) for child in item]
        return item

    return model.model_validate(plain(value))


def _interfaces(definition):
    inputs = [node for node in definition.program.nodes if node.kind == "Input"]
    outputs = [node for node in definition.program.nodes if node.kind == "Output"]
    if len(inputs) > 32 or not 1 <= len(outputs) <= 32:
        raise ValueError("Activities require at most32Inputs and1..32Outputs.")
    return inputs, outputs


def _reference(node, definitions):
    if node.kind != "Activity" or node.value_type != "number" or node.unit != "":
        raise ValueError(
            f"Activity {node.id}: container requires the number/empty-unit sentinel, not a scalar output."
        )
    if set(node.params) != {"definition"} or type(node.params["definition"]) is not str:
        raise ValueError(f"Activity {node.id}: parameters must contain only a definition ID.")
    identifier = node.params["definition"]
    if identifier not in definitions:
        raise ValueError(f"Activity {node.id}: unknown definition {identifier!r}.")
    return definitions[identifier]


def _load(program, *, allow_empty=False):
    import copy

    raw = program.metadata.get("macros")
    if (
        raw is None
        and allow_empty
        and not any(n.kind in ("Macro", "Activity") for n in program.nodes)
    ):
        return {}
    if not isinstance(raw, dict) or type(raw.get("version")) is not int or raw.get("version") != 2:
        raise ValueError(
            "Activities require an explicit macros.version2 library; promote v1 deliberately."
        )
    from .program_source import _bounded

    try:
        _bounded(raw)
    except (AttributeError, TypeError, RecursionError) as exc:
        raise ValueError(
            "Activity library requires bounded JSON objects with string keys."
        ) from exc
    if len(canonical(raw)) > 4194304:
        raise ValueError("Activity library exceeds4MiB.")
    library = _fresh(ActivityLibrary, copy.deepcopy(raw))
    definitions = {item.id: item for item in library.definitions}
    if len(definitions) != len(library.definitions):
        raise ValueError("Activity definition identifiers must be unique.")
    if sum(len(item.program.nodes) for item in definitions.values()) > 4000:
        raise ValueError("Activity library exceeds4000definition nodes.")
    dependencies = {}
    for definition in definitions.values():
        graph = definition.program
        if "macros" in graph.metadata or "native_sedona" in graph.metadata:
            raise ValueError(
                "Activity definitions cannot hide nested libraries or native extensions."
            )
        if any(node.params.get("terminal") for node in graph.nodes):
            raise ValueError("Activity definitions cannot contain physical terminal bindings.")
        _interfaces(definition)
        if any(node.kind == "Macro" for node in graph.nodes):
            raise ValueError("V1 Macro references cannot be mixed into a v2 activity library.")
        dependencies[definition.id] = {
            _reference(node, definitions).id for node in graph.nodes if node.kind == "Activity"
        }
    depths = {}

    def visit(identifier, path=()):
        if identifier in path:
            raise ValueError("Recursive activity definitions: " + " -> ".join((*path, identifier)))
        if identifier not in depths:
            depth = 1 + max(
                (visit(child, (*path, identifier)) for child in sorted(dependencies[identifier])),
                default=0,
            )
            if depth > 8:
                raise ValueError("Activity nesting exceeds8levels.")
            depths[identifier] = depth
        return depths[identifier]

    for identifier in definitions:
        visit(identifier)
    return definitions


def _alias(role, path, identifier=None):
    parts = [role, *path] + ([] if identifier is None else [identifier])
    prefix = {"node": "an2_", "output": "ao2_", "selector": "ac2_", "edge": "ae2_"}[role]
    return prefix + hashlib.sha256(canonical(parts)).hexdigest()[:24]


def _port(node, source_port, definitions):
    from .engine import output_type

    if node.kind == "Activity":
        definition = _reference(node, definitions)
        output = next((n for n in _interfaces(definition)[1] if n.id == source_port), None)
        if output is None:
            raise ValueError(f"{node.id}: undefined named activity output {source_port!r}.")
        return output.value_type, output.unit
    if source_port != "out":
        raise ValueError(f"{node.id}: ordinary nodes have only the out source port.")
    return output_type(node), node.unit


class _Expansion:
    def __init__(self, root, definitions, *, incomplete=False):
        self.root, self.definitions, self.incomplete = root, definitions, incomplete
        self.nodes, self.edges, self.instances, self.outputs = [], [], [], []
        self.node_ids, self.edge_ids = set(), set()
        self.reserved = {node.id for node in root.nodes}

    def add_node(self, node, *, generated=False):
        if node.id in self.node_ids or (generated and node.id in self.reserved):
            raise ValueError(f"Activity expansion identifier collision: {node.id}.")
        if len(self.nodes) >= min(2000, self.root.target.max_nodes):
            raise ValueError("Activity expansion exceeds the parent target/2000node limit.")
        self.node_ids.add(node.id)
        self.nodes.append(node)

    def edge(self, source, target, port, *identity, preserved=None):
        from .models import Edge

        identifier = preserved or _alias("edge", identity)
        if identifier in self.edge_ids:
            raise ValueError(f"Activity expansion edge collision: {identifier}.")
        if len(self.edges) >= 10000:
            raise ValueError("Activity expansion exceeds10000edges.")
        self.edge_ids.add(identifier)
        self.edges.append(Edge(id=identifier, source=source, target=target, target_port=port))

    def graph(self, graph, path=(), *, supplied=None, output_aliases=None):
        from .blocks import BLOCKS
        from .models import Node

        nested = supplied is not None
        if len(path) > 8:
            raise ValueError("Activity nesting exceeds8levels.")
        lookup = {node.id: node for node in graph.nodes}
        if len(lookup) != len(graph.nodes) or len({e.id for e in graph.edges}) != len(graph.edges):
            raise ValueError("Activity graph node/edge identifiers must be unique.")
        values, ordinary, children = {}, {}, {}
        for node in graph.nodes:
            if node.kind == "Activity":
                definition = _reference(node, self.definitions)
                instance_path = (*path, node.id)
                children[node.id] = {
                    output.id: _alias("output", instance_path, output.id)
                    for output in _interfaces(definition)[1]
                }
                for output in _interfaces(definition)[1]:
                    values[node.id, output.id] = children[node.id][output.id]
            elif node.kind in BLOCKS:
                identifier = (
                    output_aliases[node.id]
                    if nested and node.kind == "Output"
                    else _alias("node", path, node.id)
                    if nested
                    else node.id
                )
                ordinary[node.id] = identifier
                values[node.id, "out"] = identifier
            else:
                raise ValueError(f"Block {node.kind!r} has no v2 activity execution semantics.")
        incoming = {}
        for edge in graph.edges:
            if edge.source not in lookup or edge.target not in lookup:
                raise ValueError("Activity graph wire references a missing node.")
            _port(lookup[edge.source], edge.source_port, self.definitions)
            target = lookup[edge.target]
            allowed = (
                {n.id for n in _interfaces(_reference(target, self.definitions))[0]}
                if target.kind == "Activity"
                else set(BLOCKS[target.kind].inputs)
            )
            if edge.target_port not in allowed:
                raise ValueError(f"{target.id}: undefined input port {edge.target_port!r}.")
            key = edge.target, edge.target_port
            if key in incoming:
                raise ValueError(f"{target.id}.{edge.target_port}: multiple input writers.")
            incoming[key] = values[edge.source, edge.source_port]
        selector = _alias("selector", path) if nested else None
        if nested:
            self.add_node(
                Node(id=selector, kind="Constant", value_type="boolean", params={"value": True}),
                generated=True,
            )
        for node in graph.nodes:
            if node.kind == "Activity":
                definition = _reference(node, self.definitions)
                inputs, outputs = _interfaces(definition)
                absent = [port.id for port in inputs if (node.id, port.id) not in incoming]
                if absent and not self.incomplete:
                    raise ValueError(
                        f"Activity {node.id}: connect required inputs {', '.join(absent)}."
                    )
                if len(self.instances) >= 256:
                    raise ValueError("Activity expansion exceeds256instances.")
                instance_path = (*path, node.id)
                self.instances.append(
                    {
                        "path": list(instance_path),
                        "definition": definition.id,
                        "source_sha256": definition.program.digest(),
                    }
                )
                for output in outputs:
                    self.outputs.append(
                        {
                            "instance_path": list(instance_path),
                            "definition": definition.id,
                            "output_id": output.id,
                            "alias_node_id": children[node.id][output.id],
                            "value_type": output.value_type,
                            "unit": output.unit,
                        }
                    )
                self.graph(
                    definition.program,
                    instance_path,
                    supplied={
                        port.id: incoming[node.id, port.id]
                        for port in inputs
                        if (node.id, port.id) in incoming
                    },
                    output_aliases=children[node.id],
                )
            else:
                identifier = ordinary[node.id]
                if nested and node.kind in ("Input", "Output"):
                    alias = node.model_copy(
                        deep=True, update={"id": identifier, "kind": "Switch", "params": {}}
                    )
                    self.add_node(alias, generated=True)
                    self.edge(selector, identifier, "select", *path, node.id, "selector")
                    if node.kind == "Input" and node.id in supplied:
                        for port in ("on", "off"):
                            self.edge(
                                supplied[node.id], identifier, port, *path, node.id, "input", port
                            )
                else:
                    self.add_node(
                        node.model_copy(deep=True, update={"id": identifier}), generated=nested
                    )
        for edge in graph.edges:
            target = lookup[edge.target]
            if target.kind == "Activity":
                continue
            ports = ("on", "off") if nested and target.kind == "Output" else (edge.target_port,)
            for port in ports:
                self.edge(
                    values[edge.source, edge.source_port],
                    ordinary[edge.target],
                    port,
                    *path,
                    edge.id,
                    port,
                    preserved=None if nested else edge.id,
                )

    def result(self, *, source_sha256=None):
        import copy

        metadata = copy.deepcopy({k: v for k, v in self.root.metadata.items() if k != "macros"})
        metadata["activity_expansion"] = {
            "version": 2,
            "profile": PROFILE["profile"],
            "profile_sha256": PROFILE_SHA,
            "source_sha256": source_sha256 or self.root.digest(),
            "instances": self.instances,
            "outputs": self.outputs,
        }
        return self.root.model_copy(
            deep=True, update={"nodes": self.nodes, "edges": self.edges, "metadata": metadata}
        )


def _validate_flat(graph, *, allow_incomplete=False):
    from .engine import validate

    diagnostics = validate(graph)
    allowed = {"unwired", "empty"} if allow_incomplete else set()
    errors = [
        row.message for row in diagnostics if row.level == "error" and row.code not in allowed
    ]
    if errors:
        raise ValueError("; ".join(errors))
    return [row.model_dump() for row in diagnostics]


def _validate_definitions(definitions):
    from .models import Target

    for definition in definitions.values():
        graph = definition.program.model_copy(deep=True)
        graph.target = Target()
        expansion = _Expansion(graph, definitions)
        expansion.graph(graph)
        _validate_flat(expansion.result())


def _expand(program, *, incomplete=False):
    # A pretyped caller may have edited schema-controlled display fields in
    # place. Validate a private executable copy, but retain the exact original
    # editable source identity used by Engine.program and portable force maps.
    source_sha256 = program.digest() if isinstance(program, Program) else None
    program = _fresh(ActivityProgram, {"program": program}).program
    source_sha256 = source_sha256 or program.digest()
    definitions = _load(program)
    _validate_definitions(definitions)
    expansion = _Expansion(program, definitions, incomplete=incomplete)
    expansion.graph(program)
    result = expansion.result(source_sha256=source_sha256)
    _validate_flat(result, allow_incomplete=incomplete)
    return result


def expand_activities(program):
    return _expand(program)


def resolve(program):
    if not isinstance(program, Program):
        program = _fresh(ActivityProgram, {"program": program}).program
    expanded = expand_activities(program)
    return {
        "format": "bms.activity-bindings/1",
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "program_id": program.id,
        "program_revision": program.revision,
        "source_sha256": program.digest(),
        "expanded_sha256": expanded.digest(),
        "outputs": expanded.metadata["activity_expansion"]["outputs"],
    }


def _library(definitions):
    return ActivityLibrary(version=2, definitions=list(definitions.values())).model_dump(
        mode="json"
    )


def _closure(definitions, identifier):
    if identifier not in definitions:
        raise ValueError(f"Unknown activity definition {identifier!r}.")
    seen, pending = set(), [identifier]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(
            node.params["definition"]
            for node in definitions[current].program.nodes
            if node.kind == "Activity"
        )
    return seen


def _descriptor(node):
    return {
        "id": node.id,
        "label": node.label or node.id,
        "value_type": node.value_type,
        "unit": node.unit,
    }


def catalog(program):
    original = program if isinstance(program, Program) else None
    program = _fresh(ActivityProgram, {"program": program}).program
    source = original or program
    definitions = _load(program)
    _validate_definitions(definitions)
    for node in program.nodes:
        if node.kind == "Activity":
            _reference(node, definitions)
        elif node.kind == "Macro":
            raise ValueError("V1 Macro containers cannot be mixed with v2 Activities.")
    rows = []
    for item in definitions.values():
        inputs, outputs = _interfaces(item)
        rows.append(
            {
                "id": item.id,
                "name": item.name,
                "definition": item.id,
                "program_sha256": item.program.digest(),
                "definition_sha256": digest(item.model_dump(mode="json")),
                "archive_sha256": digest(
                    ActivityArchive(
                        format="bms-macro-library/2",
                        root=item.id,
                        library=ActivityLibrary(
                            version=2,
                            definitions=[
                                value
                                for key, value in definitions.items()
                                if key in _closure(definitions, item.id)
                            ],
                        ),
                    ).model_dump(mode="json")
                ),
                "kind": "Activity",
                "title": item.name,
                "category": "Activities",
                "inputs": [node.id for node in inputs],
                "input_contracts": [_descriptor(node) | {"required": True} for node in inputs],
                "outputs": [_descriptor(node) for node in outputs],
                "output": "ports",
                "unit": "",
                "parameters": {"definition": item.id},
                "help": item.program.description,
                "stateful": True,
                "node_count": len(item.program.nodes),
                "edge_count": len(item.program.edges),
                "dependencies": sorted(
                    {
                        node.params["definition"]
                        for node in item.program.nodes
                        if node.kind == "Activity"
                    }
                ),
                "instances": sum(
                    node.kind == "Activity" and node.params.get("definition") == item.id
                    for graph in [program, *(d.program for d in definitions.values())]
                    for node in graph.nodes
                ),
            }
        )
    try:
        bindings, diagnostics = resolve(source), []
    except ValueError as exc:
        bindings, diagnostics = (
            None,
            [{"level": "warning", "code": "unresolved-expansion", "message": str(exc)}],
        )
    return {
        "format": "bms.activities-catalog",
        "version": 2,
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "source_sha256": source.digest(),
        "definitions": rows,
        "bindings": bindings,
        "diagnostics": diagnostics,
    }


def _available(base, used):
    base = base[:70]
    result, index = base, 1
    while result in used:
        index += 1
        result = base + "_" + str(index)
    return result


def _with_library(program, definitions):
    result = program.model_copy(deep=True)
    result.metadata["macros"] = _library(definitions)
    return result


def create(program, selected_ids, name):
    import re

    from .models import Edge, Node

    body = _fresh(
        ActivitySelection, {"program": program, "selected_ids": selected_ids, "name": name}
    )
    program, selected_ids, name = body.program, body.selected_ids, body.name.strip()
    if not name or len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Activity selection/name must be nonempty with unique node IDs.")
    definitions = _load(program, allow_empty=True)
    _validate_definitions(definitions)
    working = _with_library(program, definitions)
    _expand(working, incomplete=True)
    lookup = {node.id: node for node in program.nodes}
    selected = set(selected_ids)
    if selected - lookup.keys():
        raise ValueError("Activity selection references a missing node.")
    if any(lookup[identifier].kind in ("Input", "Output") for identifier in selected):
        raise ValueError("Keep root Input/Output interfaces outside the selection.")
    incoming = [e for e in program.edges if e.target in selected and e.source not in selected]
    outgoing = [e for e in program.edges if e.source in selected and e.target not in selected]
    boundary = sorted({(edge.source, edge.source_port) for edge in outgoing})
    input_keys = sorted({(edge.source, edge.source_port) for edge in incoming})
    if not 1 <= len(boundary) <= 32 or len(input_keys) > 32:
        raise ValueError(
            "Selection needs1..32distinct outgoing source/port signals and at most32incoming signals."
        )
    definition_id = _available(
        "activity_" + (re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "Group"), set(definitions)
    )
    instance_id = _available("use_" + definition_id, set(lookup))
    internal = [node.model_copy(deep=True) for node in program.nodes if node.id in selected]
    min_x, max_x = min(n.x for n in internal), max(n.x for n in internal)
    center_y = sum(n.y for n in internal) / len(internal)
    interfaces, outputs = {}, {}
    for index, key in enumerate(input_keys):
        source, port = key
        identifier = "in_" + hashlib.sha256(canonical(key)).hexdigest()[:20]
        if identifier in selected:
            raise ValueError("Generated activity input interface collides with selected node.")
        typ, unit = _port(lookup[source], port, definitions)
        interfaces[key] = identifier
        internal.append(
            Node(
                id=identifier,
                kind="Input",
                label=(lookup[source].label or source)[:200],
                value_type=typ,
                unit=unit,
                params={"default": False if typ == "boolean" else 0},
                x=min_x - 220,
                y=center_y + index * 90,
            )
        )
    for index, key in enumerate(boundary):
        source, port = key
        identifier = "out_" + hashlib.sha256(canonical(key)).hexdigest()[:20]
        if identifier in selected or identifier in interfaces.values():
            raise ValueError("Generated activity output interface collides with selected node.")
        typ, unit = _port(lookup[source], port, definitions)
        outputs[key] = identifier
        internal.append(
            Node(
                id=identifier,
                kind="Output",
                label=((lookup[source].label or source) + "." + port)[:200],
                value_type=typ,
                unit=unit,
                x=max_x + 220,
                y=center_y + index * 90,
            )
        )
    edges = [
        edge.model_copy(deep=True)
        for edge in program.edges
        if edge.source in selected and edge.target in selected
    ]
    edges.extend(
        edge.model_copy(
            deep=True,
            update={"source": interfaces[edge.source, edge.source_port], "source_port": "out"},
        )
        for edge in incoming
    )
    edges.extend(
        Edge(
            id="boundary_" + hashlib.sha256(canonical(key)).hexdigest()[:20],
            source=key[0],
            source_port=key[1],
            target=identifier,
        )
        for key, identifier in outputs.items()
    )
    definition = ActivityDefinition(
        id=definition_id,
        name=name,
        program=Program(
            id=definition_id,
            name=name,
            scan_seconds=program.scan_seconds,
            nodes=internal,
            edges=edges,
            metadata={
                "extracted_from": {
                    "program": program.id,
                    "revision": program.revision,
                    "nodes": sorted(selected),
                }
            },
        ),
    )
    definitions[definition_id] = definition
    nodes = [node.model_copy(deep=True) for node in program.nodes if node.id not in selected]
    nodes.append(
        Node(
            id=instance_id,
            kind="Activity",
            label=name,
            x=min_x,
            y=center_y,
            params={"definition": definition_id},
            value_type="number",
            unit="",
        )
    )
    root_edges = [
        edge.model_copy(deep=True)
        for edge in program.edges
        if edge.source not in selected and edge.target not in selected
    ]
    for key, identifier in interfaces.items():
        edge = next(e for e in incoming if (e.source, e.source_port) == key)
        root_edges.append(
            edge.model_copy(deep=True, update={"target": instance_id, "target_port": identifier})
        )
    root_edges.extend(
        edge.model_copy(
            deep=True,
            update={"source": instance_id, "source_port": outputs[edge.source, edge.source_port]},
        )
        for edge in outgoing
    )
    result = _with_library(program, definitions)
    result.nodes, result.edges = nodes, root_edges
    _expand(result, incomplete=True)
    return result


def instantiate(program, definition, x=0, y=0):
    request = _fresh(
        ActivityInstance, {"program": program, "definition": definition, "x": x, "y": y}
    )
    definitions = _load(request.program)
    _validate_definitions(definitions)
    if definition not in definitions:
        raise ValueError(f"Unknown activity definition {definition!r}.")
    if len(request.program.nodes) >= 2000:
        raise ValueError("Activity placement exceeds the parent node limit.")
    from .models import Node

    result = request.program.model_copy(deep=True)
    result.nodes.append(
        Node(
            id=_available("use_" + definition, {n.id for n in result.nodes}),
            kind="Activity",
            label=definitions[definition].name,
            params={"definition": definition},
            value_type="number",
            unit="",
            x=request.x,
            y=request.y,
        )
    )
    return result


def inspect(program, definition):
    request = _fresh(ActivityReference, {"program": program, "definition": definition})
    program, definition = request.program, request.definition
    definitions = _load(program)
    _validate_definitions(definitions)
    included = _closure(definitions, definition)
    result = definitions[definition].program.model_copy(deep=True)
    result.name = definitions[definition].name
    result.scan_seconds = program.scan_seconds
    result.target = program.target.model_copy(deep=True)
    result.metadata["macros"] = _library(
        {key: item for key, item in definitions.items() if key in included}
    )
    return result


def update(program, definition, replacement):
    body = _fresh(
        ActivityUpdate, {"program": program, "definition": definition, "replacement": replacement}
    )
    program, replacement = body.program, body.replacement
    definitions = _load(program)
    _validate_definitions(definitions)
    expected = inspect(program, definition)
    if canonical(replacement.metadata.get("macros")) != canonical(expected.metadata["macros"]):
        raise ValueError(
            "Activity edit dependency context changed or is stale; reopen the definition."
        )
    if "native_sedona" in replacement.metadata:
        raise ValueError("Native extensions cannot be hidden inside activities.")
    if replacement.scan_seconds != program.scan_seconds or replacement.target != program.target:
        raise ValueError("Activity edits inherit the exact parent clock and target.")
    previous = definitions[definition]
    graph = replacement.model_copy(deep=True)
    graph.metadata.pop("macros")
    graph.id, graph.revision, graph.scan_seconds, graph.target = (
        previous.program.id,
        previous.program.revision,
        previous.program.scan_seconds,
        previous.program.target.model_copy(deep=True),
    )
    updated = ActivityDefinition(id=definition, name=replacement.name, program=graph)
    used = any(
        node.kind == "Activity" and node.params.get("definition") == definition
        for owner in [
            program,
            *(item.program for key, item in definitions.items() if key != definition),
        ]
        for node in owner.nodes
    )
    if used:
        old_inputs, old_outputs = _interfaces(previous)
        new_inputs, new_outputs = _interfaces(updated)

        def contract(rows):
            return {n.id: (n.value_type, n.unit) for n in rows}

        if contract(old_inputs) != contract(new_inputs) or contract(old_outputs) != contract(
            new_outputs
        ):
            raise ValueError(
                "Activity input/output IDs, types and units must stay unchanged while instances exist."
            )
    definitions[definition] = updated
    result = _with_library(program, definitions)
    _expand(result, incomplete=True)
    return result


def delete(program, definition):
    request = _fresh(ActivityReference, {"program": program, "definition": definition})
    program, definition = request.program, request.definition
    definitions = _load(program)
    _validate_definitions(definitions)
    if definition not in definitions:
        raise ValueError(f"Unknown activity definition {definition!r}.")
    for owner in [program, *(item.program for item in definitions.values())]:
        if any(
            node.kind == "Activity" and node.params.get("definition") == definition
            for node in owner.nodes
        ):
            raise ValueError(f"Activity definition {definition!r} is still referenced.")
    return _with_library(
        program, {key: item for key, item in definitions.items() if key != definition}
    )


def export_bundle(program, definition):
    request = _fresh(ActivityReference, {"program": program, "definition": definition})
    program, definition = request.program, request.definition
    definitions = _load(program)
    _validate_definitions(definitions)
    included = _closure(definitions, definition)
    return ActivityArchive(
        format="bms-macro-library/2",
        root=definition,
        library=ActivityLibrary(
            version=2, definitions=[item for key, item in definitions.items() if key in included]
        ),
    ).model_dump(mode="json")


def import_bundle(program, bundle):
    from .models import canonical as program_canonical

    body = _fresh(ActivityImport, {"program": program, "bundle": bundle})
    program, bundle = body.program, body.bundle
    archive = _fresh(ActivityArchive, bundle)
    incoming = _load(Program(metadata={"macros": archive.library.model_dump(mode="json")}))
    _validate_definitions(incoming)
    if _closure(incoming, archive.root) != set(incoming):
        raise ValueError(
            "Activity archive includes definitions outside its root dependency closure."
        )
    definitions = _load(program, allow_empty=True)
    _validate_definitions(definitions)
    for identifier, item in incoming.items():
        if identifier in definitions and (
            definitions[identifier].name != item.name
            or program_canonical(definitions[identifier].program) != program_canonical(item.program)
        ):
            raise ValueError(
                f"Activity definition identifier conflict: {identifier}; original sources retained."
            )
        definitions[identifier] = item
    result = _with_library(program, definitions)
    _load(result)
    _validate_definitions(definitions)
    return result


def _migration_graph(graph, definitions, rewrites, owner=None):
    from .macros import _reference as legacy_reference

    result = graph.model_copy(deep=True)
    lookup = {node.id: node for node in graph.nodes}
    for node in result.nodes:
        if node.kind == "Activity":
            raise ValueError("V1 promotion cannot contain unresolved Activity nodes.")
        if node.kind != "Macro":
            continue
        legacy_reference(node, definitions)
        rewrites.append(
            {
                "scope": "root" if owner is None else "definition",
                "definition": owner,
                "kind": "container",
                "node": node.id,
                "from": {"kind": "Macro", "value_type": node.value_type, "unit": node.unit},
                "to": {"kind": "Activity", "value_type": "number", "unit": ""},
            }
        )
        node.kind, node.value_type, node.unit = "Activity", "number", ""
    for edge in result.edges:
        source = lookup.get(edge.source)
        if source is None:
            raise ValueError("Migration source wire references a missing node.")
        if edge.source_port != "out":
            raise ValueError("V1 source wires must use the out source port.")
        if source.kind != "Macro":
            continue
        definition = legacy_reference(source, definitions)
        output = next(node for node in definition.program.nodes if node.kind == "Output")
        rewrites.append(
            {
                "scope": "root" if owner is None else "definition",
                "definition": owner,
                "kind": "source-port",
                "edge": edge.id,
                "source": edge.source,
                "from": "out",
                "to": output.id,
            }
        )
        edge.source_port = output.id
    return result


def migration_preview(program):
    from .engine import validate
    from .macros import _load_library
    from .macros import _validate_definitions as validate_v1

    program = _fresh(ActivityProgram, {"program": program}).program
    if (
        isinstance(program.metadata.get("macros"), dict)
        and type(program.metadata["macros"].get("version")) is int
        and program.metadata["macros"]["version"] == 2
    ):
        raise ValueError("Source already has an activity version2 library.")
    definitions = _load_library(program)
    validate_v1(definitions)
    rewrites, promoted = [], {}
    for identifier, item in definitions.items():
        promoted[identifier] = ActivityDefinition(
            id=identifier,
            name=item.name,
            program=_migration_graph(item.program, definitions, rewrites, identifier),
        )
    result = _migration_graph(program, definitions, rewrites)
    result.metadata["macros"] = _library(promoted)
    # Mechanical promotion preserves unwired drafts, without inventing source wires.
    expanded = _expand(result, incomplete=True)
    report = {
        "format": "bms.activity-migration-preview",
        "version": 1,
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "source_sha256": program.digest(),
        "program": result.model_dump(mode="json"),
        "program_sha256": result.digest(),
        "rewrites": rewrites,
        "rewrites_sha256": digest(rewrites),
        "can_apply": True,
        "before_diagnostics": [row.model_dump() for row in validate(program)],
        "after_diagnostics": _validate_flat(expanded, allow_incomplete=True),
    }
    report["review_sha256"] = digest(
        {
            key: report[key]
            for key in [
                "format",
                "version",
                "profile_sha256",
                "source_sha256",
                "program_sha256",
                "rewrites_sha256",
            ]
        }
    )
    return report


def migration_apply(request):
    request = _fresh(MigrationApply, request)
    report = migration_preview(request.program)
    if request.profile_sha256 != PROFILE_SHA or request.review_sha256 != report["review_sha256"]:
        raise ValueError("Activity migration source/profile/review changed; preview again.")
    return Program.model_validate(report["program"])


def bundle_migration_preview(bundle):
    from .macros import MacroArchive, _load_library
    from .macros import _closure as legacy_closure
    from .macros import _validate_definitions as validate_v1

    request = _fresh(BundleMigration, {"bundle": bundle})
    archive = _fresh(MacroArchive, request.bundle)
    program = Program(metadata={"macros": archive.library.model_dump(mode="json")})
    definitions = _load_library(program)
    validate_v1(definitions)
    if legacy_closure(definitions, archive.root) != set(definitions):
        raise ValueError("V1 bundle includes definitions outside its root dependency closure.")
    rewrites, promoted = [], {}
    for identifier, item in definitions.items():
        promoted[identifier] = ActivityDefinition(
            id=identifier,
            name=item.name,
            program=_migration_graph(item.program, definitions, rewrites, identifier),
        )
    converted = ActivityArchive(
        format="bms-macro-library/2",
        root=archive.root,
        library=ActivityLibrary(version=2, definitions=list(promoted.values())),
    ).model_dump(mode="json")
    _validate_definitions(_load(Program(metadata={"macros": converted["library"]})))
    report = {
        "format": "bms.activity-bundle-migration-preview",
        "version": 1,
        "profile": copy.deepcopy(PROFILE),
        "profile_sha256": PROFILE_SHA,
        "source_bundle_sha256": digest(request.bundle),
        "bundle": converted,
        "bundle_sha256": digest(converted),
        "rewrites": rewrites,
        "rewrites_sha256": digest(rewrites),
        "can_apply": True,
    }
    report["review_sha256"] = digest(
        {
            key: report[key]
            for key in [
                "format",
                "version",
                "profile_sha256",
                "source_bundle_sha256",
                "bundle_sha256",
                "rewrites_sha256",
            ]
        }
    )
    return report


def bundle_migration_export(request):
    request = _fresh(BundleMigrationExport, request)
    report = bundle_migration_preview(request.bundle)
    if request.profile_sha256 != PROFILE_SHA or request.review_sha256 != report["review_sha256"]:
        raise ValueError("Activity bundle migration source/profile/review changed; preview again.")
    return report["bundle"]


def activity_router():
    import copy

    from fastapi import APIRouter, Response

    router = APIRouter(prefix="/api/activities")

    @router.get("/profile")
    def profile_route():
        return {
            "format": "bms.activities-profile",
            "version": 2,
            "profile": copy.deepcopy(PROFILE),
            "profile_sha256": PROFILE_SHA,
            "schemas": {
                model.__name__: model.model_json_schema()
                for model in [
                    ActivityProgram,
                    ActivitySelection,
                    ActivityReference,
                    ActivityInstance,
                    ActivityImport,
                    ActivityUpdate,
                    MigrationApply,
                    BundleMigration,
                    BundleMigrationExport,
                ]
            },
        }

    @router.post("/catalog")
    def catalog_route(body: ActivityProgram):
        return catalog(body.program)

    @router.post("/resolve")
    def resolve_route(body: ActivityProgram):
        return resolve(body.program)

    @router.post("/create")
    def create_route(body: ActivitySelection, source_transport: SourceMode = False):
        return source_response(create(body.program, body.selected_ids, body.name), source_transport)

    @router.post("/instantiate")
    def instantiate_route(body: ActivityInstance, source_transport: SourceMode = False):
        return source_response(
            instantiate(body.program, body.definition, body.x, body.y), source_transport
        )

    @router.post("/definition")
    def inspect_route(body: ActivityReference, source_transport: SourceMode = False):
        return source_response(inspect(body.program, body.definition), source_transport)

    @router.post("/update")
    def update_route(body: ActivityUpdate, source_transport: SourceMode = False):
        return source_response(
            update(body.program, body.definition, body.replacement), source_transport
        )

    @router.post("/delete")
    def delete_route(body: ActivityReference, source_transport: SourceMode = False):
        return source_response(delete(body.program, body.definition), source_transport)

    @router.post("/import")
    def import_route(body: ActivityImport, source_transport: SourceMode = False):
        return source_response(import_bundle(body.program, body.bundle), source_transport)

    def original_archive(value):
        raw = canonical(value)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
                "Content-Disposition": f'attachment; filename="{value["root"]}.bms-activity.json"',
            },
        )

    @router.post("/export")
    def export_route(body: ActivityReference):
        return original_archive(export_bundle(body.program, body.definition))

    @router.post("/migration/preview")
    def migration_preview_route(body: ActivityProgram, source_transport: SourceMode = False):
        return source_response(migration_preview(body.program), source_transport)

    @router.post("/migration/apply")
    def migration_apply_route(body: MigrationApply, source_transport: SourceMode = False):
        return source_response(migration_apply(body), source_transport)

    @router.post("/migration/bundle-preview")
    def bundle_preview_route(body: BundleMigration, source_transport: SourceMode = False):
        return source_response(bundle_migration_preview(body.bundle), source_transport)

    @router.post("/migration/bundle-export")
    def bundle_export_route(body: BundleMigrationExport):
        return original_archive(bundle_migration_export(body))

    return router
