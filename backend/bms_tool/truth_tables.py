"""Finite offline truth-table review; never a native controller interpreter."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import itertools
import json
import secrets
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import Field, ValidationError, field_validator, model_validator

from .models import StrictModel

FORMAT = "bms.truth-table"
MAX_SOURCE_BYTES = 1024 * 1024
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_CACHE_BYTES = 32 * 1024 * 1024
MAX_CASES, MAX_ROWS, MAX_INPUTS, MAX_STATES, PAGE_SIZE = 4096, 128, 12, 32, 64
Key = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,79}$")]
Name = Annotated[
    str, Field(strict=True, min_length=1, max_length=160, pattern=r"^\S(?:[^\x00-\x1f]*\S)?$")
]
Hash = Annotated[str, Field(strict=True, pattern=r"^[a-f0-9]{64}$")]
SCOPE = (
    "Offline finite Boolean/explicit integer Enum declarations and stateless evaluation only. "
    "No inferred CCT behavior, previous output, input quality, native CAF encoding, executable "
    "graph lowering, proprietary compilation, controller connection or field writes."
)


def canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Truth-table data requires bounded finite UTF-8 JSON.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE = {
    "id": "finite-truth-table-review/1",
    "limits": {
        "inputs": MAX_INPUTS,
        "states_per_domain": MAX_STATES,
        "rows": MAX_ROWS,
        "combinations": MAX_CASES,
        "page_cases": PAGE_SIZE,
        "source_bytes": MAX_SOURCE_BYTES,
        "report_bytes": MAX_REPORT_BYTES,
        "session_reports": 8,
        "cache_bytes": MAX_CACHE_BYTES,
    },
    "sources": [
        {
            "document": "JCI Controller Tool Help, LIT-12011147",
            "release": "18.0",
            "revision_date": "2025-10-06",
            "pdf_pages": [167, 168, 1690, 1691],
            "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
            "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
            "configuration_url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0/Configuring-a-System/Setting-Preferences-Steps/Logic-View-Steps/Configuring-the-Command-Hierarchy-Block",
            "documented_behavior": (
                "Command Hierarchy has Boolean or Enum output, wildcard input cells and ordered rows. "
                "The documented CCT configuration uses higher-row priority for redundant matches; "
                "unlisted combinations hold the prior output with unresolved reliability."
            ),
            "applicability": "Reviewed Release18.0 documentation only; not a controller/CAF acceptance matrix.",
        }
    ],
    "portable_policy": {
        "default_overlap": "reject",
        "explicit_priority": "first-match: source row order selects a result; every overlap/shadow remains evidence",
        "wildcard": "any declared state of this input, never an unknown or invalid value",
        "unlisted": "unresolved unless a valid constant fallback with explicit rationale is declared",
        "hold_last": False,
        "native_reliability_emulation": False,
        "enum_values": "explicit signed32-bit integers; Boolean and integer values never coerce",
    },
}
PROFILE["sha256"] = digest(PROFILE)


class State(StrictModel):
    id: Key
    label: Name
    value: Any


class Domain(StrictModel):
    id: Key
    label: Name
    kind: Literal["boolean", "enum"]
    states: list[State] = Field(min_length=1, max_length=MAX_STATES)

    @model_validator(mode="after")
    def finite_domain(self):
        if len({state.id for state in self.states}) != len(self.states):
            raise ValueError("Domain state identifiers must be unique.")
        expected = bool if self.kind == "boolean" else int
        if any(type(state.value) is not expected for state in self.states):
            raise ValueError(
                "Boolean states require exact Booleans; Enum states require exact integers."
            )
        if self.kind == "boolean" and (
            len(self.states) != 2 or {state.value for state in self.states} != {False, True}
        ):
            raise ValueError("A Boolean domain must declare exactly false and true.")
        if self.kind == "enum" and any(
            not -(2**31) <= state.value < 2**31 for state in self.states
        ):
            raise ValueError("Enum values must be signed32-bit integers.")
        if len({state.value for state in self.states}) != len(self.states):
            raise ValueError("Domain values must be unique; aliases are not inferred.")
        return self


class AnyState(StrictModel):
    kind: Literal["any"]


class ExactState(StrictModel):
    kind: Literal["state"]
    state_id: Key


Condition = Annotated[AnyState | ExactState, Field(discriminator="kind")]


class Row(StrictModel):
    id: Key
    label: Name
    conditions: dict[Key, Condition] = Field(max_length=MAX_INPUTS)
    output_state_id: Key


class Fallback(StrictModel):
    output_state_id: Key
    rationale: Annotated[str, Field(strict=True, min_length=1, max_length=512)]

    @model_validator(mode="after")
    def reason(self):
        if not self.rationale.strip() or any(not c.isprintable() for c in self.rationale):
            raise ValueError("Fallback rationale requires visible single-line text.")
        return self


class Table(StrictModel):
    format: Literal["bms.truth-table"] = FORMAT
    version: Literal[1] = 1
    id: Key
    label: Name
    inputs: list[Domain] = Field(min_length=1, max_length=MAX_INPUTS)
    output: Domain
    rows: list[Row] = Field(max_length=MAX_ROWS)
    overlap_policy: Literal["reject", "first-match"] = "reject"
    fallback: Fallback | None = None

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Truth-table version must be exact integer1.")
        return value

    @model_validator(mode="after")
    def coherent(self):
        ids = [item.id for item in self.inputs]
        if len(set(ids + [self.output.id])) != len(ids) + 1:
            raise ValueError("Input and output identifiers must be distinct and unique.")
        if len({row.id for row in self.rows}) != len(self.rows):
            raise ValueError("Row identifiers must be unique, including copied rows.")
        combinations = 1
        for item in self.inputs:
            combinations *= len(item.states)
        if combinations > MAX_CASES:
            raise ValueError(f"Declared domains exceed the{MAX_CASES}-combination review bound.")
        output_ids = {state.id for state in self.output.states}
        for row in self.rows:
            if set(row.conditions) != set(ids):
                raise ValueError(
                    f"Row {row.id} requires exactly one condition for every declared input."
                )
            for item in self.inputs:
                condition = row.conditions[item.id]
                if condition.kind == "state" and condition.state_id not in {
                    s.id for s in item.states
                }:
                    raise ValueError(
                        f"Row {row.id}, input {item.id}: undeclared state {condition.state_id}."
                    )
            if row.output_state_id not in output_ids:
                raise ValueError(f"Row {row.id}: undeclared output state.")
        if self.fallback and self.fallback.output_state_id not in output_ids:
            raise ValueError("Fallback references an undeclared output state.")
        return self


def validate_table(value):
    if len(canonical(value)) > MAX_SOURCE_BYTES:
        raise ValueError("Truth-table source exceeds1MiB.")
    try:
        return Table.model_validate(value)
    except ValidationError as exc:
        errors = json.dumps(exc.errors(include_input=False, include_context=False))
        raise ValueError("Invalid truth table: " + errors[:8000]) from None


def template():
    def boolean(id, label):
        return {
            "id": id,
            "label": label,
            "kind": "boolean",
            "states": [
                {"id": "false", "label": "False", "value": False},
                {"id": "true", "label": "True", "value": True},
            ],
        }

    return {
        "format": FORMAT,
        "version": 1,
        "id": "example-table",
        "label": "Mode and override example",
        "inputs": [
            {
                "id": "mode",
                "label": "Mode",
                "kind": "enum",
                "states": [
                    {"id": "off", "label": "Off", "value": 0},
                    {"id": "on", "label": "On", "value": 1},
                ],
            },
            boolean("override", "Override"),
        ],
        "output": boolean("result", "Run"),
        "rows": [
            {
                "id": "enabled",
                "label": "Mode enabled",
                "conditions": {
                    "mode": {"kind": "state", "state_id": "on"},
                    "override": {"kind": "any"},
                },
                "output_state_id": "true",
            },
            {
                "id": "disabled",
                "label": "Mode disabled without override",
                "conditions": {
                    "mode": {"kind": "state", "state_id": "off"},
                    "override": {"kind": "state", "state_id": "false"},
                },
                "output_state_id": "false",
            },
        ],
        "overlap_policy": "reject",
        "fallback": None,
    }


def _analyze(table):
    output_indices = {state.id: i for i, state in enumerate(table.output.states)}
    compiled = [
        tuple(
            None
            if row.conditions[item.id].kind == "any"
            else next(
                i
                for i, state in enumerate(item.states)
                if state.id == row.conditions[item.id].state_id
            )
            for item in table.inputs
        )
        for row in table.rows
    ]
    counts = {
        key: 0
        for key in (
            "cases",
            "row",
            "priority",
            "fallback",
            "uncovered",
            "overlap",
            "overlapping_cases",
            "unlisted_cases",
        )
    }
    usage = [{"row_id": row.id, "matches": 0, "chosen": 0, "shadowed": 0} for row in table.rows]
    cases = []
    for states in itertools.product(*(range(len(item.states)) for item in table.inputs)):
        matches = [
            i
            for i, conditions in enumerate(compiled)
            if all(
                expected is None or expected == actual
                for expected, actual in zip(conditions, states, strict=True)
            )
        ]
        chosen, output = None, None
        if len(matches) > 1:
            counts["overlapping_cases"] += 1
        if not matches:
            counts["unlisted_cases"] += 1
            if table.fallback:
                disposition, output = "fallback", output_indices[table.fallback.output_state_id]
            else:
                disposition = "uncovered"
        elif len(matches) > 1 and table.overlap_policy == "reject":
            disposition = "overlap"
        else:
            chosen = matches[0]
            output = output_indices[table.rows[chosen].output_state_id]
            disposition = "priority" if len(matches) > 1 else "row"
        for index in matches:
            usage[index]["matches"] += 1
        if chosen is not None:
            usage[chosen]["chosen"] += 1
            if disposition == "priority":
                for index in matches[1:]:
                    usage[index]["shadowed"] += 1
        counts["cases"] += 1
        counts[disposition] += 1
        # Ordered indices preserve every identity without repeating long labels
        # thousands of times. The exact table and row/state order are sealed.
        cases.append([list(states), matches, chosen, output, disposition])
    diagnostics = []
    for row in usage:
        if row["chosen"] == 0:
            diagnostics.append(
                {
                    "row_id": row["row_id"],
                    "code": (
                        "fully-shadowed"
                        if row["shadowed"]
                        else "only-unresolved-overlaps"
                        if row["matches"]
                        else "never-matches"
                    ),
                    "matches": row["matches"],
                    "shadowed": row["shadowed"],
                }
            )
    return cases, counts, usage, diagnostics


def _case_view(report, index):
    states, matches, chosen, output, disposition = report["coverage"][index]
    table = report["table"]
    return {
        "index": index,
        "inputs": {
            item["id"]: copy.deepcopy(item["states"][state])
            for item, state in zip(table["inputs"], states, strict=True)
        },
        "matched_row_ids": [table["rows"][row]["id"] for row in matches],
        "chosen_row_id": table["rows"][chosen]["id"] if chosen is not None else None,
        "shadowed_row_ids": [table["rows"][row]["id"] for row in matches[1:]]
        if disposition == "priority"
        else [],
        "output": copy.deepcopy(table["output"]["states"][output]) if output is not None else None,
        "disposition": disposition,
        "fallback_rationale": table["fallback"]["rationale"] if disposition == "fallback" else None,
    }


class ReviewKey(StrictModel):
    review_id: Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{32}$")]
    table_sha256: Hash
    profile_sha256: Hash


class PageBody(ReviewKey):
    offset: int = Field(default=0, strict=True, ge=0, le=MAX_CASES)
    limit: int = Field(default=PAGE_SIZE, strict=True, ge=1, le=PAGE_SIZE)
    filter: Literal["all", "uncovered", "unlisted", "overlap", "fallback", "resolved"] = "all"


class EvaluateBody(ReviewKey):
    values: dict[str, Any] = Field(max_length=MAX_INPUTS)


class ReviewBody(StrictModel):
    table: dict
    profile_sha256: Hash


class TruthTables:
    def __init__(self):
        self._reports = OrderedDict()
        self._lock = threading.RLock()

    def review(self, value):
        table = validate_table(value)
        cases, counts, usage, diagnostics = _analyze(table)
        report = {
            "format": "bms.truth-table-review",
            "version": 1,
            "id": secrets.token_hex(16),
            "reviewed_at": datetime.now(UTC).isoformat(),
            "table": table.model_dump(),
            "table_sha256": digest(table.model_dump()),
            "source_profile": copy.deepcopy(PROFILE),
            "status": "ambiguous"
            if counts["overlap"]
            else "incomplete"
            if counts["uncovered"]
            else "complete",
            "counts": counts,
            "row_usage": usage,
            "row_diagnostics": diagnostics,
            "warnings": (
                [
                    "Every overlapping case remains visible; explicit source row priority resolves selected results."
                ]
                if counts["priority"]
                else []
            )
            + (
                [
                    "A declared constant fallback resolves otherwise unlisted combinations; it does not add source rows."
                ]
                if counts["fallback"]
                else []
            ),
            "coverage_encoding": [
                "input_state_indices",
                "all_matching_row_indices",
                "chosen_row_index_or_null",
                "output_state_index_or_null",
                "disposition",
            ],
            "coverage": cases,
            "scope": SCOPE,
            "field_writes": False,
            "native_execution": False,
        }
        report["content_sha256"] = digest(report)
        raw = canonical(report) + b"\n"
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError(
                "Truth-table report exceeds its4MiB bound; no partial review was saved."
            )
        with self._lock:
            self._reports[report["id"]] = raw
            while len(self._reports) > 8 or sum(map(len, self._reports.values())) > MAX_CACHE_BYTES:
                self._reports.popitem(last=False)
        return self._summary(report) | {
            "page": self._page(
                report,
                PageBody(
                    review_id=report["id"],
                    table_sha256=report["table_sha256"],
                    profile_sha256=PROFILE["sha256"],
                ),
            )
        }

    @staticmethod
    def _summary(report):
        return {
            key: copy.deepcopy(report[key])
            for key in (
                "id",
                "reviewed_at",
                "table_sha256",
                "source_profile",
                "status",
                "counts",
                "row_usage",
                "row_diagnostics",
                "warnings",
                "content_sha256",
                "scope",
            )
        }

    def _get(self, key):
        if key.profile_sha256 != PROFILE["sha256"]:
            raise ValueError(
                "Truth-table profile changed; import or review against the current profile."
            )
        with self._lock:
            raw = self._reports.get(key.review_id)
        if raw is None:
            raise ValueError(
                "Truth-table review expired or is from another session; review the source again."
            )
        report = json.loads(raw)
        if report["table_sha256"] != key.table_sha256:
            raise ValueError(
                "Truth-table source differs from this review; review the current source again."
            )
        return report, raw

    @staticmethod
    def _page(report, request):
        def matches(row):
            return request.filter == "all" or (
                len(row[1]) > 1
                if request.filter == "overlap"
                else not row[1]
                if request.filter == "unlisted"
                else row[3] is not None
                if request.filter == "resolved"
                else row[4] == request.filter
            )

        indices = [i for i, row in enumerate(report["coverage"]) if matches(row)]
        selected = indices[request.offset : request.offset + request.limit]
        return {
            "review_id": report["id"],
            "table_sha256": report["table_sha256"],
            "content_sha256": report["content_sha256"],
            "filter": request.filter,
            "offset": request.offset,
            "total": len(indices),
            "next_offset": request.offset + len(selected)
            if request.offset + len(selected) < len(indices)
            else None,
            "cases": [_case_view(report, i) for i in selected],
        }

    def page(self, request):
        report, _ = self._get(request)
        return self._page(report, request)

    def evaluate(self, request):
        report, _ = self._get(request)
        table = report["table"]
        if set(request.values) != {item["id"] for item in table["inputs"]}:
            raise ValueError(
                "Select exactly one value for every declared input; unknown and missing inputs are refused."
            )
        selected, index = [], 0
        for item in table["inputs"]:
            value = request.values[item["id"]]
            if type(value) is not (bool if item["kind"] == "boolean" else int):
                raise ValueError(
                    "Selected Boolean and Enum values require exact declared types; no truthiness or numeric coercion."
                )
            state = next(
                (
                    i
                    for i, state in enumerate(item["states"])
                    if type(state["value"]) is type(value) and state["value"] == value
                ),
                None,
            )
            if state is None:
                raise ValueError(f"Input {item['id']} has an unknown/out-of-domain value.")
            selected.append(state)
            index = index * len(item["states"]) + state
        case = _case_view(report, index)
        result = {
            "format": "bms.truth-table-evaluation",
            "version": 1,
            "review_id": report["id"],
            "table_sha256": report["table_sha256"],
            "profile_sha256": PROFILE["sha256"],
            "review_content_sha256": report["content_sha256"],
            "values": copy.deepcopy(request.values),
            "selection_sha256": digest(request.values),
            "case": case,
            "resolved": case["output"] is not None,
            "table_status": report["status"],
            "scope": SCOPE,
            "prior_output_used": False,
        }
        result["content_sha256"] = digest(result)
        return result

    def export(self, request, kind):
        report, raw = self._get(request)
        if kind == "review":
            return raw, report["table"]["id"] + "-review.json", report["content_sha256"]
        document = {
            "format": "bms.truth-table-document",
            "version": 1,
            "source_profile": copy.deepcopy(PROFILE),
            "table_sha256": report["table_sha256"],
            "table": report["table"],
        }
        document["content_sha256"] = digest(document)
        return (
            canonical(document) + b"\n",
            report["table"]["id"] + ".bms-truth-table.json",
            document["content_sha256"],
        )


def strict_json(raw):
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Truth-table JSON exceeds1MiB.")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON keys are not a truth-table interpretation.")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON numbers are not supported.")

    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        canonical(result)
        return result
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Malformed or excessively nested truth-table JSON.") from exc


def import_document(raw):
    document = strict_json(raw)
    if (
        not isinstance(document, dict)
        or set(document)
        != {"format", "version", "source_profile", "table_sha256", "table", "content_sha256"}
        or document["format"] != "bms.truth-table-document"
        or type(document["version"]) is not int
        or document["version"] != 1
    ):
        raise ValueError("Import requires a sealed version1 portable truth-table document.")
    supplied = document.pop("content_sha256")
    if supplied != digest(document):
        raise ValueError("Truth-table document content seal failed.")
    if canonical(document["source_profile"]) != canonical(PROFILE):
        raise ValueError(
            "Truth-table source profile differs; no automatic rule migration is performed."
        )
    table = validate_table(document["table"]).model_dump()
    if document["table_sha256"] != digest(table):
        raise ValueError("Truth-table source seal failed.")
    return {
        "table": table,
        "table_sha256": digest(table),
        "source_file_sha256": hashlib.sha256(raw).hexdigest(),
        "profile_sha256": PROFILE["sha256"],
    }


async def _body(request, model):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise ValueError("Truth-table requests require application/json.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_SOURCE_BYTES:
            raise ValueError("Truth-table request exceeds1MiB.")
        raw.extend(chunk)
    try:
        return model.model_validate(strict_json(bytes(raw)))
    except ValidationError as exc:
        raise ValueError(
            "Invalid truth-table request: "
            + json.dumps(exc.errors(include_input=False, include_context=False))[:8000]
        ) from None


def truth_table_router(service):
    router = APIRouter(prefix="/api/truth-tables")

    @router.get("/profile")
    def profile():
        return {"profile": copy.deepcopy(PROFILE), "template": template(), "scope": SCOPE}

    @router.post("/review")
    async def review(request: Request):
        body = await _body(request, ReviewBody)
        if body.profile_sha256 != PROFILE["sha256"]:
            raise ValueError(
                "Truth-table profile changed; reload the reviewed rule profile before reviewing."
            )
        return await asyncio.to_thread(service.review, body.table)

    @router.post("/cases")
    async def page(request: Request):
        return service.page(await _body(request, PageBody))

    @router.post("/evaluate")
    async def evaluate(request: Request):
        return service.evaluate(await _body(request, EvaluateBody))

    @router.post("/import")
    async def import_file(file: Annotated[UploadFile, File()]):
        return import_document(await file.read(MAX_SOURCE_BYTES + 1))

    @router.post("/export/{kind}")
    async def export(kind: Literal["table", "review"], request: Request):
        raw, filename, seal = service.export(await _body(request, ReviewKey), kind)
        return Response(
            raw,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-SHA256": seal,
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
            },
        )

    return router
