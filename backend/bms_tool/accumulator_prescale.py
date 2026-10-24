"""Exact offline pulse arithmetic; native observations never become raw pulse counts."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import secrets
import threading
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Request, Response, UploadFile
from pydantic import Field, ValidationError, field_validator, model_validator

from .models import StrictModel

UINT32 = 2**32 - 1
MAX_BYTES = 256 * 1024
SCOPE = (
    "Offline integer pulse-batch review only. Explicit initial PV and numerator remainder are "
    "operator declarations, never inferred from native PV. No hardware pulses, debounce, rollover, "
    "restart/persistence, publication timing, COV, scale application, native compiler or field writes. "
    "Exceeding the declared PV maximum stops before that batch; physical wrap/overflow is unresolved."
)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


PROFILE = {
    "id": "accumulator-prescale-review/1",
    "arithmetic": "For each accepted batch: numerator = pulses * multiplier + previous_remainder; increment, remainder = divmod(numerator, modulo_divide); PV = previous_PV + increment.",
    "overflow_policy": "Stop before a batch that exceeds declared maximum PV; no wrap or partial-batch interpretation.",
    "limits": {
        "batches": 256,
        "unsigned_max": str(UINT32),
        "json_bytes": MAX_BYTES,
        "session_reviews": 8,
    },
    "sources": [
        {
            "title": "Controller Tool Help",
            "document": "LIT-12011147",
            "release": "18.0",
            "pdf_pages": [1582, 1583, 1584, 1585],
            "sha256": "68935362c85cb1879dc033cc701115e8ea7c4ecb26748f21a9ceaf0454f82903",
            "url": "https://docs.johnsoncontrols.com/bas/r/Metasys/en-US/Controller-Tool-Help/18.0",
            "applicability": "Release18 documentation: Field Controller main code5.0+ for Accumulator. Not a model/firmware/package acceptance matrix.",
        }
    ],
    "source_policy": "Native property evidence is a sequential read snapshot. Self seals identify content, not manufacturer authenticity or current configuration.",
    "scope": SCOPE,
}
PROFILE["sha256"] = digest(PROFILE)
Hash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[
    str, Field(strict=True, min_length=1, max_length=10, pattern=r"^(0|[1-9][0-9]*)$")
]


class Batch(StrictModel):
    pulses: Count

    @field_validator("pulses")
    @classmethod
    def bound(cls, value):
        if int(value) > UINT32:
            raise ValueError("A pulse batch must fit Unsigned32.")
        return value


class Configuration(StrictModel):
    multiplier: Count = "1"
    modulo_divide: Count = "1"
    initial_pv: Count = "0"
    initial_remainder: Count = "0"
    max_pv: Count = str(UINT32)
    batches: list[Batch] = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def coherent(self):
        values = {
            name: int(getattr(self, name))
            for name in ("multiplier", "modulo_divide", "initial_pv", "initial_remainder", "max_pv")
        }
        if any(value > UINT32 for value in values.values()):
            raise ValueError("Prescale and state declarations must fit Unsigned32.")
        if not values["modulo_divide"]:
            raise ValueError("Modulo divide must be greater than zero.")
        if values["initial_remainder"] >= values["modulo_divide"]:
            raise ValueError("Initial numerator remainder must be smaller than modulo divide.")
        if values["initial_pv"] > values["max_pv"]:
            raise ValueError("Initial PV exceeds the declared maximum.")
        return self


class SourceRef(StrictModel):
    report_id: str = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    object_id: str = Field(strict=True, pattern=r"^accumulator,(0|[1-9][0-9]{0,6})$")


class ReviewRequest(StrictModel):
    profile_sha256: Hash
    configuration: Configuration
    source: SourceRef | None = None


class ReviewKey(StrictModel):
    id: str = Field(strict=True, pattern=r"^[0-9a-f]{32}$")
    content_sha256: Hash


def calculate(configuration):
    config = Configuration.model_validate(configuration)
    multiplier, divisor = int(config.multiplier), int(config.modulo_divide)
    pv, remainder = int(config.initial_pv), int(config.initial_remainder)
    maximum = int(config.max_pv)
    rows, stopped = [], False
    for index, batch in enumerate(config.batches, 1):
        row = {
            "batch": index,
            "pulses": batch.pulses,
            "prior_pv": str(pv),
            "prior_remainder": str(remainder),
        }
        if stopped:
            row["status"] = "not_evaluated_after_limit"
        else:
            numerator = int(batch.pulses) * multiplier + remainder
            increment, next_remainder = divmod(numerator, divisor)
            candidate = pv + increment
            row.update(
                numerator=str(numerator),
                increment=str(increment),
                candidate_pv=str(candidate),
                candidate_remainder=str(next_remainder),
            )
            stopped = candidate > maximum
            row["status"] = "declared_limit_exceeded" if stopped else "accepted"
            if not stopped:
                pv, remainder = candidate, next_remainder
        row.update(retained_pv=str(pv), retained_remainder=str(remainder))
        rows.append(row)
    return {
        "status": "stopped_at_limit" if stopped else "complete",
        "complete": not stopped,
        "rows": rows,
        "final_pv": str(pv),
        "final_remainder": str(remainder),
    }


def strict_json(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Pulse review JSON exceeds256KiB.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate pulse-review JSON keys are refused.")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite pulse-review JSON is refused.")

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
        canonical(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError, OverflowError) as exc:
        raise ValueError("Malformed pulse-review UTF-8 JSON.") from exc


class PrescaleReviews:
    def __init__(self, point_status):
        self.points = point_status
        self.reviews = OrderedDict()
        self.lock = threading.RLock()

    def native_source(self, reference):
        if reference is None:
            return None
        report = self.points.detail(reference.report_id)
        item = next(
            (item for item in report["objects"] if item["object"] == reference.object_id), None
        )
        if (
            not report["identity_verified"]
            or item is None
            or not item["identity_verified"]
            or "accumulator_metering" not in item
        ):
            raise ValueError(
                "Select an identity-verified Accumulator with explicit metering metadata reads."
            )
        return {
            "report_id": report["id"],
            "report_evidence_sha256": report["evidence_sha256"],
            "profile": report["profile"],
            "target": report["target"],
            "connector_config": report["connector_config"],
            "started_at": report["started_at"],
            "finished_at": report["finished_at"],
            "object_id": item["object"],
            "properties": copy.deepcopy(item["properties"]),
            "meaning": "Original sequential native observation snapshot; simulation state and chosen settings are independent declarations. No current-state or controller acceptance proof.",
        }

    def review(self, request):
        if request.profile_sha256 != PROFILE["sha256"]:
            raise ValueError("Pulse-review profile changed; reload its rules before review.")
        configuration = request.configuration.model_dump()
        report = {
            "format": "bms.accumulator-prescale-review/1",
            "id": secrets.token_hex(16),
            "reviewed_at": datetime.now(UTC).isoformat(),
            "profile": copy.deepcopy(PROFILE),
            "configuration": configuration,
            "configuration_sha256": digest(configuration),
            "native_source": self.native_source(request.source),
            "simulation": calculate(configuration),
            "scope": SCOPE,
            "field_writes": False,
            "native_execution": False,
        }
        report["content_sha256"] = digest(report)
        raw = canonical(report) + b"\n"
        if len(raw) > MAX_BYTES:
            raise ValueError("Pulse-review report exceeds256KiB; no review retained.")
        with self.lock:
            self.reviews[report["id"]] = raw
            while len(self.reviews) > 8:
                self.reviews.popitem(last=False)
        return report

    def get(self, key):
        with self.lock:
            raw = self.reviews.get(key.id)
        if raw is None:
            raise ValueError("Pulse review expired; review the configuration again.")
        report = json.loads(raw)
        if report["content_sha256"] != key.content_sha256:
            raise ValueError("Pulse review source differs; review the current configuration.")
        return raw, report

    @staticmethod
    def import_configuration(raw):
        report = strict_json(raw)
        if type(report) is not dict or report.get("format") != "bms.accumulator-prescale-review/1":
            raise ValueError("Import requires a sealed pulse-review report.")
        supplied = report.pop("content_sha256", None)
        if supplied != digest(report) or canonical(report.get("profile")) != canonical(PROFILE):
            raise ValueError("Pulse review content/profile seal failed.")
        configuration = Configuration.model_validate(report.get("configuration"))
        if report.get("configuration_sha256") != digest(configuration.model_dump()) or canonical(
            report.get("simulation")
        ) != canonical(calculate(configuration)):
            raise ValueError("Pulse review arithmetic/source proof failed.")
        # Imported native observations remain in the original downloadable file.
        # New review gets no retained native identity by trusting a self seal.
        return {
            "configuration": configuration.model_dump(),
            "file_sha256": hashlib.sha256(raw).hexdigest(),
            "native_source_reused": False,
            "note": "Configuration only. Original native observations remain in your source file; new review is offline and unbound to a live Device.",
        }


async def body(request, model):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BYTES:
            raise ValueError("Pulse review request exceeds256KiB.")
        raw.extend(chunk)
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise ValueError("Pulse review requests require application/json.")
    try:
        return model.model_validate(strict_json(bytes(raw)))
    except ValidationError as exc:
        raise ValueError(
            "Invalid pulse-review request: "
            + json.dumps(exc.errors(include_input=False, include_context=False))[:3000]
        ) from None


def prescale_router(service):
    router = APIRouter(prefix="/api/accumulator-prescale")

    @router.get("/profile")
    def profile():
        return copy.deepcopy(PROFILE)

    @router.post("/review")
    async def review(request: Request):
        return service.review(await body(request, ReviewRequest))

    @router.post("/import")
    async def import_file(file: Annotated[UploadFile, File()]):
        try:
            return service.import_configuration(await file.read(MAX_BYTES + 1))
        except ValidationError:
            raise ValueError("Imported pulse configuration is invalid.") from None

    @router.post("/export/{kind}")
    async def export(kind: Literal["json", "csv"], request: Request):
        raw, report = service.get(await body(request, ReviewKey))
        if kind == "csv":
            output = io.StringIO(newline="")
            fields = [
                "batch",
                "pulses",
                "prior_pv",
                "prior_remainder",
                "numerator",
                "increment",
                "candidate_pv",
                "candidate_remainder",
                "status",
                "retained_pv",
                "retained_remainder",
            ]
            writer = csv.DictWriter(
                output,
                fieldnames=["review_content_sha256", "configuration_sha256", "profile_sha256"]
                + fields,
            )
            writer.writeheader()
            for row in report["simulation"]["rows"]:
                writer.writerow(
                    {
                        "review_content_sha256": report["content_sha256"],
                        "configuration_sha256": report["configuration_sha256"],
                        "profile_sha256": PROFILE["sha256"],
                        **row,
                    }
                )
            raw = output.getvalue().encode()
        return Response(
            raw,
            media_type="application/json" if kind == "json" else "text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="pulse-review-{report["id"]}.{kind}"',
                "X-File-SHA256": hashlib.sha256(raw).hexdigest(),
            },
        )

    return router
