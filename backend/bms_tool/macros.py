"""Bounded hierarchical graph macros lowered to ordinary typed blocks.

The editable source stores a versioned library in ``metadata.macros``. A Macro
node names one definition and exposes its Input identifiers as required ports.
Definitions have one Output; its type and unit are the instance's output
contract. Each instance gets independent state. All blocks use the parent scan
period and target. Library definitions never bind physical terminals.

Expansion retains root I/O and instance identifiers, replaces interface nodes
with zero-delay Switch aliases, and scopes all other identifiers by instance
path. Internal outputs never become published outputs. Lowering adds no memory
boundaries and cannot hide a combinational cycle. Expansion provenance describes
the source; the original JSON is required to recover editable hierarchy.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Literal

from pydantic import Field

from .blocks import BLOCKS
from .models import Edge, Node, Program, StrictModel, Target

_MAX_DEFINITIONS = 64
_MAX_DEFINITION_NODES = 4000
_MAX_DEPTH = 8
_MAX_INSTANCES = 256
_MAX_NODES = 2000
_MAX_EDGES = 10000
_MAX_INPUTS = 32
_MAX_LIBRARY_BYTES = 4 * 1024 * 1024


class MacroDefinition(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,79}$")
    name: str = Field(min_length=1, max_length=200)
    program: Program


class MacroLibrary(StrictModel):
    version: Literal[1]
    definitions: list[MacroDefinition] = Field(max_length=_MAX_DEFINITIONS)


class MacroArchive(StrictModel):
    format: Literal["bms-macro-library/1"]
    root: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,79}$")
    library: MacroLibrary


def _type(node: Node) -> str:
    spec = BLOCKS.get(node.kind)
    if spec is None or spec.output == "same" or node.kind in ("Input", "Constant"):
        return node.value_type
    return spec.output


def _interfaces(definition: MacroDefinition) -> tuple[list[Node], Node]:
    inputs = [node for node in definition.program.nodes if node.kind == "Input"]
    outputs = [node for node in definition.program.nodes if node.kind == "Output"]
    if len(inputs) > _MAX_INPUTS:
        raise ValueError(f"Macro {definition.id}: at most {_MAX_INPUTS} inputs are supported")
    if len(outputs) != 1:
        raise ValueError(f"Macro {definition.id}: exactly one Output is required")
    return inputs, outputs[0]


def _reference(node: Node, definitions: dict[str, MacroDefinition]) -> MacroDefinition:
    if set(node.params) != {"definition"} or not isinstance(node.params["definition"], str):
        raise ValueError(f"Macro {node.id}: parameters must contain only a definition identifier")
    identifier = node.params["definition"]
    if identifier not in definitions:
        raise ValueError(f"Macro {node.id}: unknown definition {identifier!r}")
    definition = definitions[identifier]
    _, output = _interfaces(definition)
    if node.value_type != output.value_type or node.unit != output.unit:
        raise ValueError(
            f"Macro {node.id}: output must be {output.value_type} with unit {output.unit!r}"
        )
    return definition


def _load_library(program: Program) -> dict[str, MacroDefinition]:
    if "macros" not in program.metadata:
        if any(node.kind == "Macro" for node in program.nodes):
            raise ValueError("Macro nodes require metadata.macros version 1")
        return {}
    raw = program.metadata["macros"]
    try:
        size = len(json.dumps(raw, allow_nan=False).encode())
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Macro library must contain finite JSON data") from exc
    if size > _MAX_LIBRARY_BYTES:
        raise ValueError("Macro library exceeds 4 MiB")
    library = MacroLibrary.model_validate(raw)
    definitions = {definition.id: definition for definition in library.definitions}
    if len(definitions) != len(library.definitions):
        raise ValueError("Macro definition identifiers must be unique")
    if sum(len(item.program.nodes) for item in definitions.values()) > _MAX_DEFINITION_NODES:
        raise ValueError(f"Macro library exceeds {_MAX_DEFINITION_NODES} definition nodes")
    dependencies: dict[str, set[str]] = {}
    for definition in definitions.values():
        graph = definition.program
        if "macros" in graph.metadata or "native_sedona" in graph.metadata:
            raise ValueError(
                f"Macro {definition.id}: nested libraries and native extensions are forbidden"
            )
        _interfaces(definition)
        if any(node.params.get("terminal") for node in graph.nodes):
            raise ValueError(f"Macro {definition.id}: physical terminal bindings are forbidden")
        dependencies[definition.id] = {
            _reference(node, definitions).id for node in graph.nodes if node.kind == "Macro"
        }

    depths: dict[str, int] = {}

    def visit(identifier: str, path: tuple[str, ...]) -> int:
        if identifier in path:
            raise ValueError("Recursive macro definitions: " + " -> ".join((*path, identifier)))
        if identifier in depths:
            return depths[identifier]
        height = 1 + max(
            (visit(child, (*path, identifier)) for child in sorted(dependencies[identifier])),
            default=0,
        )
        if height > _MAX_DEPTH:
            raise ValueError(f"Macro nesting exceeds {_MAX_DEPTH} levels")
        depths[identifier] = height
        return height

    for identifier in sorted(definitions):
        visit(identifier, ())
    return definitions


def _hash(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()[:24]


class _Expansion:
    def __init__(self, definitions: dict[str, MacroDefinition], root: Program):
        self.definitions = definitions
        self.root = root
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []
        self.node_ids: set[str] = set()
        self.edge_ids: set[str] = set()
        self.reserved = {node.id for node in root.nodes}
        self.instances: list[dict] = []

    def _add_node(self, node: Node, *, generated=False):
        if node.id in self.node_ids or (generated and node.id in self.reserved):
            raise ValueError(f"Macro expansion identifier collision: {node.id}")
        if len(self.nodes) >= min(_MAX_NODES, self.root.target.max_nodes):
            raise ValueError("Macro expansion exceeds the parent target node limit")
        self.node_ids.add(node.id)
        self.nodes.append(node)

    def _edge(self, source, target, port, *identity, preserved_id=None):
        identifier = preserved_id or "me_" + _hash(*identity)
        if identifier in self.edge_ids:
            raise ValueError(f"Macro expansion edge identifier collision: {identifier}")
        if len(self.edges) >= _MAX_EDGES:
            raise ValueError(f"Macro expansion exceeds {_MAX_EDGES} edges")
        self.edge_ids.add(identifier)
        self.edges.append(Edge(id=identifier, source=source, target=target, target_port=port))

    def _alias(
        self, node: Node, identifier: str, source: str, selector: str, path: tuple[str, ...]
    ):
        alias = node.model_copy(
            deep=True, update={"id": identifier, "kind": "Switch", "params": {}}
        )
        self._add_node(alias, generated=identifier not in self.reserved)
        for port in ("on", "off"):
            self._edge(source, identifier, port, *path, node.id, "interface", port)
        self._edge(selector, identifier, "select", *path, node.id, "interface", "select")

    def graph(self, graph: Program, path=(), *, wrapper: Node | None = None, supplied=None):
        nested = wrapper is not None
        if len(path) > _MAX_DEPTH:
            raise ValueError(f"Macro nesting exceeds {_MAX_DEPTH} levels")
        lookup = {node.id: node for node in graph.nodes}
        if len(lookup) != len(graph.nodes):
            raise ValueError("Macro graph node identifiers must be unique")
        if len({edge.id for edge in graph.edges}) != len(graph.edges):
            raise ValueError("Macro graph edge identifiers must be unique")
        for node in graph.nodes:
            if node.kind not in BLOCKS and node.kind != "Macro":
                raise ValueError(f"Block {node.kind!r} has no execution semantics")
        output = next((node for node in graph.nodes if node.kind == "Output"), None)
        mapped = {
            node.id: (
                wrapper.id
                if nested and node is output
                else "mn_" + _hash(*path, node.id)
                if nested
                else node.id
            )
            for node in graph.nodes
        }
        incoming: dict[tuple[str, str], str] = {}
        for edge in graph.edges:
            if edge.source not in lookup or edge.target not in lookup:
                raise ValueError("Macro graph connection references a missing node")
            if edge.source_port != "out":
                raise ValueError("Macro graph connection uses an undefined source port")
            target = lookup[edge.target]
            allowed = (
                {node.id for node in _interfaces(_reference(target, self.definitions))[0]}
                if target.kind == "Macro"
                else set(BLOCKS[target.kind].inputs)
            )
            if edge.target_port not in allowed:
                raise ValueError(f"{target.id}: undefined input port {edge.target_port!r}")
            key = (edge.target, edge.target_port)
            if key in incoming:
                raise ValueError(
                    f"{target.id}.{edge.target_port}: an input port can have only one writer"
                )
            incoming[key] = mapped[edge.source]
        selector = "mc_" + _hash(*path, "selector") if nested else ""
        if nested:
            self._add_node(
                Node(id=selector, kind="Constant", value_type="boolean", params={"value": True}),
                generated=True,
            )
        for node in graph.nodes:
            identifier = mapped[node.id]
            if node.kind == "Macro":
                definition = _reference(node, self.definitions)
                ports, _ = _interfaces(definition)
                absent = [port.id for port in ports if (node.id, port.id) not in incoming]
                if absent:
                    raise ValueError(
                        f"Macro {node.id}: connect required inputs {', '.join(absent)}"
                    )
                if len(self.instances) >= _MAX_INSTANCES:
                    raise ValueError(f"Macro expansion exceeds {_MAX_INSTANCES} instances")
                instance_path = (*path, node.id)
                self.instances.append(
                    {
                        "path": list(instance_path),
                        "definition": definition.id,
                        "node": identifier,
                        "source_sha256": definition.program.digest(),
                    }
                )
                instance = node.model_copy(deep=True, update={"id": identifier})
                self.graph(
                    definition.program,
                    instance_path,
                    wrapper=instance,
                    supplied={port.id: incoming[node.id, port.id] for port in ports},
                )
            elif nested and node.kind == "Input":
                self._alias(node, identifier, supplied[node.id], selector, path)
            elif nested and node.kind == "Output":
                alias = wrapper.model_copy(deep=True, update={"kind": "Switch", "params": {}})
                self._add_node(alias, generated=identifier not in self.reserved)
                self._edge(selector, identifier, "select", *path, node.id, "output", "select")
            else:
                self._add_node(
                    node.model_copy(deep=True, update={"id": identifier}), generated=nested
                )
        for edge in graph.edges:
            target = lookup[edge.target]
            if target.kind == "Macro":
                continue
            source_id, target_id = mapped[edge.source], mapped[edge.target]
            ports = ("on", "off") if nested and target.kind == "Output" else (edge.target_port,)
            for port in ports:
                self._edge(
                    source_id,
                    target_id,
                    port,
                    *path,
                    edge.id,
                    port,
                    preserved_id=edge.id if not nested else None,
                )

    def result(self, *, provenance=True) -> Program:
        metadata = {key: value for key, value in self.root.metadata.items() if key != "macros"}
        if provenance:
            metadata["macro_expansion"] = {
                "version": 1,
                "source_sha256": self.root.digest(),
                "instances": self.instances,
                "definitions": [
                    {"id": item.id, "sha256": item.program.digest()}
                    for item in self.definitions.values()
                ],
                "scan_seconds": self.root.scan_seconds,
            }
        return self.root.model_copy(
            deep=True, update={"nodes": self.nodes, "edges": self.edges, "metadata": metadata}
        )


def _validate_flat(program: Program, context=""):
    # Local import avoids a module cycle when core validation calls expansion.
    from .engine import validate

    errors = [item.message for item in validate(program) if item.level == "error"]
    if errors:
        raise ValueError((context + ": " if context else "") + "; ".join(errors))


def _validate_definitions(definitions: dict[str, MacroDefinition]):
    for definition in definitions.values():
        graph = definition.program.model_copy(deep=True)
        # Definitions inherit the caller's target and scan. Validate their
        # portable structure without applying an unrelated saved target limit.
        graph.target = Target()
        expansion = _Expansion(definitions, graph)
        expansion.graph(graph)
        _validate_flat(expansion.result(provenance=False), f"Macro {definition.id}")


def expand_macros(program: Program) -> Program:
    """Return an executable flat copy, rejecting incomplete or ambiguous macros."""
    if "macros" not in program.metadata and not any(node.kind == "Macro" for node in program.nodes):
        return program.model_copy(deep=True)
    definitions = _load_library(program)
    _validate_definitions(definitions)
    expansion = _Expansion(definitions, program)
    expansion.graph(program)
    result = expansion.result()
    _validate_flat(result)
    return result


def macro_catalog(program: Program) -> list[dict]:
    """Return validated definitions and typed interfaces for a graphical editor."""
    definitions = _load_library(program)
    _validate_definitions(definitions)
    result = []
    for definition in definitions.values():
        inputs, output = _interfaces(definition)
        result.append(
            {
                "id": definition.id,
                "name": definition.name,
                "definition": definition.id,
                "kind": "Macro",
                "title": definition.name,
                "category": "Macros",
                "inputs": [node.id for node in inputs],
                "input_contracts": [
                    {
                        "id": node.id,
                        "label": node.label or node.id,
                        "value_type": node.value_type,
                        "unit": node.unit,
                        "required": True,
                    }
                    for node in inputs
                ],
                "output": output.value_type,
                "unit": output.unit,
                "parameters": {"definition": definition.id},
                "help": definition.program.description,
                "nodes": len(definition.program.nodes),
                "node_count": len(definition.program.nodes),
                "edge_count": len(definition.program.edges),
                "dependencies": sorted(
                    {
                        node.params["definition"]
                        for node in definition.program.nodes
                        if node.kind == "Macro"
                    }
                ),
                "root_instances": sum(
                    node.kind == "Macro" and node.params.get("definition") == definition.id
                    for node in program.nodes
                ),
                "instances": sum(
                    node.kind == "Macro" and node.params.get("definition") == definition.id
                    for graph in (program, *(item.program for item in definitions.values()))
                    for node in graph.nodes
                ),
                "scan": "inherits parent scan period",
            }
        )
    return result


def _available(identifier: str, existing: set[str]) -> str:
    identifier = identifier[:70]
    candidate = identifier
    suffix = 1
    while candidate in existing:
        suffix += 1
        candidate = identifier[:70] + "_" + str(suffix)
    return candidate


def create_definition(program: Program, selected_ids: list[str], name: str) -> Program:
    """Extract one-output internal selection into a reusable definition/instance.

    Root Input and Output nodes remain in place. A selection must have exactly
    one distinct node feeding its outside consumers; fanout is preserved. Every
    distinct incoming source becomes one typed required input. Multi-output
    selections are rejected explicitly rather than dropping their connections.
    The returned source retains the full editable library and is not flattened.
    """
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 200:
        raise ValueError("Macro name must contain 1..200 characters")
    if (
        not isinstance(selected_ids, list)
        or not selected_ids
        or any(not isinstance(item, str) for item in selected_ids)
    ):
        raise ValueError("Select at least one internal node")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValueError("Selected node identifiers must be unique")
    definitions = _load_library(program)
    _validate_flat(expand_macros(program))
    lookup = {node.id: node for node in program.nodes}
    selected = set(selected_ids)
    if selected - lookup.keys():
        raise ValueError("Selection references an unknown node")
    if any(lookup[identifier].kind in ("Input", "Output") for identifier in selected):
        raise ValueError("Keep root Input and Output nodes outside a macro selection")
    incoming = [
        edge for edge in program.edges if edge.target in selected and edge.source not in selected
    ]
    outgoing = [
        edge for edge in program.edges if edge.source in selected and edge.target not in selected
    ]
    output_sources = {edge.source for edge in outgoing}
    if len(output_sources) != 1:
        raise ValueError("Macro selection must have exactly one distinct outgoing result")
    if len(definitions) >= _MAX_DEFINITIONS:
        raise ValueError(f"Macro library already contains {_MAX_DEFINITIONS} definitions")
    result_source = lookup[next(iter(output_sources))]
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", name.strip()).strip("_")[:48] or "selection"
    definition_id = _available("macro_" + slug, set(definitions))
    instance_id = _available("use_" + definition_id, set(lookup))
    internal = [node.model_copy(deep=True) for node in program.nodes if node.id in selected]
    min_x = min(node.x for node in internal)
    max_x = max(node.x for node in internal)
    center_y = sum(node.y for node in internal) / len(internal)
    sources: dict[str, list[Edge]] = defaultdict(list)
    for edge in incoming:
        sources[edge.source].append(edge)
    if len(sources) > _MAX_INPUTS:
        raise ValueError(f"Macro selection requires more than {_MAX_INPUTS} inputs")
    interfaces: dict[str, str] = {}
    for index, source_id in enumerate(sorted(sources)):
        source = lookup[source_id]
        interface_id = "in_" + _hash(source_id)
        interfaces[source_id] = interface_id
        internal.append(
            Node(
                id=interface_id,
                kind="Input",
                label=source.label or source.id,
                x=min_x - 220,
                y=center_y + 110 * index,
                value_type=_type(source),
                unit=source.unit,
                params={"default": False if _type(source) == "boolean" else 0},
            ),
        )
    output_id = "out_" + _hash(result_source.id)
    internal.append(
        Node(
            id=output_id,
            kind="Output",
            label="Result",
            x=max_x + 220,
            y=center_y,
            value_type=_type(result_source),
            unit=result_source.unit,
        ),
    )
    internal_edges = [
        edge.model_copy(deep=True)
        for edge in program.edges
        if edge.source in selected and edge.target in selected
    ]
    for edge in incoming:
        internal_edges.append(
            edge.model_copy(deep=True, update={"source": interfaces[edge.source]})
        )
    internal_edges.append(
        Edge(id="result_" + _hash(result_source.id), source=result_source.id, target=output_id)
    )
    graph = Program(
        id=definition_id,
        name=name.strip(),
        scan_seconds=program.scan_seconds,
        nodes=internal,
        edges=internal_edges,
        metadata={
            "extracted_from": {
                "program": program.id,
                "revision": program.revision,
                "nodes": sorted(selected),
            }
        },
    )
    definition = MacroDefinition(id=definition_id, name=name.strip(), program=graph)
    nodes = [node.model_copy(deep=True) for node in program.nodes if node.id not in selected]
    nodes.append(
        Node(
            id=instance_id,
            kind="Macro",
            label=name.strip(),
            x=min_x,
            y=center_y,
            params={"definition": definition_id},
            unit=result_source.unit,
            value_type=_type(result_source),
        )
    )
    edges = [
        edge.model_copy(deep=True)
        for edge in program.edges
        if edge.source not in selected and edge.target not in selected
    ]
    for source_id in sorted(sources):
        edges.append(
            sources[source_id][0].model_copy(
                deep=True, update={"target": instance_id, "target_port": interfaces[source_id]}
            )
        )
    edges.extend(edge.model_copy(deep=True, update={"source": instance_id}) for edge in outgoing)
    library = MacroLibrary(version=1, definitions=[*definitions.values(), definition])
    result = program.model_copy(deep=True, update={"nodes": nodes, "edges": edges})
    result.metadata["macros"] = library.model_dump(mode="json")
    expand_macros(result)
    return result


def instantiate_macro(program: Program, definition: str, x=0, y=0) -> Program:
    """Add an unwired typed instance, ready for normal graphical wiring."""
    definitions = _load_library(program)
    _validate_definitions(definitions)
    if definition not in definitions:
        raise ValueError(f"Unknown macro definition {definition!r}")
    for coordinate in (x, y):
        try:
            finite = type(coordinate) in (int, float) and math.isfinite(coordinate)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Macro coordinates must be finite numbers")
    if len(program.nodes) >= _MAX_NODES:
        raise ValueError("Program node capacity exceeded")
    item = definitions[definition]
    _, output = _interfaces(item)
    identifier = _available("use_" + definition, {node.id for node in program.nodes})
    result = program.model_copy(deep=True)
    result.nodes.append(
        Node(
            id=identifier,
            kind="Macro",
            label=item.name,
            params={"definition": definition},
            x=x,
            y=y,
            value_type=output.value_type,
            unit=output.unit,
        )
    )
    return result


def _closure(definitions: dict[str, MacroDefinition], identifier: str) -> set[str]:
    if identifier not in definitions:
        raise ValueError(f"Unknown macro definition {identifier!r}")
    included: set[str] = set()
    pending = [identifier]
    while pending:
        current = pending.pop()
        if current in included:
            continue
        included.add(current)
        pending.extend(
            node.params["definition"]
            for node in definitions[current].program.nodes
            if node.kind == "Macro"
        )
    return included


def export_macro_library(program: Program, definition: str) -> dict:
    """Export a finite JSON definition bundle with its complete dependency closure."""
    definitions = _load_library(program)
    _validate_definitions(definitions)
    included = _closure(definitions, definition)
    archive = MacroArchive(
        format="bms-macro-library/1",
        root=definition,
        library=MacroLibrary(
            version=1, definitions=[item for key, item in definitions.items() if key in included]
        ),
    )
    return archive.model_dump(mode="json")


def import_macro_library(program: Program, bundle: dict) -> Program:
    """Merge a validated portable bundle; conflicting identifiers never overwrite."""
    archive = MacroArchive.model_validate(bundle)
    imported_program = Program(metadata={"macros": archive.library.model_dump(mode="json")})
    imported = _load_library(imported_program)
    _validate_definitions(imported)
    if _closure(imported, archive.root) != set(imported):
        raise ValueError("Macro bundle includes definitions outside its root dependency closure")
    definitions = _load_library(program)
    _validate_definitions(definitions)
    for identifier, item in imported.items():
        if identifier in definitions and definitions[identifier] != item:
            raise ValueError(
                f"Macro definition identifier conflict: {identifier}; existing definitions were retained"
            )
        definitions[identifier] = item
    result = program.model_copy(deep=True)
    result.metadata["macros"] = MacroLibrary(
        version=1, definitions=list(definitions.values())
    ).model_dump(mode="json")
    # Recheck combined size and node limits after merging independently valid bundles.
    _validate_definitions(_load_library(result))
    return result


def delete_macro_definition(program: Program, definition: str) -> Program:
    """Remove an unused definition after checking root and nested references."""
    definitions = _load_library(program)
    _validate_definitions(definitions)
    if definition not in definitions:
        raise ValueError(f"Unknown macro definition {definition!r}")
    for owner, graph in [
        ("root program", program),
        *((item.id, item.program) for item in definitions.values()),
    ]:
        for node in graph.nodes:
            if node.kind == "Macro" and node.params.get("definition") == definition:
                raise ValueError(f"Macro definition {definition!r} is in use by {owner}:{node.id}")
    result = program.model_copy(deep=True)
    result.metadata["macros"] = MacroLibrary(
        version=1, definitions=[item for key, item in definitions.items() if key != definition]
    ).model_dump(mode="json")
    return result


def inspect_macro_definition(program: Program, definition: str) -> Program:
    """Return an isolated graph view with the library needed to inspect nesting."""
    definitions = _load_library(program)
    _validate_definitions(definitions)
    included = _closure(definitions, definition)
    result = definitions[definition].program.model_copy(deep=True)
    result.name = definitions[definition].name
    result.scan_seconds = program.scan_seconds
    result.target = program.target.model_copy(deep=True)
    result.metadata["macros"] = MacroLibrary(
        version=1, definitions=[item for key, item in definitions.items() if key in included]
    ).model_dump(mode="json")
    return result


def update_macro_definition(program: Program, definition: str, replacement: Program) -> Program:
    """Apply an isolated definition edit while preserving every public contract.

    The preview library must match the current dependency closure exactly; it is
    context for nested inspection, not an alternate place to edit dependencies.
    Input identifiers/types/units and output type/unit cannot change through this
    operation. Logic, labels, layout, defaults, description, and the definition's
    name may change. Parent scan/target and stored definition identity/revision
    stay unchanged. A previously complete root graph must remain executable.
    """
    definitions = _load_library(program)
    _validate_definitions(definitions)
    if definition not in definitions:
        raise ValueError(f"Unknown macro definition {definition!r}")
    if not isinstance(replacement, Program):
        raise ValueError("Replacement macro definition must be a Program")
    expected = inspect_macro_definition(program, definition)
    if replacement.metadata.get("macros") != expected.metadata["macros"]:
        raise ValueError(
            "Macro preview library changed or is stale; reopen the definition before applying"
        )
    if "native_sedona" in replacement.metadata:
        raise ValueError("Native extensions are forbidden inside a macro definition")
    if replacement.scan_seconds != program.scan_seconds or replacement.target != program.target:
        raise ValueError("A macro definition inherits its parent scan period and target")
    try:
        expand_macros(program)
        root_was_valid = True
    except ValueError:
        root_was_valid = False
    previous = definitions[definition]
    body = replacement.model_copy(deep=True)
    body.metadata.pop("macros")
    body.id = previous.program.id
    body.revision = previous.program.revision
    body.scan_seconds = previous.program.scan_seconds
    body.target = previous.program.target.model_copy(deep=True)
    updated = MacroDefinition(id=definition, name=replacement.name, program=body)
    before_inputs, before_output = _interfaces(previous)
    after_inputs, after_output = _interfaces(updated)
    before_contract = {node.id: (node.value_type, node.unit) for node in before_inputs}
    after_contract = {node.id: (node.value_type, node.unit) for node in after_inputs}
    if before_contract != after_contract:
        raise ValueError("Macro input identifiers, value types, and units must remain unchanged")
    if (before_output.value_type, before_output.unit) != (
        after_output.value_type,
        after_output.unit,
    ):
        raise ValueError("Macro output value type and unit must remain unchanged")
    definitions[definition] = updated
    result = program.model_copy(deep=True)
    result.metadata["macros"] = MacroLibrary(
        version=1, definitions=list(definitions.values())
    ).model_dump(mode="json")
    checked = _load_library(result)
    _validate_definitions(checked)
    # Even an unfinished root must not acquire unknown or incompatible instances.
    for node in result.nodes:
        if node.kind == "Macro":
            _reference(node, checked)
    if root_was_valid:
        expand_macros(result)
    return result
