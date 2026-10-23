"""Versioned private IEC names, independent of portable graph identifiers."""

from __future__ import annotations

import copy
import hashlib
import json

from .engine import output_type
from .macros import expand_macros
from .models import Program
from .source_profiles import read_profile_json, source_profile, verify_source_profile

CURRENT = "studio-iec-symbols/1"
LEGACY = "studio-iec-symbols/legacy"
RULES = {
    "id": CURRENT,
    "ordering": "Original expanded identifiers sorted by Python Unicode code-point order; no case folding, sanitization or normalization of logical IDs.",
    "private_ids": "Zero-based sorted ordinal rendered as bms plus six decimal digits. Private stems end in digits; generated helper roles append distinct nonnumeric suffixes.",
    "scope": "Validated private expanded graph copy only. Original Program, identifiers, metadata, source bytes, revision and digest remain unchanged.",
    "roles": "All node values; Output stage; Input valid; hosted Schedule calendar/calendar_valid; Delay/Deadband/Slew memory; PI integral/candidate/error/raw; TimerOn/Alarm elapsed/next.",
    "globals": "StudioScanSeconds REAL, StudioDayOfWeek INT, StudioMinuteOfDay INT, StudioFault BOOL retained unchanged. Complete declaration names must be unique under case folding.",
    "state_labels": "JSON retained-state labels use n_ plus original expanded ID plus _memory/_integral/_elapsed. No sanitization; case and Unicode remain distinct. Existing underscore-only labels are unchanged.",
    "compatibility": "ST V3 and explicitly symbol-qualified PLCopen only; legacy V1/V2 and Sedona retain frozen old emission and numeric profiles. No marker/rules fallback or reseal.",
}
GLOBALS = [
    {"symbol": "StudioScanSeconds", "type": "REAL"},
    {"symbol": "StudioDayOfWeek", "type": "INT"},
    {"symbol": "StudioMinuteOfDay", "type": "INT"},
    {"symbol": "StudioFault", "type": "BOOL"},
]


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def symbol_profile():
    return {"id": CURRENT, "rules_sha256": digest(RULES)}


def verify_symbol_profile(value):
    if type(value) is not dict or set(value) != {"id", "rules_sha256"}:
        raise ValueError("IEC symbol profile requires an exact ID and rules digest.")
    if value != symbol_profile():
        raise ValueError("Unknown or conflicting IEC symbol profile/rules digest.")


def allocate_ids(identifiers):
    """Do not impose a second character/normalization policy on admitted IDs."""
    identifiers = list(identifiers)
    if any(type(identifier) is not str for identifier in identifiers):
        raise ValueError("IEC symbol allocation requires string identifiers.")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("IEC symbol allocation requires unique original identifiers.")
    return {identifier: f"bms{index:06d}" for index, identifier in enumerate(sorted(identifiers))}


def _roles(node):
    value_type = "BOOL" if output_type(node) == "boolean" else "REAL"
    roles = {"value": ("", value_type)}
    if node.kind == "Input":
        roles["valid"] = ("_valid", "BOOL")
    elif node.kind == "Output":
        roles["stage"] = ("_stage", value_type)
    elif node.kind == "Schedule" and (node.params.get("timezone") or node.params.get("exceptions")):
        roles.update(calendar=("_calendar", "BOOL"), calendar_valid=("_calendar_valid", "BOOL"))
    elif node.kind in ("Delay", "Deadband", "Slew"):
        roles["memory"] = ("_memory", value_type)
    elif node.kind == "PI":
        roles.update(
            {role: ("_" + role, "REAL") for role in ("integral", "candidate", "error", "raw")}
        )
    elif node.kind in ("TimerOn", "Alarm"):
        roles.update(elapsed=("_elapsed", "REAL"), next=("_next", "REAL"))
    return roles


class SymbolTable:
    """One allocation supplies both the emitter and the actual host bindings."""

    def __init__(self, program):
        self._graph = expand_macros(program)
        self._ids = allocate_ids(node.id for node in self._graph.nodes)
        self._lookup, nodes = {}, []
        indexed = {node.id: node for node in self._graph.nodes}
        for identifier, private in self._ids.items():
            node, roles = indexed[identifier], {}
            for role, (suffix, typ) in _roles(node).items():
                descriptor = {"symbol": "n_" + private + suffix, "type": typ}
                if role in ("memory", "integral", "elapsed"):
                    descriptor["state_label"] = "n_" + identifier + suffix
                self._lookup[(identifier, role)] = descriptor
                roles[role] = descriptor
            nodes.append(
                {"id": identifier, "private_id": private, "kind": node.kind, "roles": roles}
            )
        self._document = {
            "format": "bms.iec-symbol-table/1",
            "profile": symbol_profile(),
            "globals": copy.deepcopy(GLOBALS),
            "nodes": nodes,
        }
        self.sha256 = digest(self._document)
        names = [row["symbol"].casefold() for row in GLOBALS] + [
            row["symbol"].casefold() for row in self._lookup.values()
        ]
        if len(names) != len(set(names)):
            raise ValueError("Allocated IEC declaration namespace is not unique.")
        labels = [row["state_label"] for row in self._lookup.values() if "state_label" in row]
        if len(labels) != len(set(labels)):
            raise ValueError("Allocated IEC retained-state labels are not unique.")

    def role(self, identifier, role="value"):
        try:
            return self._lookup[(identifier, role)]["symbol"]
        except KeyError as error:
            raise ValueError("No allocated IEC role for the original node.") from error

    def state_rows(self):
        return [copy.deepcopy(row) for row in self._lookup.values() if "state_label" in row]

    def evidence(self):
        return copy.deepcopy(self._document) | {"sha256": self.sha256}

    def lowered(self):
        lowered = self._graph.model_copy(deep=True)
        for node in lowered.nodes:
            node.id = self._ids[node.id]
        for edge in lowered.edges:
            edge.source, edge.target = self._ids[edge.source], self._ids[edge.target]
        return lowered

    def verify_declarations(self, declarations):
        actual = [(name, typ) for group in declarations.values() for name, typ, _ in group]
        expected = [(row["symbol"], row["type"]) for row in GLOBALS] + [
            (row["symbol"], row["type"]) for row in self._lookup.values()
        ]
        if sorted(actual) != sorted(expected):
            raise ValueError("IEC declarations differ from the allocated typed symbol roles.")


def source_document(program):
    return canonical(
        {
            "source_generator": source_profile(),
            "symbol_generator": symbol_profile(),
            "program": program.model_dump(),
        }
    )


def read_source_document(raw):
    document = read_profile_json(raw, limit=8 * 1024 * 1024)
    if type(document) is not dict or set(document) != {
        "source_generator",
        "symbol_generator",
        "program",
    }:
        raise ValueError("Invalid versioned IEC source document fields.")
    verify_source_profile(document["source_generator"])
    verify_symbol_profile(document["symbol_generator"])
    return Program.model_validate(document["program"])
