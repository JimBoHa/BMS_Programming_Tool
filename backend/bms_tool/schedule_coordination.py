"""Authored weekly occupancy composition; never a native G36 application encoder."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Response
from pydantic import Field, model_validator

from .calendar_schedule import compile_schedule
from .engine import Engine, validate
from .models import Edge, Node, Program, StrictModel
from .program_source import SourceMode, source_response

DAY = 1440
WEEK = DAY * 7
MAX_GROUPS = 8
MAX_CLOCKS = 128
MAX_NODES = 1000
SOURCE = {
    "title": "Guideline 36 Sample Archive Application Note",
    "document": "LIT-12014121",
    "edition": "15",
    "pdf_pages": [28, 29, 30],
    "sha256": "6ba1a3963dc71de99a7a5192a7c1aa61487e0150d3902e34fc5a5bc34dd7e422",
    "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Guideline-36-Sample-Archive-Application-Note/15",
    "scope": "PDF 30 qualifies per-group schedules, an earlier pre-trigger/default 180 minutes and any-group AHU occupancy. End retention, cyclic union, all-day and DST policies below are authored Studio behavior, not recovered native G36 semantics.",
}
GAPS = [
    "dated exceptions and their pre-trigger policy",
    "time-to-occupancy countdown, thermal warmup/cooldown and G36 operating modes",
    "native occupancy MV codes, Global Data objects and zone/AHU target associations",
    "native CAF/SCT archive generation, controller allocation, compilation and transfer",
    "physical equipment acceptance and complete G36/Title24 certification",
]
PROFILE = {
    "profile": "studio-weekly-zone-group-occupancy/1",
    "source": SOURCE,
    "semantics": {
        "occupied": "Half-open occupied intervals retain the declared end; overnight intervals belong to the selected START weekday. Equal start/end in window mode is empty. All-day explicitly means 24 hours; disabled or no selected days is empty.",
        "pre_or_occupied": "Expand each nonempty occupied interval [start,end) to [start-lead,end), preserving its occupied end. Union all expansions over the cyclic 10,080-minute local week. Never shift the end or infer an elapsed countdown.",
        "pre_only": "pre_or_occupied AND NOT occupied after weekly union.",
        "ahu": "OR of original group occupied outputs only; pre-only does not set AHU occupied.",
        "timezone": "Each group uses its explicit IANA local wall clock. Spring gaps never occur; repeated fold minutes evaluate pointwise in both folds, possibly separated by a real-time off gap. Elapsed lead can differ from nominal wall-clock lead.",
        "lowering": "Disjoint local-day segments use existing core Schedule/Or nodes. A full local day uses 00:00–12:00 plus 12:00–00:00 on its START weekday, never an equal-time Schedule. Named-zone native source requires host calendar/value-valid bindings; no autonomous controller calendar is inferred.",
        "choices": "New generator choice evidence normalizes integral scan_seconds to an integer. Existing Program canonical/source/evidence rules are unchanged.",
        "links": "This Program composes internally in one scan. Connecting its Outputs through shared-system simulation adds the existing explicit previous-cycle link delay.",
        "identifiers": "Generated scopes use positional zg1 through zg8 in declared group order. Exact group IDs and output mappings remain in evidence; labels or suffix-like IDs never infer native symbols.",
    },
    "limits": {
        "groups": MAX_GROUPS,
        "lead_minutes": [0, DAY],
        "clocks": MAX_CLOCKS,
        "nodes": MAX_NODES,
    },
    "gaps": GAPS,
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE_SHA = digest(PROFILE)


def visible(value, field):
    if not value.strip() or not all(character.isprintable() for character in value):
        raise ValueError(field + " requires visible printable text.")


class Group(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=160)
    timezone: str = Field(min_length=1, max_length=128)
    mode: Literal["window", "all-day", "disabled"]
    days: list[Annotated[int, Field(strict=True, ge=0, le=6)]] = Field(max_length=7)
    start: str = Field(max_length=5)
    end: str = Field(max_length=5)
    lead_minutes: Annotated[int, Field(strict=True, ge=0, le=DAY)] = 180

    @model_validator(mode="after")
    def coherent(self):
        visible(self.label, "Group label")
        if len(set(self.days)) != len(self.days):
            raise ValueError("Weekdays must be unique; Monday=0, Sunday=6.")
        compile_schedule(
            {"start": self.start, "end": self.end, "days": self.days, "timezone": self.timezone}
        )
        return self


class Choices(StrictModel):
    project_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(min_length=1, max_length=200)
    ahu_label: str = Field(min_length=1, max_length=140)
    scan_seconds: Annotated[float, Field(strict=True, ge=0.01, le=60)] = 1.0
    groups: list[Group] = Field(min_length=1, max_length=MAX_GROUPS)

    @model_validator(mode="after")
    def coherent(self):
        visible(self.name, "Program name")
        visible(self.ahu_label, "AHU label")
        if len({group.id for group in self.groups}) != len(self.groups):
            raise ValueError("Zone group identifiers must be unique.")
        return self


class PreviewRequest(StrictModel):
    choices: Choices
    clocks: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(
        default_factory=list, max_length=MAX_CLOCKS
    )

    @model_validator(mode="after")
    def valid_clocks(self):
        for clock in self.clocks:
            parse_clock(clock)
        return self


def parse_clock(value):
    try:
        if "T" not in value or not value.endswith(("Z", "+00:00")):
            raise ValueError
        clock = datetime.fromisoformat(value)
        if (
            clock.tzinfo is None
            or clock.utcoffset() is None
            or clock.utcoffset().total_seconds() != 0
        ):
            raise ValueError
        return clock.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError("Evaluation clocks must be explicit valid UTC ISO8601 instants.") from exc


def choice_document(choices):
    result = choices.model_dump()
    if choices.scan_seconds.is_integer():
        result["scan_seconds"] = int(choices.scan_seconds)
    return result


def minute(text):
    hour, part = map(int, text.split(":"))
    return hour * 60 + part


def text_minute(value):
    return f"{value // 60:02d}:{value % 60:02d}"


def weekly_minutes(group, lead=0):
    """Exact finite local-week union; no clocks, DST arithmetic or inferred end."""
    result = bytearray(WEEK)
    if group.mode == "disabled":
        return result
    start = 0 if group.mode == "all-day" else minute(group.start)
    duration = DAY if group.mode == "all-day" else (minute(group.end) - start) % DAY
    if duration == 0:
        return result
    for day in group.days:
        begin = day * DAY + start - lead
        for index in range(begin, begin + duration + lead):
            result[index % WEEK] = 1
    return result


def windows(active):
    """Lower a weekly union to disjoint per-day core windows; no24:00/equal times."""
    if not isinstance(active, bytearray) or len(active) != WEEK:
        raise ValueError("Expected one bounded local-week union.")
    combined = {}
    for day in range(7):
        offset, index = day * DAY, 0
        while index < DAY:
            if not active[offset + index]:
                index += 1
                continue
            start = index
            while index < DAY and active[offset + index]:
                index += 1
            pieces = (
                [(0, DAY // 2), (DAY // 2, DAY)]
                if start == 0 and index == DAY
                else [(start, index)]
            )
            for low, high in pieces:
                key = text_minute(low), text_minute(high % DAY)
                combined.setdefault(key, []).append(day)
    return [
        {"start": start, "end": end, "days": days}
        for (start, end), days in sorted(combined.items())
    ]


def generate(choices):
    nodes, edges, summaries = [], [], []

    def node(identifier, kind, label, params=None):
        index = len(nodes)
        nodes.append(
            Node(
                id=identifier,
                kind=kind,
                label=label,
                params=params or {},
                value_type="boolean",
                x=40 + 300 * (index % 5),
                y=60 + 160 * (index // 5),
            )
        )
        return identifier

    def edge(source, target, port="in"):
        edges.append(
            Edge(id=f"{source}_{target}_{port}", source=source, target=target, target_port=port)
        )

    def union(prefix, label, sources):
        if not sources:
            return node(prefix + "_empty", "Constant", label + " is empty", {"value": False})
        result = sources[0]
        for index, source in enumerate(sources[1:]):
            target = node(prefix + f"_or{index}", "Or", label + " union")
            edge(result, target, "a")
            edge(source, target, "b")
            result = target
        return result

    def output(identifier, label, source):
        node(identifier, "Output", label)
        edge(source, identifier)
        return identifier

    occupied_outputs = []
    for group_index, group in enumerate(choices.groups, start=1):
        prefix = f"zg{group_index}"
        original = windows(weekly_minutes(group))
        expanded = windows(weekly_minutes(group, group.lead_minutes))
        unions = {}
        for purpose, entries in (("occupied", original), ("pre", expanded)):
            sources = [
                node(
                    prefix + f"_{purpose}_window{i}",
                    "Schedule",
                    group.label + " " + purpose + " local window",
                    row | {"timezone": group.timezone},
                )
                for i, row in enumerate(entries)
            ]
            unions[purpose] = union(prefix + "_" + purpose, group.label + " " + purpose, sources)
        occupied = output(
            prefix + "_occupied", group.label + " scheduled occupied", unions["occupied"]
        )
        expanded_out = output(
            prefix + "_pre_or_occupied", group.label + " pre-or-occupied union", unions["pre"]
        )
        inverted = node(prefix + "_not_occupied", "Not", group.label + " is not occupied")
        edge(unions["occupied"], inverted)
        pre_only = node(prefix + "_pre_only_gate", "And", group.label + " pre-only interval")
        edge(unions["pre"], pre_only, "a")
        edge(inverted, pre_only, "b")
        pre_out = output(prefix + "_pre_only", group.label + " pre-only, not a countdown", pre_only)
        occupied_outputs.append(occupied)
        summaries.append(
            {
                "id": group.id,
                "label": group.label,
                "timezone": group.timezone,
                "occupied_windows": original,
                "pre_windows": expanded,
                "occupied_week_minutes": sum(weekly_minutes(group)),
                "pre_week_minutes": sum(weekly_minutes(group, group.lead_minutes)),
                "outputs": {
                    "occupied": occupied,
                    "pre_or_occupied": expanded_out,
                    "pre_only": pre_out,
                },
                "inactive_choices": ["start", "end"] if group.mode != "window" else [],
            }
        )
    output(
        "ahu_occupied",
        choices.ahu_label + " occupied from original group schedules only",
        union("ahu", choices.ahu_label, occupied_outputs),
    )
    if len(nodes) > MAX_NODES:
        raise ValueError("Generated schedule composition exceeds its 1,000-node bound.")
    evidence = {
        "profile_sha256": PROFILE_SHA,
        "source": SOURCE,
        "choices": choice_document(choices),
        "choices_sha256": digest(choice_document(choices)),
        "unimplemented": GAPS,
        "groups": summaries,
    }
    program = Program(
        id=choices.project_id,
        name=choices.name,
        scan_seconds=choices.scan_seconds,
        description="Authored weekly zone-group occupancy/pre-start union. Original occupied end retained. Wall-clock lead is not an elapsed countdown or native G36 operating mode. No field bindings or deployment verified.",
        nodes=nodes,
        edges=edges,
        metadata={
            "schedule_coordination": evidence,
            "native_deployment_verified": False,
            "compliance": "Uncertified authored weekly foundation",
        },
    )
    return program, summaries


def preview(body):
    program, summaries = generate(body.choices)
    issues = [row.model_dump() for row in validate(program)]
    evaluation = []
    for requested in body.clocks:
        clock = parse_clock(requested)
        row = Engine(program).step(clock=clock)
        evaluation.append(
            {"requested_clock": requested, "clock": clock.isoformat(), "outputs": row["outputs"]}
        )
    return {
        "format": "bms.schedule-coordination-preview",
        "version": 1,
        "profile": PROFILE,
        "profile_sha256": PROFILE_SHA,
        "choices": choice_document(body.choices),
        "choices_sha256": digest(choice_document(body.choices)),
        "program": program.model_dump(mode="json"),
        "program_sha256": program.digest(),
        "issues": issues,
        "can_create": not any(row["level"] == "error" for row in issues),
        "groups": summaries,
        "evaluation": evaluation,
        "native_compile": False,
        "controller_writes": False,
    }


def schedule_coordination_router():
    router = APIRouter(prefix="/api/schedule-coordination")

    @router.get("/catalog")
    def catalog():
        return {
            "profile": PROFILE,
            "profile_sha256": PROFILE_SHA,
            "limits": PROFILE["limits"],
            "defaults": {
                "project_id": "new-zone-group-project",
                "name": "Zone-group occupancy",
                "ahu_label": "AHU",
                "scan_seconds": 1,
                "groups": [
                    {
                        "id": "group1",
                        "label": "Zone group 1",
                        "timezone": "",
                        "mode": "",
                        "days": [0, 1, 2, 3, 4],
                        "start": "08:00",
                        "end": "18:00",
                        "lead_minutes": 180,
                    }
                ],
            },
        }

    @router.post("/preview")
    def review(body: PreviewRequest, source_transport: SourceMode = False):
        return source_response(preview(body), source_transport)

    @router.post("/export")
    def export(body: PreviewRequest):
        content = canonical(preview(body))
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="zone-group-schedule-review.json"',
                "X-File-SHA256": hashlib.sha256(content).hexdigest(),
            },
        )

    return router
