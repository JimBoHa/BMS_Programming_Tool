"""Operator-declared acceptance checks for the portable Studio graph engine only."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import AwareDatetime, Field, field_validator

from .blocks import BLOCKS
from .engine import Engine, ScanError, output_type
from .executable_numbers import require_number
from .models import Program, StrictModel
from .storage import Conflict

MAX_BYTES = 2 * 1024 * 1024
MAX_REPORT = 4 * 1024 * 1024
MAX_PLANS = 100
MAX_STORAGE = 32 * 1024 * 1024
MAX_STEPS = 5000
MAX_WORK = 1_000_000
SCOPE = "Declared checks of portable Studio graph behavior only; no native CAF execution, physical controller simulation, complete sequence coverage or Title24/Guideline36 certification."
SEMANTICS = {
    "profile": "studio-graph-conformance/1",
    "cases": "Each case starts a fresh Engine with default inputs and empty retained state; cases never share state.",
    "events": "Events apply at an exact scan start; omitted inputs hold their previous sample. The first scan starts at elapsed zero.",
    "checks": "Value checks observe supported root-block values after a successful scan at its exact elapsed end time. Units and types must match; no conversion is inferred.",
    "numeric": "Finite binary64 values; abs(actual-expected) <= max(abs_tol,rel_tol*max(abs(actual),abs(expected))). Boolean checks are exact and have zero tolerances. Nonrepresentable integer criteria/stimuli are refused; nonrepresentable integer actuals explicitly fail the comparison.",
    "fault": "An expected ScanError must occur on the final attempted scan, match an optional literal substring and leave the Engine snapshot unchanged. No regex or executable scripts.",
    "clock": "Operator-selected aware start clock normalized to UTC; each attempted scan uses start_clock plus its elapsed end time. Wall-clock speed does not affect results.",
    "coverage": "Only listed signal/time/value checks and supplied input samples are asserted. Unlisted signals, times, conditions, combinations and physical behavior remain untested.",
}


def canonical(value):
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError("Conformance data requires bounded finite JSON values.") from exc


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(SEMANTICS)
Finite = Annotated[float, Field(strict=True, ge=0, le=1e308)]
Time = Annotated[float, Field(strict=True, ge=0, le=86400)]
Identity = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Sample(StrictModel):
    value: Any
    quality: Literal["good", "open-circuit", "short-circuit", "unreliable", "out-of-service"] = (
        "good"
    )


class Event(StrictModel):
    time: Time
    inputs: dict[str, Sample] = Field(min_length=1, max_length=2000)


class Check(StrictModel):
    id: Identity
    label: str = Field(default="", max_length=200)
    time: Time
    signal: Identity
    unit: str = Field(max_length=100)
    expected: Any
    abs_tol: Finite = 0.0
    rel_tol: Annotated[float, Field(strict=True, ge=0, le=1)] = 0.0


class ExpectedFault(StrictModel):
    time: Time
    contains: str = Field(default="", max_length=200)


class Case(StrictModel):
    id: Identity
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    duration: Annotated[float, Field(strict=True, gt=0, le=86400)] = 10.0
    dt: Annotated[float, Field(strict=True, gt=0, le=60)] = 1.0
    start_clock: AwareDatetime = datetime(2026, 1, 5, tzinfo=UTC)
    events: list[Event] = Field(default_factory=list, max_length=1000)
    checks: list[Check] = Field(default_factory=list, max_length=1000)
    expected_fault: ExpectedFault | None = None

    @field_validator("start_clock")
    @classmethod
    def utc_clock(cls, value):
        return value.astimezone(UTC)


class Suite(StrictModel):
    format: Literal["bms.graph-conformance-suite"]
    version: Literal[1]
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    program_sha256: Hash
    program_id: str = Field(min_length=1, max_length=80)
    program_revision: int = Field(ge=0, strict=True)
    execution_profile_sha256: Hash
    signals: list[dict] = Field(min_length=1, max_length=2000)
    cases: list[Case] = Field(min_length=1, max_length=20)

    @field_validator("version", mode="before")
    @classmethod
    def exact_version(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("Conformance suite requires integer version1.")
        return value


def contract(program):
    engine = Engine(program)  # Rejects invalid graphs and unexecuted native extensions.
    signals = [
        {
            "id": n.id,
            "label": n.label,
            "kind": n.kind,
            "type": output_type(n),
            "unit": n.unit,
            "role": "input"
            if n.kind == "Input"
            else "output"
            if n.kind == "Output"
            else "internal",
        }
        for n in program.nodes
    ]
    if any(row["id"] not in engine.nodes for row in signals):
        raise ValueError("A root graph signal lacks an observable portable execution value.")
    return engine, signals


def template(program):
    _, signals = contract(program)
    return Suite(
        format="bms.graph-conformance-suite",
        version=1,
        name="New conformance suite",
        program_sha256=program.digest(),
        program_id=program.id,
        program_revision=program.revision,
        execution_profile_sha256=PROFILE_SHA,
        signals=signals,
        cases=[Case(id="case_1", name="New test case", dt=program.scan_seconds)],
    ).model_dump(mode="json")


def grid(case):
    duration, dt = Decimal(str(case.duration)), Decimal(str(case.dt))
    count = int((duration / dt).to_integral_value(rounding=ROUND_CEILING))
    if count > MAX_STEPS:
        raise ValueError("Conformance suite exceeds the5000 scan budget.")
    starts = [i * dt for i in range(count)]
    return starts, [min(start + dt, duration) for start in starts]


def scalar(value, typ, label):
    if typ == "boolean":
        if type(value) is not bool:
            raise ValueError(f"{label} requires an exact Boolean.")
        return value
    return float(require_number(value, label))


def validate_suite(program, value):
    if len(canonical(value)) > MAX_BYTES:
        raise ValueError("Conformance suite exceeds2MiB.")
    suite = Suite.model_validate(value)
    if not suite.name.strip() or any(not case.name.strip() for case in suite.cases):
        raise ValueError("Suite and case names must contain visible text.")
    engine, signals = contract(program)
    if (
        suite.program_sha256 != program.digest()
        or suite.program_id != program.id
        or suite.program_revision != program.revision
    ):
        raise ValueError(
            "Conformance suite requires the exact source program hash, identity and revision."
        )
    if suite.execution_profile_sha256 != PROFILE_SHA or canonical(suite.signals) != canonical(
        signals
    ):
        raise ValueError(
            "Conformance execution profile or exact signal/type/unit contract changed."
        )
    by_id = {row["id"]: row for row in signals}
    seen, steps, checks = set(), 0, 0
    for case in suite.cases:
        if case.id in seen:
            raise ValueError("Conformance case IDs must be unique.")
        seen.add(case.id)
        starts, ends = grid(case)
        steps += len(starts)
        checks += len(case.checks)
        if steps > MAX_STEPS or steps * len(engine.nodes) > MAX_WORK or checks > 2000:
            raise ValueError(
                "Conformance suite exceeds5000 scans,2000 checks or1000000 block evaluations."
            )
        if not case.checks and case.expected_fault is None:
            raise ValueError(
                "Each test case needs at least one explicit value check or expected fault."
            )
        if case.expected_fault and (Decimal(str(case.expected_fault.time)) != ends[-1]):
            raise ValueError("Expected fault time must be the final attempted scan end.")
        previous = Decimal(-1)
        for event in case.events:
            time = Decimal(str(event.time))
            if time not in starts or time <= previous:
                raise ValueError(
                    "Stimuli require unique increasing exact scan-start times before case duration."
                )
            previous = time
            for identity, sample in event.inputs.items():
                signal = by_id.get(identity)
                if signal is None or signal["role"] != "input":
                    raise ValueError("Stimuli must identify an existing root Input block.")
                sample.value = scalar(sample.value, signal["type"], f"Input {identity}")
        check_ids = set()
        for check in case.checks:
            if check.id in check_ids:
                raise ValueError("Check IDs must be unique within each case.")
            check_ids.add(check.id)
            signal = by_id.get(check.signal)
            if signal is None or signal["unit"] != check.unit:
                raise ValueError(
                    "Check signal or exact engineering unit does not match the source contract."
                )
            if Decimal(str(check.time)) not in ends or (
                case.expected_fault and check.time >= case.expected_fault.time
            ):
                raise ValueError(
                    "Checks require exact successful scan-end times before any expected fault."
                )
            check.expected = scalar(check.expected, signal["type"], f"Check {check.id}")
            if signal["type"] == "boolean" and (check.abs_tol or check.rel_tol):
                raise ValueError("Boolean checks require zero tolerances.")
        try:
            case.start_clock + timedelta(seconds=case.duration)
        except OverflowError as exc:
            raise ValueError("Conformance clock exceeds the supported datetime range.") from exc
    if len(canonical(suite.model_dump(mode="json"))) > MAX_BYTES:
        raise ValueError("Normalized conformance suite exceeds2MiB.")
    return suite


def run_suite(program, value):
    suite = validate_suite(program, value)
    signal_ids = {row["id"] for row in suite.signals}
    input_ids = {row["id"] for row in suite.signals if row["role"] == "input"}
    output_ids = {row["id"] for row in suite.signals if row["role"] == "output"}
    cases = []
    for case in suite.cases:
        engine = Engine(program)
        engine.clock = case.start_clock
        starts, ends = grid(case)
        inputs, comparisons, observations = {}, [], []
        events = {Decimal(str(row.time)): row for row in case.events}
        checks_at = {}
        for check in case.checks:
            checks_at.setdefault(Decimal(str(check.time)), []).append(check)
        fault = None
        evaluated = set()
        successful_scans = 0
        for start, end in zip(starts, ends, strict=True):
            if start in events:
                inputs.update(
                    {key: sample.model_dump() for key, sample in events[start].inputs.items()}
                )
            before = engine.snapshot()
            try:
                row = engine.step(
                    inputs,
                    dt=float(end - start),
                    clock=case.start_clock + timedelta(seconds=float(end)),
                )
            except ScanError as exc:
                message = str(exc)[:2048]
                unchanged = before == engine.snapshot()
                expected = case.expected_fault
                accepted = bool(
                    expected
                    and float(end) == expected.time
                    and expected.contains in message
                    and unchanged
                )
                fault = {
                    "time": float(end),
                    "message": message,
                    "expected": expected.model_dump() if expected else None,
                    "snapshot_unchanged": unchanged,
                    "passed": accepted,
                }
                break
            successful_scans += 1
            observed = {}
            for check in checks_at.get(end, []):
                actual = row["values"][check.signal]
                representation_error = None
                try:
                    scalar(
                        actual,
                        "boolean" if type(check.expected) is bool else "number",
                        f"Actual {check.signal}",
                    )
                except ValueError as exc:
                    representation_error = str(exc)
                passed = not representation_error and (
                    (actual is check.expected)
                    if type(check.expected) is bool
                    else math.isclose(
                        actual, check.expected, rel_tol=check.rel_tol, abs_tol=check.abs_tol
                    )
                )
                error = (
                    None
                    if type(actual) is bool or representation_error
                    else abs(actual - check.expected)
                )
                comparisons.append(
                    check.model_dump()
                    | {
                        "actual": actual,
                        "passed": passed,
                        "numeric_representation_error": representation_error,
                        "absolute_error": error if error is None or math.isfinite(error) else None,
                        "error_overflow": error is not None and not math.isfinite(error),
                        "clock": row["clock"],
                    }
                )
                evaluated.add(check.id)
                observed[check.signal] = actual
            if observed:
                observations.append({"time": float(end), "clock": row["clock"], "values": observed})
        missing = [
            check.model_dump() | {"status": "not-run"}
            for check in case.checks
            if check.id not in evaluated
        ]
        asserted = {check.signal for check in case.checks}
        supplied = {identity for event in case.events for identity in event.inputs}
        passed = (
            all(row["passed"] for row in comparisons)
            and not missing
            and (fault["passed"] if fault else case.expected_fault is None)
        )
        cases.append(
            {
                "id": case.id,
                "name": case.name,
                "status": "passed" if passed else "failed",
                "comparisons": comparisons,
                "not_run": missing,
                "fault": fault,
                "expected_fault_missing": case.expected_fault is not None and fault is None,
                "successful_scans": successful_scans,
                "attempted_scans": successful_scans + (1 if fault else 0),
                "observations": observations,
                "coverage": {
                    "asserted_signals": sorted(asserted),
                    "unasserted_signals": sorted(signal_ids - asserted),
                    "asserted_outputs": sorted(output_ids & asserted),
                    "unasserted_outputs": sorted(output_ids - asserted),
                    "supplied_input_signals": sorted(supplied),
                    "inputs_using_only_defaults": sorted(input_ids - supplied),
                    "initial_input_defaults": {
                        n.id: {
                            "value": n.params.get("default", BLOCKS["Input"].parameters["default"]),
                            "quality": "good",
                            "unit": n.unit,
                        }
                        for n in program.nodes
                        if n.kind == "Input"
                    },
                    "declared_conditions": [event.model_dump() for event in case.events],
                    "meaning": SEMANTICS["coverage"],
                },
            }
        )
    report = {
        "format": "bms.graph-conformance-report",
        "version": 1,
        "program_sha256": program.digest(),
        "program_id": program.id,
        "program_revision": program.revision,
        "suite_sha256": digest(suite.model_dump(mode="json")),
        "suite_name": suite.name,
        "target_declaration": program.target.model_dump(),
        "signal_contract": suite.signals,
        "execution_profile_sha256": PROFILE_SHA,
        "semantics": SEMANTICS,
        "scope": SCOPE,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if all(row["status"] == "passed" for row in cases) else "failed",
        "cases": cases,
        "native_execution": False,
        "controller_writes": False,
        "certification": False,
    }
    report["content_sha256"] = digest(report)
    if len(canonical(report)) > MAX_REPORT:
        raise ValueError(
            "Conformance result exceeds4MiB; reduce checks/conditions or split the suite."
        )
    return report


class ProgramBody(StrictModel):
    program: Program


class SuiteBody(ProgramBody):
    suite: dict


class SaveBody(SuiteBody):
    id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    expected_revision: int = Field(ge=0, strict=True)


class DeleteBody(ProgramBody):
    expected_revision: int = Field(ge=1, strict=True)


class ImportBody(ProgramBody):
    text: str = Field(max_length=MAX_BYTES)


def parse_document(text):
    try:
        size = len(text.encode())
    except UnicodeError as exc:
        raise ValueError("Conformance import requires valid Unicode JSON.") from exc
    if size > MAX_BYTES:
        raise ValueError("Conformance import exceeds2MiB.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Conformance JSON contains duplicate fields.")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Conformance JSON requires finite values.")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Conformance import must be bounded valid JSON.") from exc


class ConformancePlans:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS conformance_suites(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,source TEXT NOT NULL,name TEXT NOT NULL,updated TEXT NOT NULL,content BLOB NOT NULL,sha256 TEXT NOT NULL)"
            )

    def list(self, program):
        with self.store.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,revision,name,updated,sha256 FROM conformance_suites WHERE source=? ORDER BY updated DESC,id LIMIT ?",
                    (program.digest(), MAX_PLANS),
                )
            ]

    def load(self, program, key):
        if len(key) != 32 or any(char not in "0123456789abcdef" for char in key):
            raise ValueError("Invalid conformance suite identifier.")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM conformance_suites WHERE id=?", (key,)).fetchone()
        if row is None or row["source"] != program.digest():
            raise ValueError("Saved conformance suite does not match this source program.")
        content = bytes(row["content"])
        if len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise ValueError("Saved conformance suite integrity check failed.")
        suite = validate_suite(program, parse_document(content.decode())).model_dump(mode="json")
        return {"id": key, "revision": row["revision"], "sha256": row["sha256"], "suite": suite}

    def save(self, body):
        suite = validate_suite(body.program, body.suite).model_dump(mode="json")
        raw, stamp = canonical(suite), datetime.now(UTC).isoformat()
        key = body.id or secrets.token_hex(16)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                "SELECT source,revision,length(content) AS bytes FROM conformance_suites WHERE id=?",
                (key,),
            ).fetchone()
            revision = prior["revision"] if prior else 0
            if (
                body.expected_revision != revision
                or (prior and prior["source"] != body.program.digest())
                or (body.id is None and body.expected_revision != 0)
                or (body.id is not None and prior is None)
            ):
                raise Conflict("Conformance suite changed; reopen the saved revision.")
            count, size = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(length(content)),0) FROM conformance_suites"
            ).fetchone()
            if (prior is None and count >= MAX_PLANS) or size - (
                prior["bytes"] if prior else 0
            ) + len(raw) > MAX_STORAGE:
                raise ValueError(
                    "Conformance saved suite capacity reached; export/remove existing suites first."
                )
            db.execute(
                "INSERT INTO conformance_suites VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,name=excluded.name,updated=excluded.updated,content=excluded.content,sha256=excluded.sha256",
                (
                    key,
                    revision + 1,
                    body.program.digest(),
                    suite["name"],
                    stamp,
                    raw,
                    hashlib.sha256(raw).hexdigest(),
                ),
            )
        # Return this committed revision, even if another writer advances it immediately.
        return {
            "id": key,
            "revision": revision + 1,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "suite": suite,
        }

    def delete(self, program, key, revision):
        self.load(program, key)
        with self.store.connect() as db:
            cursor = db.execute(
                "DELETE FROM conformance_suites WHERE id=? AND revision=? AND source=?",
                (key, revision, program.digest()),
            )
            if cursor.rowcount != 1:
                raise Conflict("Conformance suite changed; reopen before deleting.")
        return {"deleted": key}


def conformance_router(service):
    router = APIRouter(prefix="/api/conformance")

    @router.post("/catalog")
    def catalog(body: ProgramBody):
        return {
            "template": template(body.program),
            "saved": service.list(body.program),
            "scope": SCOPE,
            "semantics": SEMANTICS,
            "limits": {
                "cases": 20,
                "scans": MAX_STEPS,
                "block_evaluations": MAX_WORK,
                "suite_bytes": MAX_BYTES,
                "report_bytes": MAX_REPORT,
            },
        }

    @router.post("/validate")
    def validate(body: SuiteBody):
        suite = validate_suite(body.program, body.suite).model_dump(mode="json")
        return {"suite": suite, "suite_sha256": digest(suite)}

    @router.post("/import")
    def imported(body: ImportBody):
        return {
            "suite": validate_suite(body.program, parse_document(body.text)).model_dump(mode="json")
        }

    @router.post("/export")
    def exported(body: SuiteBody):
        suite = validate_suite(body.program, body.suite).model_dump(mode="json")
        return Response(
            canonical(suite) + b"\n",
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="graph-conformance-suite.json"'},
        )

    @router.post("/run")
    def run(body: SuiteBody):
        return Response(
            canonical(run_suite(body.program, body.suite)) + b"\n", media_type="application/json"
        )

    @router.post("/save")
    def save(body: SaveBody):
        return service.save(body)

    @router.post("/saved/{key}")
    def load(key: str, body: ProgramBody):
        return service.load(body.program, key)

    @router.post("/saved/{key}/delete")
    def delete(key: str, body: DeleteBody):
        return service.delete(body.program, key, body.expected_revision)

    return router
