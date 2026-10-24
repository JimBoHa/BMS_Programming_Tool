"""Local persisted hardware surveys and read-only archive jobs for the web UI.

Plans describe work for a compatible native engineering tool. This service has
no application compiler, WriteProperty, firmware, or controller activation path.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import Field

from .device_details import DeviceDetails
from .hardware_survey import (
    HardwareSurvey,
    HardwareSurveyRequest,
    analyze_archive,
    enrich_report,
    occupancy,
    relocation_plan,
    validate_report,
)
from .hardware_target import HardwareTargetRequest, serial_identity
from .model_transport import ModelQualification, ModelReviewRequest
from .model_transport import catalog as model_transport_catalog
from .model_transport import observe as observe_model_transport
from .model_transport import review as review_model_transport
from .models import StrictModel

MAX_DOCUMENT = 8 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_REPORTS = 32
MAX_ARCHIVES = 16
MAX_JOBS = 32
MAX_STORAGE = 128 * 1024 * 1024


def now():
    return datetime.now(UTC).isoformat()


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise ValueError("Invalid hardware workbench identifier.")
    return value


def bounded_json(raw):
    if len(raw) > MAX_DOCUMENT:
        raise ValueError("Hardware document exceeds 8 MiB.")
    try:
        value = json.loads(
            raw,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON value.")),
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid hardware JSON document.") from exc
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > 150000 or depth > 32:
            raise ValueError("Hardware JSON exceeds its structure budget.")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValueError("Nonfinite hardware value.")
    return value


class ReportArchiveRequest(StrictModel):
    report_id: str
    archive_id: str


class CaptureArchiveRequest(StrictModel):
    capture_id: str


class ReadArchiveRequest(StrictModel):
    report_id: str
    file_object: str | None = Field(default=None, max_length=80)


class WorkbenchSurveyRequest(HardwareSurveyRequest):
    model_qualification: ModelQualification | None = None


class RelocationRequest(StrictModel):
    report_id: str
    source_object: str = Field(min_length=1, max_length=80)
    destination_sa_mac: int | None = Field(default=None, ge=4, le=127, strict=True)
    destination_slot: int = Field(ge=1, le=64, strict=True)


class SensorChannel(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    sa_mac: int | None = Field(default=None, ge=4, le=127, strict=True)
    slot: int = Field(ge=1, le=64, strict=True)
    signal_low: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
    signal_high: float = Field(default=5, gt=0, le=10, allow_inf_nan=False)
    engineering_low: float = Field(allow_inf_nan=False)
    engineering_high: float = Field(allow_inf_nan=False)
    units: str = Field(min_length=1, max_length=40)


class SensorRelocation(StrictModel):
    source_object: str = Field(min_length=1, max_length=80)
    destination_sa_mac: int | None = Field(default=None, ge=4, le=127, strict=True)
    destination_slot: int = Field(ge=1, le=64, strict=True)


class SensorPlanRequest(StrictModel):
    report_id: str
    relocation: SensorRelocation | None = None
    channels: list[SensorChannel] = Field(min_length=1, max_length=8)


class HardwareWorkbench:
    def __init__(self, bacnet, store, files):
        self.bacnet, self.store, self.files = bacnet, store, files
        self.surveys = HardwareSurvey(bacnet, store)
        self.directory = Path(store.directory) / "hardware-workbench"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.jobs = {}
        self.tasks = {}
        self.closed = False
        for path in sorted(self.directory.glob("job-*.json"))[-MAX_JOBS:]:
            job = self._load("job", path.stem.removeprefix("job-"))
            if job["status"] in ("queued", "running"):
                job.update(
                    status="interrupted",
                    finished_at=now(),
                    error="Server stopped; the read was not resumed.",
                )
                self._write("job", job["id"], job)
            self.jobs[job["id"]] = job

    def _path(self, kind, key):
        return self.directory / f"{kind}-{identifier(key)}.json"

    def _write(self, kind, key, value):
        path = self._path(kind, key)
        encoded = canonical({"sha256": digest(value), "data": value})
        if len(encoded) > MAX_DOCUMENT:
            raise ValueError("Saved hardware evidence exceeds 8 MiB.")
        quota = {"report": MAX_REPORTS, "archive": MAX_ARCHIVES, "job": MAX_JOBS}[kind]
        if not path.exists() and len(list(self.directory.glob(f"{kind}-*.json"))) >= quota:
            raise ValueError(
                f"Hardware {kind} retention limit reached; remove an older saved item first."
            )
        used = sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file())
        previous_size = path.stat().st_size if path.is_file() else 0
        if used - previous_size + len(encoded) > MAX_STORAGE:
            raise ValueError("Hardware evidence storage budget reached.")
        temporary = self.directory / (".pending-" + secrets.token_hex(16))
        try:
            with temporary.open("xb") as stream:
                temporary.chmod(0o600)
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self, kind, key):
        path = self._path(kind, key)
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DOCUMENT:
                raise ValueError("Hardware evidence must be a bounded regular file.")
            wrapper = bounded_json(path.read_bytes())
        except FileNotFoundError as exc:
            raise ValueError(f"Saved hardware {kind} was not found.") from exc
        if (
            not isinstance(wrapper, dict)
            or set(wrapper) != {"sha256", "data"}
            or digest(wrapper["data"]) != wrapper["sha256"]
        ):
            raise ValueError("Saved hardware evidence failed its integrity check.")
        return wrapper["data"]

    def report(self, key):
        return self._load("report", key)

    def archive(self, key):
        return self._load("archive", key)

    def save_report(self, report, *, origin):
        result = validate_report(bounded_json(canonical(report)))
        if not isinstance(result, dict) or result.get("profile") != "bacnet-hardware-survey/1":
            raise ValueError("Import a BMS Studio hardware-survey JSON report.")
        if not isinstance(result.get("identity"), dict) or not isinstance(
            result.get("inventory"), dict
        ):
            raise ValueError("Hardware report requires identity and inventory evidence.")
        target = result.get("target")
        if not isinstance(target, dict):
            raise ValueError("Hardware report requires an explicit target.")
        HardwareSurveyRequest.model_validate(
            {
                key: target[key]
                for key in ("transport", "address", "device", "router", "dnet")
                if key in target
            }
        )
        inputs = result.get("inputs")
        if (
            not isinstance(inputs, list)
            or len(inputs) > 1024
            or any(not isinstance(row, dict) for row in inputs)
        ):
            raise ValueError("Hardware report has an invalid input list.")
        objects = [row.get("object") for row in inputs]
        if any(
            not isinstance(obj, str)
            or not re.fullmatch(r"(?:analog|binary|multi-state)-input,\d+", obj)
            for obj in objects
        ) or len(set(objects)) != len(objects):
            raise ValueError("Hardware report inputs need unique AI/BI object identities.")
        # Imported reports remain source-labelled. No uploaded plan can acquire an
        # executable path; analysis rederives capacities and candidate occupancy.
        result.update(
            id=secrets.token_hex(16),
            saved_at=now(),
            origin=origin,
            imported=origin == "uploaded-report" or result.get("imported") is True,
            native_apply_supported=False,
        )
        result["content_sha256"] = digest(
            {
                key: val
                for key, val in result.items()
                if key not in ("content_sha256", "id", "saved_at")
            }
        )
        self._write("report", result["id"], result)
        self.store.record(
            "hardware.report.saved",
            {"id": result["id"], "origin": origin, "sha256": result["content_sha256"]},
        )
        return result

    def import_report(self, data):
        return self.save_report(bounded_json(data), origin="uploaded-report")

    def import_archive(self, data, filename, *, origin=None):
        if not data or len(data) > MAX_SOURCE:
            raise ValueError("Hardware archive requires 1 byte through 2 MiB.")
        evidence = analyze_archive(data, filename=Path(filename or "Archive.moi").name[:200])
        evidence.update(
            id=secrets.token_hex(16), saved_at=now(), origin=origin or {"kind": "uploaded-file"}
        )
        # Publish exact source bytes before the metadata commits the archive.
        # Failed writes cannot leave a saved archive with a missing/partial source.
        path = self.directory / ("source-" + evidence["id"] + ".bin")
        temporary = self.directory / (".pending-source-" + secrets.token_hex(16))
        if (
            sum(p.stat().st_size for p in self.directory.iterdir() if p.is_file()) + len(data)
            > MAX_STORAGE
        ):
            raise ValueError("Hardware evidence storage budget reached.")
        try:
            with temporary.open("xb") as stream:
                temporary.chmod(0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._write("archive", evidence["id"], evidence)
        except (ValueError, OSError):
            path.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        self.store.record(
            "hardware.archive.saved",
            {"id": evidence["id"], "sha256": hashlib.sha256(data).hexdigest()},
        )
        return evidence

    def import_capture(self, key):
        receipt, data = self.files._load(identifier(key))
        if not receipt.get("complete") or receipt.get("access_method") != "stream-access":
            raise ValueError("Choose a complete stream-access application archive capture.")
        return self.import_archive(
            data,
            receipt["metadata"]["object_name"].split("/")[-1] + ".moi",
            origin={"kind": "saved-bacnet-file", "capture_id": key, "receipt": receipt},
        )

    def enrich(self, report_id, archive_id):
        return self.save_report(
            enrich_report(self.report(report_id), self.archive(archive_id)),
            origin="archive-comparison",
        )

    def status(self):
        reports = []
        archives = []
        for path in sorted(self.directory.glob("report-*.json")):
            row = self.report(path.stem.removeprefix("report-"))
            reports.append(
                {
                    key: row.get(key)
                    for key in (
                        "id",
                        "saved_at",
                        "target",
                        "connector_config",
                        "identity",
                        "status",
                        "origin",
                        "imported",
                    )
                }
            )
        for path in sorted(self.directory.glob("archive-*.json")):
            row = self.archive(path.stem.removeprefix("archive-"))
            archives.append(
                {
                    key: row.get(key)
                    for key in ("id", "saved_at", "source", "identity", "profile", "errors")
                }
            )
        return {
            "profile": "hardware-workbench/1",
            "supported_transports": ["bacnet-ip", "direct-mstp"],
            "read_only": True,
            "native_apply_supported": False,
            "limits": {
                "reports": MAX_REPORTS,
                "archives": MAX_ARCHIVES,
                "jobs": MAX_JOBS,
                "active_jobs": 1,
                "archive_bytes": MAX_SOURCE,
            },
            "jobs": [self._job_summary(row) for row in self.jobs.values()],
            "reports": reports,
            "archives": archives,
            "captures": self.files.captures(),
        }

    @staticmethod
    def _job_summary(job):
        return {key: value for key, value in job.items() if key not in ("report", "archive")}

    def job(self, key):
        key = identifier(key)
        if key not in self.jobs:
            raise ValueError("Hardware read job was not found.")
        return copy.deepcopy(self.jobs[key])

    def start(self, kind, body):
        if self.closed:
            raise ValueError("Hardware workbench is shutting down.")
        self.bacnet.require()
        if any(not task.done() for task in self.tasks.values()):
            raise ValueError("A hardware read is already active. Finish or cancel it first.")
        if len(self.jobs) >= MAX_JOBS:
            raise ValueError("Hardware read history is full; remove a finished job first.")
        model_admission = None
        if kind == "survey":
            qualified = WorkbenchSurveyRequest.model_validate(body)
            options = HardwareSurveyRequest.model_validate(
                qualified.model_dump(exclude={"model_qualification"})
            )
            if options.transport == "direct-mstp":
                serial_identity(self.bacnet.config, options)
            elif (self.bacnet.config or {}).get("transport") == "mstp":
                raise ValueError(
                    "Select direct-mstp explicitly for a hardware survey over the open serial interface."
                )
            body = options.model_dump()
            if qualified.model_qualification is not None:
                model_admission = review_model_transport(
                    qualified.model_qualification,
                    {
                        key: body[key]
                        for key in ("transport", "address", "device", "router", "dnet")
                    },
                    self.bacnet.config,
                    connected=True,  # require() above admitted the existing local interface.
                )
                if not model_admission["dispatch_admitted"]:
                    raise ValueError(
                        "Model-qualified target is not admitted: "
                        + ", ".join(item["code"] for item in model_admission["findings"])
                    )
        elif kind == "archive-read":
            report = self.report(body["report_id"])
            target = HardwareTargetRequest.model_validate(report["target"])
            if target.transport == "direct-mstp":
                serial_identity(self.bacnet.config, target)
                if self.bacnet.config != report.get("connector_config"):
                    raise ValueError(
                        "Serial interface differs from the saved survey; reopen that exact interface or run a new survey."
                    )
            if not report.get("inventory", {}).get("complete"):
                raise ValueError(
                    "Complete the object inventory before selecting an existing archive."
                )
        else:
            raise ValueError("Unsupported read-only hardware job.")
        key = secrets.token_hex(16)
        job = {
            "id": key,
            "kind": kind,
            "status": "queued",
            "started_at": now(),
            "progress": {},
            "read_only": True,
            "connector_config": copy.deepcopy(self.bacnet.config),
            "target": {
                key: body.get(key) for key in ("transport", "address", "device", "router", "dnet")
            }
            if kind == "survey"
            else copy.deepcopy(report["target"]),
        }
        if model_admission is not None:
            job["model_transport_admission"] = model_admission
        self._write("job", key, job)
        self.jobs[key] = job
        self.tasks[key] = asyncio.create_task(self._run(key, kind, body))
        return self._job_summary(job)

    async def _run(self, key, kind, body):
        job = self.jobs[key]
        job["status"] = "running"

        def progress(report):
            job["report"] = copy.deepcopy(report)
            if "model_transport_admission" in job:
                job["model_transport_observation"] = observe_model_transport(
                    job["model_transport_admission"], report
                )
            inventory = report.get("inventory", {})
            job["progress"] = {
                "objects_read": inventory.get("read", 0),
                "objects_total": inventory.get("total"),
                "inputs_read": len(report.get("inputs", [])),
            }

        try:
            if kind == "survey":
                admission = job.get("model_transport_admission")
                if admission is not None:
                    self.bacnet.require()
                    current = review_model_transport(
                        admission["declaration"],
                        admission["target"],
                        self.bacnet.config,
                        connected=True,
                    )
                    if current != admission:
                        raise ValueError(
                            "Model-qualified target/interface changed before the read; review a fresh target explicitly."
                        )
                result = await self.surveys.survey(
                    body, progress=progress, expected_config=job["connector_config"]
                )
                if admission is not None:
                    job["model_transport_observation"] = observe_model_transport(admission, result)
                saved = self.save_report(result, origin="live-read")
                job.update(
                    report=saved,
                    report_id=saved["id"],
                    status="complete" if saved.get("status") == "complete" else "partial",
                )
            else:
                original = self.report(body["report_id"])
                evidence = await self._read_archive(original, body.get("file_object"), job)
                job.update(archive=evidence, archive_id=evidence["id"])
                saved = self.save_report(
                    enrich_report(original, evidence), origin="controller-archive-comparison"
                )
                job.update(report=saved, report_id=saved["id"], status="complete")
        except asyncio.CancelledError:
            job.update(
                status="cancelled",
                error="Read cancelled; retained evidence is partial and no controller changes were made.",
            )
            if job.get("report"):
                partial = copy.deepcopy(job["report"])
                partial.update(status="partial", cancelled=True, candidates=[])
                partial.setdefault("inventory", {})["complete"] = False
                try:
                    saved = self.save_report(partial, origin="cancelled-live-read")
                    job.update(report=saved, report_id=saved["id"])
                except (ValueError, OSError) as exc:
                    job["storage_error"] = str(exc)
        except Exception as exc:
            job.update(status="error", error=str(exc) or type(exc).__name__)
        finally:
            job["finished_at"] = now()
            try:
                self._write("job", key, job)
            except (ValueError, OSError) as exc:
                job["storage_error"] = str(exc)

    async def cancel(self, key):
        job = self.job(key)
        task = self.tasks.get(key)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        # A task cancelled before its first bytecode never enters _run/finally.
        if self.jobs[key]["status"] in ("queued", "running"):
            self.jobs[key].update(
                status="cancelled",
                finished_at=now(),
                error="Read cancelled before it started; no controller changes were made.",
            )
            self._write("job", key, self.jobs[key])
        return self.job(job["id"])

    async def close(self):
        self.closed = True
        await asyncio.gather(
            *(self.cancel(key) for key in list(self.tasks)), return_exceptions=True
        )

    def delete(self, kind, key):
        kind = {"reports": "report", "archives": "archive", "jobs": "job"}.get(kind, kind)
        if kind not in ("report", "archive", "job"):
            raise ValueError("Unknown hardware evidence kind.")
        key = identifier(key)
        task = self.tasks.get(key)
        if task and not task.done():
            raise ValueError("Cancel the active read before removing its job.")
        self._load(kind, key)
        self._path(kind, key).unlink()
        if kind == "job":
            self.jobs.pop(key, None)
            self.tasks.pop(key, None)
        if kind == "archive":
            (self.directory / ("source-" + key + ".bin")).unlink(missing_ok=True)
        return {"deleted": key, "kind": kind}

    async def _read_archive(self, report, selected, job):
        # Every operation stays under the explicit route/source filter and the
        # connection lock. Only one previously advertised existing file is read.
        from bacpypes3.apdu import AtomicReadFileACK, AtomicReadFileRequest, ErrorRejectAbortNack
        from bacpypes3.basetypes import (
            AtomicReadFileRequestAccessMethodChoice,
            AtomicReadFileRequestAccessMethodChoiceStreamAccess,
            DateTime,
            FileAccessMethod,
        )
        from bacpypes3.primitivedata import Boolean, CharacterString, ObjectIdentifier, Unsigned

        from .bacnet_exchange import confirmed_exchange
        from .hardware_survey import read_fields

        target = HardwareTargetRequest(
            **{
                key: report["target"][key]
                for key in ("transport", "address", "device", "router", "dnet")
                if key in report["target"]
            }
        )
        entries = report["inventory"].get("objects", [])
        objects = [entry.get("object") if isinstance(entry, dict) else entry for entry in entries]
        files = [obj for obj in objects if isinstance(obj, str) and obj.startswith("file,")]
        if not files or len(files) > 16 or (selected is not None and selected not in files):
            raise ValueError(
                "Choose an existing File object from this report's complete advertised inventory."
            )
        identity_fields = [
            ("object-identifier", None, ObjectIdentifier),
            ("object-name", None, CharacterString),
            ("model-name", None, CharacterString),
            ("firmware-revision", None, CharacterString),
            ("max-apdu-length-accepted", None, Unsigned),
            ("object-list", 0, Unsigned),
        ]
        metadata_fields = [
            ("object-name", None, CharacterString),
            ("file-type", None, CharacterString),
            ("file-size", None, Unsigned),
            ("file-access-method", None, FileAccessMethod),
            ("read-only", None, Boolean),
            ("modification-date", None, DateTime),
        ]

        def values(rows):
            if any("error" in row for row in rows):
                raise ValueError("Required archive identity or metadata could not be read.")
            return {row["property"]: row["value"] for row in rows}

        details = DeviceDetails(self.bacnet, self.store)
        data = bytearray()
        started = now()
        async with asyncio.timeout(240):
            async with details._path(target) as session:
                if session["config"] != job["connector_config"] or (
                    target.transport == "direct-mstp"
                    and session["config"] != report.get("connector_config")
                ):
                    raise ValueError(
                        "Hardware archive interface changed; run a new survey before reading."
                    )
                identity = values(
                    await read_fields(details, session, target.device, identity_fields)
                )
                if (
                    identity["object-identifier"] != target.device
                    or identity["object-list"] != report["inventory"]["total"]
                ):
                    raise ValueError("Controller identity or inventory changed. Run a new survey.")
                for field, old in (
                    ("object-name", report["identity"].get("name")),
                    ("model-name", report["identity"].get("model")),
                    ("firmware-revision", report["identity"].get("firmware")),
                ):
                    if old is not None and identity[field] != old:
                        raise ValueError("Controller identity changed. Run a new survey.")
                choices = []
                for obj in [selected] if selected else files:
                    metadata = values(await read_fields(details, session, obj, metadata_fields))
                    if str(metadata["file-type"]).lower() == ".moi" and (
                        selected or str(metadata["object-name"]).lower().endswith("/archive")
                    ):
                        choices.append((obj, metadata))
                if len(choices) != 1:
                    raise ValueError(
                        "No unique Archive .moi was found. Select its existing File object explicitly."
                    )
                obj, metadata = choices[0]
                file_index = objects.index(obj) + 1
                membership = values(
                    await read_fields(
                        details,
                        session,
                        target.device,
                        [("object-list", file_index, ObjectIdentifier)],
                    )
                )
                if membership["object-list"] != obj:
                    raise ValueError(
                        "Selected File object is no longer advertised at its surveyed index. Run a new survey."
                    )
                size = metadata["file-size"]
                if (
                    type(size) is not int
                    or not 0 < size <= MAX_SOURCE
                    or metadata["file-access-method"] != int(FileAccessMethod("stream-access"))
                ):
                    raise ValueError("Archive size or access method is outside the read profile.")
                maximum = identity["max-apdu-length-accepted"]
                if type(maximum) is not int or not 50 <= maximum <= 1476:
                    raise ValueError("Invalid controller APDU capacity.")
                chunk = min(
                    448, maximum - 32, int(session["app"].device_object.maxApduLengthAccepted) - 32
                )
                pages = 0
                eof = False
                while not eof:
                    gap = details.request_gap - (
                        asyncio.get_running_loop().time() - session["last_request"]
                    )
                    if gap > 0:
                        await asyncio.sleep(gap)
                    details._guard(session)
                    session["last_request"] = asyncio.get_running_loop().time()
                    count = min(chunk, max(1, size - len(data)))
                    request = AtomicReadFileRequest(
                        fileIdentifier=ObjectIdentifier(obj),
                        accessMethod=AtomicReadFileRequestAccessMethodChoice(
                            streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                                fileStartPosition=len(data), requestedOctetCount=count
                            )
                        ),
                        destination=session["target"],
                    )
                    try:
                        ack = await asyncio.wait_for(confirmed_exchange(session["app"], request), 5)
                    except ErrorRejectAbortNack as exc:
                        raise ValueError("Archive read rejected: " + str(exc)) from exc
                    details._guard(session)
                    if (
                        not isinstance(ack, AtomicReadFileACK)
                        or ack.pduSource != session["target"]
                        or ack.apduInvokeID != request.apduInvokeID
                        or ack.accessMethod.streamAccess is None
                        or ack.accessMethod.recordAccess is not None
                        or ack.accessMethod.streamAccess.fileStartPosition != len(data)
                    ):
                        raise ValueError("Archive response source/invoke/access/offset mismatch.")
                    block = bytes(ack.accessMethod.streamAccess.fileData)
                    if (
                        len(block) > count
                        or len(data) + len(block) > size
                        or (not block and not ack.endOfFile)
                    ):
                        raise ValueError("Archive response size or progress mismatch.")
                    data.extend(block)
                    eof = bool(ack.endOfFile)
                    pages += 1
                    if pages > 8192 or (eof and len(data) != size):
                        raise ValueError("Archive EOF or page budget mismatch.")
                    job["progress"] = {"bytes_read": len(data), "bytes_total": size, "pages": pages}
                if (
                    values(await read_fields(details, session, obj, metadata_fields)) != metadata
                    or values(await read_fields(details, session, target.device, identity_fields))
                    != identity
                ):
                    raise ValueError(
                        "Controller identity or archive metadata changed during the read."
                    )
                if (
                    values(
                        await read_fields(
                            details,
                            session,
                            target.device,
                            [("object-list", file_index, ObjectIdentifier)],
                        )
                    )
                    != membership
                ):
                    raise ValueError("Selected advertised File membership changed during the read.")
        receipt = {
            "kind": "existing-controller-file",
            "target": target.model_dump(),
            "connector_config": copy.deepcopy(session["config"]),
            "file_object": obj,
            "file_object_list_index": file_index,
            "source_inventory_sha256": digest(objects),
            "identity": identity,
            "metadata": metadata,
            "started_at": started,
            "finished_at": now(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "pages": pages,
            "complete": True,
            "controller_writes": False,
            "consistency": "Stable metadata before/after; opaque existing file, not an atomic native backup.",
        }
        return self.import_archive(bytes(data), "Archive.moi", origin=receipt)

    def sensor_plan(self, request):
        report = self.report(request.report_id)
        relocation = None
        freed = None
        if request.relocation:
            move = request.relocation
            relocation = relocation_plan(
                report, move.source_object, move.destination_sa_mac, move.destination_slot
            )
            # This is still conditional engineering work even when analysis finds
            # compatible capacity. A plan never executes native field changes.
            if relocation.get("status") != "review-required":
                raise ValueError("The proposed relocation is blocked by the report evidence.")
            source = next(
                (row for row in report["inputs"] if row["object"] == move.source_object), None
            )
            if source is None or not str(source.get("device_type", "")).startswith("UI"):
                raise ValueError("Relocation must free an existing universal input.")
            freed = (source.get("sa_mac"), source.get("slot"))
            source_modules = [
                module
                for module in occupancy(report)["modules"]
                if module.get("sa_mac") == freed[0]
                and module.get("host") == ("local" if freed[0] is None else "sa")
            ]
            if len(source_modules) != 1 or freed[1] not in (
                source_modules[0].get("capacity") or {}
            ).get("universal_inputs", []):
                raise ValueError(
                    "The freed terminal needs a documented voltage-capable source module before a sensor plan can use it."
                )
        candidates = report.get("candidates", [])
        available = set()
        for row in candidates:
            if row.get("status") == "candidate" and (
                row.get("terminal_type") == "UI"
                or row.get("kind") == "UI"
                or row.get("voltage_capable") is True
            ):
                available.add((row.get("sa_mac"), row.get("slot")))
        if freed:
            available.add(freed)
        channels = []
        used = set()
        for channel in request.channels:
            key = (channel.sa_mac, channel.slot)
            if key in used or key not in available:
                raise ValueError(
                    "Each sensor must use a distinct candidate universal input or the input conditionally freed by the relocation."
                )
            if (
                channel.signal_high <= channel.signal_low
                or channel.engineering_high <= channel.engineering_low
            ):
                raise ValueError(
                    "Signal and engineering upper endpoints must exceed the lower endpoints."
                )
            used.add(key)
            slope = (channel.engineering_high - channel.engineering_low) / (
                channel.signal_high - channel.signal_low
            )
            offset = channel.engineering_low - slope * channel.signal_low
            if not math.isfinite(slope) or not math.isfinite(offset):
                raise ValueError("Scaling exceeds finite engineering limits.")
            channels.append(
                channel.model_dump()
                | {
                    "slope": slope,
                    "offset": offset,
                    "checks": [
                        {"volts": volts, "engineering_value": offset + slope * volts}
                        for volts in (
                            channel.signal_low,
                            (channel.signal_low + channel.signal_high) / 2,
                            channel.signal_high,
                        )
                    ],
                    "conditional_on_relocation": key == freed,
                }
            )
        return {
            "profile": "hardware-sensor-plan/1",
            "read_only": True,
            "native_apply_supported": False,
            "report_id": report["id"],
            "report_sha256": report["content_sha256"],
            "target": report["target"],
            "relocation": relocation,
            "channels": channels,
            "required_checks": [
                "Confirm physical module labels and unwired terminals.",
                "Review sensor supply and shared GND against each module's input ICOM reference.",
                "Configure matching native voltage inputs and engineering ranges in compatible CCT/PCT.",
                "Preserve existing alarm polarity, delays, and logic references.",
                "Commission low, middle, and high signals after wiring and native program validation.",
            ],
            "execution": "Engineering plan only; no controller program, point, jumper, or wiring changes.",
        }


def report_csv(report):
    stream = io.StringIO(newline="")
    keys = [
        "object",
        "name",
        "description",
        "device_type",
        "terminal_type",
        "slot",
        "sa_mac",
        "host",
        "present_value",
        "units",
        "reliability",
        "status_flags",
        "out_of_service",
        "errors",
    ]
    writer = csv.writer(stream)
    writer.writerow(
        ["controller", "device", "address", "router", "dnet", "transport", "connector_config"]
        + keys
    )

    def value(item):
        if isinstance(item, (dict, list)):
            item = json.dumps(item, ensure_ascii=False, allow_nan=False)
        if isinstance(item, str) and item.startswith(("=", "+", "-", "@", "\t", "\r")):
            item = "'" + item
        return item

    target = report["target"]
    for row in report["inputs"]:
        writer.writerow(
            [
                value(report["identity"].get("name")),
                target.get("device"),
                target.get("address"),
                target.get("router"),
                target.get("dnet"),
                target.get("transport", "bacnet-ip"),
                value(report.get("connector_config")),
            ]
            + [value(row.get(key)) for key in keys]
        )
    return stream.getvalue().encode("utf-8-sig")


def hardware_router(workbench):
    router = APIRouter(prefix="/api/bacnet/hardware")

    @router.get("/status")
    async def status():
        return workbench.status()

    @router.post("/survey")
    async def survey(body: WorkbenchSurveyRequest):
        return workbench.start("survey", body.model_dump())

    @router.get("/model-transport/profile")
    async def model_transport_profile():
        return model_transport_catalog()

    @router.post("/model-transport/review")
    async def model_transport_review(body: ModelReviewRequest):
        return review_model_transport(
            body.qualification,
            body.target,
            workbench.bacnet.config,
            connected=workbench.bacnet.status()["connected"],
        )

    @router.get("/jobs/{key}")
    async def job(key: str):
        return workbench.job(key)

    @router.get("/jobs/{key}/export")
    async def export_job(key: str):
        return Response(
            canonical(workbench.job(key)),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="hardware-job-{identifier(key)}.json"'
            },
        )

    @router.post("/jobs/{key}/cancel")
    async def cancel(key: str):
        return await workbench.cancel(key)

    @router.post("/read-archive")
    async def read_archive(body: ReadArchiveRequest):
        return workbench.start("archive-read", body.model_dump())

    @router.get("/reports/{key}")
    async def report(key: str):
        return workbench.report(key)

    @router.get("/reports/{key}/export")
    async def export(key: str, format: str = "json"):
        row = workbench.report(key)
        if format not in ("json", "csv"):
            raise ValueError("Choose JSON or CSV hardware export.")
        return Response(
            report_csv(row) if format == "csv" else canonical(row),
            media_type="text/csv" if format == "csv" else "application/json",
            headers={"Content-Disposition": f'attachment; filename="hardware-{key}.{format}"'},
        )

    @router.post("/import-report")
    async def import_report(file: Annotated[UploadFile, File()]):
        return workbench.import_report(await file.read(MAX_DOCUMENT + 1))

    @router.post("/archive")
    async def archive(file: Annotated[UploadFile, File()]):
        return workbench.import_archive(await file.read(MAX_SOURCE + 1), file.filename)

    @router.post("/archive/capture")
    async def capture(body: CaptureArchiveRequest):
        return workbench.import_capture(body.capture_id)

    @router.get("/archives/{key}")
    async def get_archive(key: str):
        return workbench.archive(key)

    @router.get("/archives/{key}/export")
    async def archive_export(key: str, format: str = "json"):
        row = workbench.archive(key)
        if format == "json":
            return Response(
                canonical(row),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="hardware-archive-{identifier(key)}.json"'
                },
            )
        if format != "source":
            raise ValueError("Choose JSON evidence or exact source bytes.")
        path = workbench.directory / ("source-" + identifier(key) + ".bin")
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_SOURCE:
            raise ValueError("Saved archive source is unavailable.")
        data = path.read_bytes()
        source = row.get("source", {})
        if source.get("sha256") and hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("Saved archive source failed its integrity check.")
        extension = "caf" if row.get("archive_format") == "CAF" else "moi"
        return Response(
            data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="hardware-{key}.{extension}"'},
        )

    @router.post("/enrich")
    async def enrich(body: ReportArchiveRequest):
        return workbench.enrich(body.report_id, body.archive_id)

    @router.post("/relocation")
    async def relocation(body: RelocationRequest):
        report = workbench.report(body.report_id)
        plan = relocation_plan(
            report,
            body.source_object,
            body.destination_sa_mac,
            body.destination_slot,
        )
        return plan | {
            "report_id": report["id"],
            "report_sha256": report["content_sha256"],
            "target": report["target"],
            "archive_source": report.get("archive_comparison", {}).get("archive_source"),
        }

    @router.post("/sensor-plan")
    async def sensor_plan(body: SensorPlanRequest):
        return workbench.sensor_plan(body)

    @router.delete("/{kind}/{key}")
    async def delete(kind: str, key: str):
        return workbench.delete(kind, key)

    return router
