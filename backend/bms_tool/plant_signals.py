"""Source-bound offline distributed-plant I/O and network mapping review."""

from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import json
import re
import secrets
import sqlite3
import threading
from collections import Counter, OrderedDict, defaultdict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import AfterValidator, Field, ValidationError, field_validator, model_validator

from .models import Program, StrictModel
from .program_source import strict_source_json

MAX_SOURCE = 1024 * 1024
MAX_SOURCES_BYTES = 8 * 1024 * 1024
MAX_SOURCE_RECORDS = 16 * 1024 * 1024
MAX_REPORT = 8 * 1024 * 1024
MAX_LIBRARY = 64 * 1024 * 1024
CAPTURE_SELECT = (
    "SELECT substr(id,1,65),substr(document,1,8388609),substr(metadata,1,4097) "
    "FROM plant_signal_captures"
)
Key = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")]
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]


def visible_name(value):
    if not value.strip() or any(not char.isprintable() for char in value):
        raise ValueError("Plant declaration names require visible printable text.")
    return value


Name = Annotated[
    str, Field(strict=True, min_length=1, max_length=160), AfterValidator(visible_name)
]
NodeId = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_\-]{0,79}$")]
SCOPE = (
    "Offline engineering schedule from exact portable Program sources and explicit host/role/link "
    "declarations. No inferred native allocation, capacity, physical wiring, actual controller identity, "
    "supervisor mapping, communication timing/reliability, source execution, simulation, field query "
    "or write. A software-consistent plan is not a commissioned or manufacturer-approved system."
)


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


PROFILE = {
    "id": "distributed-plant-signals/1",
    "scope": SCOPE,
    "limits": {
        "sources": 32,
        "source_bytes": MAX_SOURCE,
        "session_source_bytes": MAX_SOURCES_BYTES,
        "session_source_record_bytes": MAX_SOURCE_RECORDS,
        "session_review_bytes": 32 * 1024 * 1024,
        "instances": 16,
        "hosts": 16,
        "total_nodes": 4000,
        "interfaces": 1024,
        "links": 1024,
        "diagnostics": 4096,
        "session_reviews": 8,
        "report_bytes": MAX_REPORT,
        "captures": 32,
        "storage_bytes": MAX_LIBRARY,
    },
    "policy": {
        "mapping": "Explicit exact instance/node identifiers; names/SRC/DEST suffixes never allocate or match points.",
        "numeric_units": "Both source units must be nonempty and identical; no inferred dimensionless unit or conversion.",
        "terminal": "Explicit terminal keys are operator declarations; identical host/key collisions are detected, aliases/capacity/wiring remain unverified.",
        "timing": "Different declared scan periods allowed for engineering only; no synchronized network behavior inferred.",
    },
    "source": {
        "title": "Chilled Water Plant for Guideline36 Application Note",
        "document": "LIT-12014531",
        "edition": "1.0",
        "pdf_pages": [15, 16, 19, 20, 21, 49, 50, 51, 52, 53, 54],
        "sha256": "87298adc723f40cc5c0ff08d08822dbd7c931698e576b7c51b099f5a59c839d7",
        "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Chilled-Water-Plant-for-Guideline-36-Application-Note/1.0",
        "applicability": "Manual describes five combinable subsystem applications, explicit supervisory shared signals and sensor/control-point distribution. This portable plan does not encode native CAFs or reproduce plant control sequences.",
    },
}
PROFILE["sha256"] = digest(PROFILE)


def strict_json(raw, limit=MAX_REPORT):
    if not raw or len(raw) > limit:
        raise ValueError("Plant signal document exceeds its explicit byte limit.")
    try:
        return strict_source_json(raw.decode("utf-8"))
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Plant signal document requires strict bounded UTF-8 JSON.") from exc


def inspect_source(raw):
    value = strict_json(raw, MAX_SOURCE)
    if type(value) is not dict or value.get("format") == "bms.program-source/1":
        raise ValueError(
            "Import the original portable Program JSON, not an HTTP transport envelope."
        )
    if "revision" in value and type(value["revision"]) is not int:
        raise ValueError("Program revision must be an exact integer.")
    if "schema_version" in value and type(value["schema_version"]) is not int:
        raise ValueError("Program schema version must be an exact integer.")
    if type(value.get("scan_seconds")) is bool:
        raise ValueError("Program scan period cannot be a Boolean.")
    for node in value.get("nodes", []) if type(value.get("nodes", [])) is list else []:
        if type(node) is dict and any(type(node.get(key)) is bool for key in ("x", "y")):
            raise ValueError("Program coordinates cannot be Booleans.")
    program = Program.model_validate(value)
    node_ids = [node.id for node in program.nodes]
    if len(set(node_ids)) != len(node_ids):
        raise ValueError(
            "Program node identities are ambiguous; duplicate IDs cannot bind a schedule."
        )
    signals = []
    for node in program.nodes:
        if node.kind not in ("Input", "Output"):
            continue
        if len(node.unit) > 80 or any(not c.isprintable() for c in node.unit):
            raise ValueError("Interface units require at most80 printable characters.")
        terminal = node.params.get("terminal")
        signals.append(
            {
                "node_id": node.id,
                "label": node.label,
                "direction": "input" if node.kind == "Input" else "output",
                "value_type": node.value_type,
                "unit": node.unit,
                "terminal_hint": terminal
                if type(terminal) is str and len(terminal) <= 160
                else None,
                "terminal_hint_meaning": "Source text only; never a verified physical assignment.",
            }
        )
    if not signals or len(signals) > 1024:
        raise ValueError("A source must have1..1024 explicit top-level Input/Output nodes.")
    return {
        "id": hashlib.sha256(raw).hexdigest(),
        "program_id": program.id,
        "name": program.name,
        "revision_text": str(program.revision),
        "canonical_sha256": program.digest(),
        "source_bytes": len(raw),
        "scan_seconds_text": repr(program.scan_seconds),
        "nodes": len(program.nodes),
        "signals": signals,
        "source_json": raw.decode("utf-8"),
    }


class Host(StrictModel):
    id: Key
    label: Name
    declared_model: str = Field(default="", strict=True, max_length=80)


class Instance(StrictModel):
    id: Key
    label: Name
    source_id: Hash
    host_id: Key
    subsystems: list[Literal["chiller", "pchwp", "cwp", "tower", "schwp", "other"]] = Field(
        min_length=1, max_length=6
    )

    @field_validator("subsystems")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Subsystem labels must be distinct.")
        return value


class Endpoint(StrictModel):
    instance_id: Key
    node_id: NodeId


class Assignment(Endpoint):
    role: Literal["sensor", "command", "network-source", "network-destination", "unassigned"]
    terminal_key: str = Field(default="", strict=True, max_length=80)

    @field_validator("terminal_key")
    @classmethod
    def terminal_text(cls, value):
        if value != value.strip() or any(not c.isprintable() for c in value):
            raise ValueError(
                "Terminal keys require trimmed printable text; no alias normalization."
            )
        return value


class Link(StrictModel):
    id: Key
    source: Endpoint
    target: Endpoint


class Plan(StrictModel):
    format: Literal["bms.plant-signal-plan/1"] = "bms.plant-signal-plan/1"
    id: Key
    name: Name
    hosts: list[Host] = Field(min_length=1, max_length=16)
    instances: list[Instance] = Field(min_length=1, max_length=16)
    assignments: list[Assignment] = Field(default_factory=list, max_length=1024)
    links: list[Link] = Field(default_factory=list, max_length=1024)

    @model_validator(mode="after")
    def identities(self):
        for values in (self.hosts, self.instances, self.links):
            if len({item.id for item in values}) != len(values):
                raise ValueError("Host, instance and link IDs must be unique within their lists.")
        return self


class ReviewRequest(StrictModel):
    profile_sha256: Hash
    plan: Plan


class ReviewKey(StrictModel):
    id: str = Field(strict=True, pattern=r"^[a-f0-9]{32}$")
    content_sha256: Hash


class CaptureKey(StrictModel):
    id: Hash


def analyze(plan, sources):
    plan = Plan.model_validate(plan)
    hosts = {host.id: host for host in plan.hosts}
    diagnostics, rows, network = [], [], []

    def issue(code, message, *, severity="error", **detail):
        if len(diagnostics) >= 4096:
            raise ValueError("Plant diagnostics exceed4096; no truncated review retained.")
        diagnostics.append({"severity": severity, "code": code, "message": message, **detail})

    assignments = defaultdict(list)
    for assignment in plan.assignments:
        assignments[(assignment.instance_id, assignment.node_id)].append(assignment)
    endpoints = {}
    total_nodes = 0
    for item in plan.instances:
        if item.source_id not in sources:
            raise ValueError("Exact source missing from session; import/open it before review.")
        source = sources[item.source_id]
        total_nodes += source["nodes"]
        if item.host_id not in hosts:
            issue("missing_host", "Instance names an undeclared host.", instance_id=item.id)
        for signal in source["signals"]:
            key = (item.id, signal["node_id"])
            entries = assignments.get(key, [])
            assignment = entries[0] if len(entries) == 1 else None
            role = assignment.role if assignment else "unassigned"
            terminal = assignment.terminal_key if assignment else ""
            row = {
                "instance_id": item.id,
                "instance_label": item.label,
                "host_id": item.host_id,
                "host_label": hosts[item.host_id].label if item.host_id in hosts else None,
                "declared_model": hosts[item.host_id].declared_model
                if item.host_id in hosts
                else None,
                "subsystems": item.subsystems,
                "source_id": source["id"],
                "program_id": source["program_id"],
                "program_name": source["name"],
                "revision_text": source["revision_text"],
                "canonical_sha256": source["canonical_sha256"],
                **signal,
                "role": role,
                "terminal_key": terminal,
                "hardware_verified": False,
                "native_mapping_verified": False,
            }
            rows.append(row)
            endpoints[key] = row
            if len(entries) > 1:
                issue(
                    "multiple_assignments",
                    "Point has multiple role declarations; none selected.",
                    instance_id=item.id,
                    node_id=signal["node_id"],
                )
            if role == "unassigned":
                issue(
                    "unassigned_interface",
                    "Every interface needs an explicit engineering role.",
                    instance_id=item.id,
                    node_id=signal["node_id"],
                )
            expected = {
                "sensor": "input",
                "command": "output",
                "network-source": "output",
                "network-destination": "input",
            }.get(role)
            if expected and expected != signal["direction"]:
                issue(
                    "role_direction",
                    "Role conflicts with the exact source node direction.",
                    instance_id=item.id,
                    node_id=signal["node_id"],
                )
            if role in ("sensor", "command") and not terminal:
                issue(
                    "unknown_terminal",
                    "Physical terminal remains undeclared/unverified.",
                    severity="warning",
                    instance_id=item.id,
                    node_id=signal["node_id"],
                )
            if role in ("network-source", "network-destination") and terminal:
                issue(
                    "network_terminal",
                    "A network role cannot also claim a physical terminal.",
                    instance_id=item.id,
                    node_id=signal["node_id"],
                )
    if total_nodes > 4000 or len(rows) > 1024:
        raise ValueError("Plan exceeds4000 source nodes or1024 interfaces.")
    for key in assignments:
        if key not in endpoints:
            issue(
                "unknown_assignment",
                "Role declaration references an absent instance/interface.",
                instance_id=key[0],
                node_id=key[1],
            )
    terminal_users = defaultdict(list)
    for row in rows:
        if row["role"] in ("sensor", "command") and row["terminal_key"]:
            terminal_users[(row["host_id"], row["terminal_key"])].append(row)
    for (host, terminal), users in terminal_users.items():
        if len(users) > 1:
            issue(
                "terminal_collision",
                "Declared host/terminal key is used more than once; capacity/alias/wiring is not inferred.",
                host_id=host,
                terminal_key=terminal,
                endpoints=[
                    {"instance_id": row["instance_id"], "node_id": row["node_id"]} for row in users
                ],
            )
    writers = Counter((link.target.instance_id, link.target.node_id) for link in plan.links)
    fanout = Counter((link.source.instance_id, link.source.node_id) for link in plan.links)
    for link in plan.links:
        src = endpoints.get((link.source.instance_id, link.source.node_id))
        dst = endpoints.get((link.target.instance_id, link.target.node_id))
        findings = []
        if not src or not dst:
            findings.append("missing_endpoint")
        else:
            if (
                src["role"] != "network-source"
                or dst["role"] != "network-destination"
                or src["direction"] != "output"
                or dst["direction"] != "input"
            ):
                findings.append("link_direction_role")
            if src["value_type"] != dst["value_type"]:
                findings.append("link_type_mismatch")
            elif src["value_type"] == "number":
                if not src["unit"].strip() or not dst["unit"].strip():
                    findings.append("link_unit_unknown")
                elif src["unit"] != dst["unit"]:
                    findings.append("link_unit_mismatch")
        if writers[(link.target.instance_id, link.target.node_id)] > 1:
            findings.append("multiple_writers")
        for code in findings:
            issue(
                code,
                "Explicit network link is unresolved; no implicit matching, conversion or writer selection.",
                link_id=link.id,
            )
        network.append(
            {
                "id": link.id,
                "source": link.source.model_dump(),
                "target": link.target.model_dump(),
                "source_host": src["host_id"] if src else None,
                "target_host": dst["host_id"] if dst else None,
                "source_host_label": src["host_label"] if src else None,
                "target_host_label": dst["host_label"] if dst else None,
                "source_program_id": src["program_id"] if src else None,
                "target_program_id": dst["program_id"] if dst else None,
                "source_program_name": src["program_name"] if src else None,
                "target_program_name": dst["program_name"] if dst else None,
                "source_revision_text": src["revision_text"] if src else None,
                "target_revision_text": dst["revision_text"] if dst else None,
                "source_instance_label": src["instance_label"] if src else None,
                "target_instance_label": dst["instance_label"] if dst else None,
                "source_subsystems": src["subsystems"] if src else None,
                "target_subsystems": dst["subsystems"] if dst else None,
                "value_type": src["value_type"] if src else None,
                "source_unit": src["unit"] if src else None,
                "target_unit": dst["unit"] if dst else None,
                "fanout": fanout[(link.source.instance_id, link.source.node_id)],
                "status": "unresolved" if findings else "software_consistent",
                "findings": findings,
                "native_mapping_verified": False,
                "hardware_verified": False,
            }
        )
    for key, row in endpoints.items():
        if row["role"] == "network-destination" and not writers[key]:
            issue(
                "missing_writer",
                "Network destination has no explicit writer.",
                instance_id=key[0],
                node_id=key[1],
            )
        if row["role"] == "network-source" and not fanout[key]:
            issue(
                "unused_source",
                "Network source has no declared consumers.",
                severity="warning",
                instance_id=key[0],
                node_id=key[1],
            )
    errors = sum(row["severity"] == "error" for row in diagnostics)
    return {
        "status": "unresolved" if errors else "software_consistent",
        "errors": errors,
        "warnings": len(diagnostics) - errors,
        "io_schedule": rows,
        "network_schedule": network,
        "diagnostics": diagnostics,
        "hardware_verified": False,
        "native_mapping_verified": False,
    }


def source_summary(source):
    return {key: copy.deepcopy(value) for key, value in source.items() if key != "source_json"}


def view_report(report):
    result = copy.deepcopy(report)
    result["sources"] = [source_summary(source) for source in report["sources"]]
    return result


def verify_report(raw):
    report = strict_json(raw)
    expected = {
        "format",
        "id",
        "reviewed_at",
        "profile",
        "plan",
        "plan_sha256",
        "sources",
        "analysis",
        "scope",
        "field_queries",
        "field_writes",
        "content_sha256",
    }
    if (
        type(report) is not dict
        or set(report) != expected
        or report["format"] != "bms.plant-signal-review/1"
    ):
        raise ValueError("Expected a sealed version1 plant signal review.")
    if not isinstance(report["id"], str) or not re.fullmatch(r"[a-f0-9]{32}", report["id"]):
        raise ValueError("Invalid plant review identity.")
    if (
        type(report["reviewed_at"]) is not str
        or len(report["reviewed_at"]) > 48
        or datetime.fromisoformat(report["reviewed_at"]).utcoffset() is None
    ):
        raise ValueError("Review timestamp requires explicit timezone text.")
    if (
        encoded(report["profile"]) != encoded(PROFILE)
        or report["scope"] != SCOPE
        or report["field_queries"] is not False
        or report["field_writes"] is not False
    ):
        raise ValueError("Plant review profile/scope differs; no automatic migration.")
    if report["content_sha256"] != digest(
        {key: value for key, value in report.items() if key != "content_sha256"}
    ):
        raise ValueError("Plant review content seal failed.")
    plan = Plan.model_validate(report["plan"])
    if encoded(plan.model_dump()) != encoded(report["plan"]) or report["plan_sha256"] != digest(
        plan.model_dump()
    ):
        raise ValueError("Plant declaration source seal/type proof failed.")
    if type(report["sources"]) is not list or not 1 <= len(report["sources"]) <= 16:
        raise ValueError("Plant review requires1..16 exact sources.")
    sources = {}
    for item in report["sources"]:
        if type(item) is not dict or type(item.get("source_json")) is not str:
            raise ValueError("Original Program source text missing from review.")
        source = inspect_source(item["source_json"].encode("utf-8"))
        if encoded(item) != encoded(source) or source["id"] in sources:
            raise ValueError("Plant Program source/identity proof failed or duplicated.")
        sources[source["id"]] = source
    if set(sources) != {item.source_id for item in plan.instances}:
        raise ValueError("Review sources do not exactly match its instances.")
    if sum(source["source_bytes"] for source in sources.values()) > MAX_SOURCES_BYTES:
        raise ValueError("Combined Program sources exceed8MiB.")
    if encoded(report["analysis"]) != encoded(analyze(plan, sources)):
        raise ValueError("Plant analysis/type proof failed regeneration.")
    return report, sources


class PlantSignals:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.sources, self.reviews = OrderedDict(), OrderedDict()
        with self.store.connect(timeout=0.25) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS plant_signal_captures(id TEXT PRIMARY KEY, document BLOB NOT NULL, metadata BLOB NOT NULL)"
            )

    def import_source(self, raw):
        source = inspect_source(raw)
        with self.lock:
            if source["id"] not in self.sources:
                if (
                    len(self.sources) >= 32
                    or sum(item["source_bytes"] for item in self.sources.values()) + len(raw)
                    > MAX_SOURCES_BYTES
                    or sum(len(encoded(item)) for item in self.sources.values())
                    + len(encoded(source))
                    > MAX_SOURCE_RECORDS
                ):
                    raise ValueError(
                        "Session source capacity reached; remove an unused source or reopen later. No source overwritten."
                    )
                self.sources[source["id"]] = source
        return source_summary(source)

    def source(self, id):
        with self.lock:
            if id not in self.sources:
                raise ValueError("Program source not in session; import or reopen its capture.")
            return self.sources[id]["source_json"].encode("utf-8")

    def remove_source(self, id):
        with self.lock:
            if id not in self.sources:
                raise ValueError("Program source not retained.")
            del self.sources[id]
        return {"removed": id, "field_queries": False}

    def review(self, request):
        if request.profile_sha256 != PROFILE["sha256"]:
            raise ValueError("Plant profile changed; reload before review.")
        plan = request.plan
        with self.lock:
            ids = {item.source_id for item in plan.instances}
            if ids - self.sources.keys():
                raise ValueError("Exact source missing; import or reopen before reviewing.")
            sources = {id: copy.deepcopy(self.sources[id]) for id in sorted(ids)}
        analysis = analyze(plan, sources)
        report = {
            "format": "bms.plant-signal-review/1",
            "id": secrets.token_hex(16),
            "reviewed_at": datetime.now(UTC).isoformat(),
            "profile": copy.deepcopy(PROFILE),
            "plan": plan.model_dump(),
            "plan_sha256": digest(plan.model_dump()),
            "sources": list(sources.values()),
            "analysis": analysis,
            "scope": SCOPE,
            "field_queries": False,
            "field_writes": False,
        }
        report["content_sha256"] = digest(report)
        raw = encoded(report) + b"\n"
        if len(raw) > MAX_REPORT:
            raise ValueError("Plant review exceeds8MiB; no truncated report retained.")
        self._retain(report["id"], raw)
        return view_report(report)

    def _retain(self, id, raw):
        with self.lock:
            if id in self.reviews and self.reviews[id] != raw:
                raise ValueError("Plant review ID collision; existing review not overwritten.")
            self.reviews[id] = raw
            while len(self.reviews) > 8 or sum(map(len, self.reviews.values())) > 32 * 1024 * 1024:
                self.reviews.popitem(last=False)

    def _review(self, key):
        with self.lock:
            raw = self.reviews.get(key.id)
        if raw is None:
            raise ValueError("Plant review expired; review the current declaration again.")
        report, _ = verify_report(raw)
        if report["content_sha256"] != key.content_sha256:
            raise ValueError("Plant review source changed; refresh its review.")
        return raw, report

    @staticmethod
    def _capture(row):
        if row is None:
            raise ValueError("Saved plant review not found.")
        id, raw, metadata = row
        if (
            type(id) is not str
            or type(raw) is not bytes
            or type(metadata) is not bytes
            or not raw
            or not metadata
        ):
            raise ValueError("Plant capture storage has invalid identity/BLOB types.")
        if len(raw) > MAX_REPORT or hashlib.sha256(raw).hexdigest() != id:
            raise ValueError("Plant capture file hash/size failed.")
        report, _ = verify_report(raw)
        meta = strict_json(metadata, 4096)
        if type(meta) is not dict or set(meta) != {
            "id",
            "report_id",
            "content_sha256",
            "name",
            "ingested_at",
            "origin",
            "bytes",
            "metadata_sha256",
        }:
            raise ValueError("Plant capture metadata profile failed.")
        if meta["metadata_sha256"] != digest(
            {key: value for key, value in meta.items() if key != "metadata_sha256"}
        ):
            raise ValueError("Plant capture metadata seal failed.")
        if (
            meta["id"] != id
            or meta["report_id"] != report["id"]
            or meta["content_sha256"] != report["content_sha256"]
            or meta["name"] != report["plan"]["name"]
            or type(meta["bytes"]) is not int
            or meta["bytes"] != len(raw)
            or meta["origin"] not in ("local-review", "import")
        ):
            raise ValueError("Plant capture metadata does not bind original report.")
        if (
            type(meta["ingested_at"]) is not str
            or len(meta["ingested_at"]) > 48
            or datetime.fromisoformat(meta["ingested_at"]).utcoffset() is None
        ):
            raise ValueError("Plant capture ingest timestamp is invalid.")
        return raw, report, meta

    def _load(self, id):
        try:
            with self.store.connect(timeout=0.25) as db:
                row = db.execute(CAPTURE_SELECT + " WHERE id=?", (id,)).fetchone()
            return self._capture(tuple(row) if row is not None else None)
        except sqlite3.Error as exc:
            raise ValueError(
                "Plant capture store unavailable; no mutation or automatic retry."
            ) from exc

    def _save(self, raw, origin):
        report, _ = verify_report(raw)
        id = hashlib.sha256(raw).hexdigest()
        meta = {
            "id": id,
            "report_id": report["id"],
            "content_sha256": report["content_sha256"],
            "name": report["plan"]["name"],
            "ingested_at": datetime.now(UTC).isoformat(),
            "origin": origin,
            "bytes": len(raw),
        }
        meta["metadata_sha256"] = digest(meta)
        metadata = encoded(meta)
        try:
            with self.store.connect(timeout=0.25) as db:
                db.execute("BEGIN IMMEDIATE")
                existing = db.execute(CAPTURE_SELECT + " WHERE id=?", (id,)).fetchone()
                if existing is not None:
                    _, _, saved = self._capture(tuple(existing))
                    return saved | {"deduplicated": True}
                count, used = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(length(CAST(document AS BLOB))+length(CAST(metadata AS BLOB))),0) FROM plant_signal_captures"
                ).fetchone()
                if count >= 32 or used + len(raw) + len(metadata) > MAX_LIBRARY:
                    raise ValueError(
                        "Plant capture capacity reached; no overwrite/eviction. Remove a selected saved capture first."
                    )
                db.execute(
                    "INSERT INTO plant_signal_captures(id,document,metadata) VALUES(?,?,?)",
                    (id, raw, metadata),
                )
        except sqlite3.Error as exc:
            raise ValueError("Plant capture publication failed; no automatic retry.") from exc
        return meta | {"deduplicated": False}

    def save_review(self, key):
        raw, _ = self._review(key)
        return self._save(raw, "local-review")

    def import_capture(self, raw):
        return self._save(raw, "import")

    def open_capture(self, id):
        raw, report, meta = self._load(id)
        sources = {source["id"]: source for source in report["sources"]}
        with self.lock:
            if report["id"] in self.reviews and self.reviews[report["id"]] != raw:
                raise ValueError("Plant review ID collision; no source or review overwritten.")
            added = {id: value for id, value in sources.items() if id not in self.sources}
            if (
                len(self.sources) + len(added) > 32
                or sum(item["source_bytes"] for item in [*self.sources.values(), *added.values()])
                > MAX_SOURCES_BYTES
                or sum(len(encoded(item)) for item in [*self.sources.values(), *added.values()])
                > MAX_SOURCE_RECORDS
            ):
                raise ValueError(
                    "Opening this capture exceeds session source capacity; no partial source restore."
                )
            self.sources.update(added)
            self._retain(report["id"], raw)
        return {"capture": meta, "review": view_report(report)}

    def remove_capture(self, id):
        self._load(id)
        try:
            with self.store.connect(timeout=0.25) as db:
                db.execute("DELETE FROM plant_signal_captures WHERE id=?", (id,))
        except sqlite3.Error as exc:
            raise ValueError("Plant capture removal failed; no automatic retry.") from exc
        return {"removed": id, "field_queries": False}

    def status(self):
        try:
            with self.store.connect(timeout=0.25) as db:
                count, used = db.execute(
                    "SELECT COUNT(*),COALESCE(SUM(length(CAST(document AS BLOB))+length(CAST(metadata AS BLOB))),0) FROM plant_signal_captures"
                ).fetchone()
                if count > 32 or used > MAX_LIBRARY:
                    raise ValueError("Saved plant capture count/bytes exceed the store profile.")
                rows = db.execute(CAPTURE_SELECT + " ORDER BY rowid").fetchmany(33)
            if len(rows) > 32:
                raise ValueError("Saved plant capture count exceeds32; storage not trusted.")
            captures = [self._capture(tuple(row))[2] for row in rows]
        except sqlite3.Error as exc:
            raise ValueError("Plant capture store unavailable.") from exc
        with self.lock:
            sources = [source_summary(source) for source in self.sources.values()]
        return {
            "profile": copy.deepcopy(PROFILE),
            "sources": sources,
            "captures": captures,
            "scope": SCOPE,
            "field_queries": False,
            "field_writes": False,
        }

    @staticmethod
    def csv_report(report):
        output = io.StringIO(newline="")
        fields = [
            "review_content_sha256",
            "plan_sha256",
            "profile_sha256",
            "record_type",
            "id",
            "instance_id",
            "instance_label",
            "host_id",
            "host_label",
            "declared_model",
            "subsystems",
            "program_id",
            "program_name",
            "revision_text",
            "node_id",
            "label",
            "direction",
            "value_type",
            "unit",
            "role",
            "terminal_key",
            "source_id",
            "canonical_sha256",
            "source",
            "target",
            "source_host",
            "target_host",
            "source_host_label",
            "target_host_label",
            "source_program_id",
            "target_program_id",
            "source_program_name",
            "target_program_name",
            "source_revision_text",
            "target_revision_text",
            "source_instance_label",
            "target_instance_label",
            "source_subsystems",
            "target_subsystems",
            "source_unit",
            "target_unit",
            "fanout",
            "hardware_verified",
            "native_mapping_verified",
            "status",
            "findings",
        ]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()

        def safe(value):
            if type(value) is bool:
                return "true" if value else "false"
            value = (
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (list, dict))
                else str(value)
            )
            return (
                "'" + value
                if value.lstrip().startswith(("=", "+", "-", "@"))
                or value.startswith(("\t", "\r", "\n"))
                else value
            )

        for kind, rows in (
            ("io", report["analysis"]["io_schedule"]),
            ("network", report["analysis"]["network_schedule"]),
        ):
            for row in rows:
                result = {key: safe(value) for key, value in row.items() if key in fields}
                result.update(
                    review_content_sha256=report["content_sha256"],
                    plan_sha256=report["plan_sha256"],
                    profile_sha256=PROFILE["sha256"],
                    record_type=kind,
                )
                writer.writerow(result)
        return output.getvalue().encode("utf-8")

    def export_review(self, key, kind):
        raw, report = self._review(key)
        return raw if kind == "json" else self.csv_report(report)

    def export_capture(self, id, kind):
        raw, report, _ = self._load(id)
        return raw if kind == "json" else self.csv_report(report)


async def _body(request, model):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_REPORT:
            raise ValueError("Plant request exceeds8MiB.")
        raw.extend(chunk)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ValueError("Plant requests require application/json.")
    try:
        return model.model_validate(strict_json(bytes(raw)))
    except ValidationError as exc:
        raise ValueError(
            "Invalid plant request: "
            + json.dumps(exc.errors(include_input=False, include_context=False))[:3000]
        ) from None


def plant_signal_router(service):
    router = APIRouter(prefix="/api/plant-signals")

    @router.get("/profile")
    async def profile():
        return await asyncio.to_thread(service.status)

    @router.post("/sources/import")
    async def import_source(file: Annotated[UploadFile, File()]):
        try:
            return await asyncio.to_thread(service.import_source, await file.read(MAX_SOURCE + 1))
        except ValidationError:
            raise ValueError("Imported portable Program interface/schema is invalid.") from None

    @router.post("/sources/export")
    async def export_source(request: Request):
        key = await _body(request, CaptureKey)
        raw = service.source(key.id)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="plant-program-{key.id}.json"',
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
            },
        )

    @router.post("/sources/remove")
    async def remove_source(request: Request):
        return service.remove_source((await _body(request, CaptureKey)).id)

    @router.post("/review")
    async def review(request: Request):
        return await asyncio.to_thread(service.review, await _body(request, ReviewRequest))

    @router.post("/reviews/export/{kind}")
    async def export_review(kind: Literal["json", "csv"], request: Request):
        key = await _body(request, ReviewKey)
        raw = await asyncio.to_thread(service.export_review, key, kind)
        return _download(raw, "plant-review-" + key.id, kind)

    @router.post("/captures/save")
    async def save(request: Request):
        return await asyncio.to_thread(service.save_review, await _body(request, ReviewKey))

    @router.post("/captures/import")
    async def import_capture(file: Annotated[UploadFile, File()]):
        try:
            return await asyncio.to_thread(service.import_capture, await file.read(MAX_REPORT + 1))
        except ValidationError:
            raise ValueError("Imported plant source/declaration schema is invalid.") from None

    @router.post("/captures/open")
    async def open_capture(request: Request):
        return await asyncio.to_thread(service.open_capture, (await _body(request, CaptureKey)).id)

    @router.post("/captures/remove")
    async def remove_capture(request: Request):
        return await asyncio.to_thread(
            service.remove_capture, (await _body(request, CaptureKey)).id
        )

    @router.post("/captures/export/{kind}")
    async def export_capture(kind: Literal["json", "csv"], request: Request):
        key = await _body(request, CaptureKey)
        raw = await asyncio.to_thread(service.export_capture, key.id, kind)
        return _download(raw, "plant-capture-" + key.id, kind)

    return router


def _download(raw, name, kind):
    return Response(
        raw,
        media_type="application/json" if kind == "json" else "text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.{kind}"',
            "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
        },
    )
