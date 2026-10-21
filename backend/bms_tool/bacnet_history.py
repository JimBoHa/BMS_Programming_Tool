"""Explicit, bounded BACnet Trend Log ReadRange retrieval and immutable captures.

Uses the existing connector only. No connection, polling, subscriptions, device
writes or backfilled simulation observations are created by this module.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import fcntl
import hashlib
import importlib.metadata
import json
import math
import os
import secrets
import stat
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from zoneinfo import TZPATH, ZoneInfo, ZoneInfoNotFoundError

from bacpypes3.apdu import ErrorRejectAbortNack, ReadRangeACK, ReadRangeRequest
from bacpypes3.basetypes import (
    DateTime,
    LogRecord,
    Range,
    RangeByPosition,
    RangeBySequenceNumber,
    RangeByTime,
)
from bacpypes3.constructeddata import ListOf
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import AwareDatetime, Field, field_validator, model_validator

from .bacnet_exchange import confirmed_exchange
from .models import StrictModel

SCOPE = "Read-only BACnet Trend Log history; device timestamps interpreted in the operator-selected IANA timezone"
PROFILE = "bacnet-trend-log-history/1"
MAX_BYTES = 2 * 1024 * 1024
MAX_PAGES = 100
MAX_CAPTURES = 32
MAX_STORAGE = 32 * 1024 * 1024
CAPTURE_LOCK_SECONDS = 2.0
UINT32 = 0xFFFFFFFF


def _sequence(first, offset):
    # Trend Log Total_Record_Count wraps from 2**32-1 to1, never to0.
    return (first - 1 + offset) % UINT32 + 1


def _zone(value):
    try:
        return ZoneInfo(value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("device_timezone must be an installed IANA timezone.") from exc


def _timezone_provenance(name):
    result = {"name": name, "selection": "operator supplied; not inferred from BACnet timestamps"}
    try:
        result["tzdata_version"] = importlib.metadata.version("tzdata")
    except importlib.metadata.PackageNotFoundError:
        result["tzdata_version"] = None
    for directory in TZPATH:
        candidate = Path(directory) / name
        if candidate.is_file():
            result["zone_file_sha256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
            break
    return result


class BacnetHistoryRequest(StrictModel):
    address: str = Field(min_length=1, max_length=256)
    object_id: str = Field(min_length=1, max_length=80)
    device_timezone: str = Field(min_length=1, max_length=128)
    mode: Literal["position", "sequence", "time"] = "position"
    reference: int | None = Field(default=None, ge=0, le=UINT32, strict=True)
    reference_time: AwareDatetime | None = None
    count: int = Field(default=100, ge=1, le=1000, strict=True)
    page_size: int = Field(default=25, ge=1, le=100, strict=True)
    fold: int | None = Field(default=None, ge=0, le=1, strict=True)

    @field_validator("object_id")
    @classmethod
    def trend_log_only(cls, value):
        try:
            identifier = ObjectIdentifier(value)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "Use a standard trend-log object identifier, for example trend-log,1."
            ) from exc
        if int(identifier[0]) != 20 or not 0 <= identifier[1] <= 4194302:
            raise ValueError("This profile reads standard trend-log objects only.")
        return str(identifier)

    @field_validator("device_timezone")
    @classmethod
    def installed_zone(cls, value):
        _zone(value)
        return value

    @model_validator(mode="after")
    def range_parameters(self):
        if self.mode == "time":
            if self.reference is not None or self.reference_time is None:
                raise ValueError("Time ranges require reference_time and omit reference.")
            try:
                local = self.reference_time.astimezone(_zone(self.device_timezone))
            except OverflowError as exc:
                raise ValueError("Reference time exceeds the local datetime range.") from exc
            if not 1900 <= local.year <= 2154 or local.microsecond % 10000:
                raise ValueError(
                    "BACnet reference time needs year1900..2154 and whole hundredths of a second."
                )
        else:
            if self.reference_time is not None:
                raise ValueError("Position/sequence ranges omit reference_time.")
            if self.reference is None:
                self.reference = 1
            if self.mode == "position" and self.reference == 0:
                raise ValueError("BACnet list positions start at1.")
        return self


def _clock(timestamp, zone, fold):
    raw = {"date": list(timestamp.date), "time": list(timestamp.time)}
    try:
        year, month, day, weekday = timestamp.date
        hour, minute, second, hundredths = timestamp.time
        if year == 255 or any(
            value == 255 for value in (month, day, hour, minute, second, hundredths)
        ):
            raise ValueError("Device timestamp contains unresolved date/time wildcard fields.")
        if not 0 <= hundredths <= 99:
            raise ValueError("Device timestamp hundredths are invalid.")
        naive = datetime(1900 + year, month, day, hour, minute, second, hundredths * 10000)
        if weekday not in (255, naive.weekday() + 1):
            raise ValueError("Device timestamp weekday conflicts with its calendar date.")
        candidates = {}
        for candidate_fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=candidate_fold)
            utc = candidate.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) == naive:
                candidates[candidate_fold] = utc
        if not candidates:
            raise ValueError("Nonexistent local time during a timezone clock transition.")
        ambiguous = len(set(candidates.values())) > 1
        if ambiguous and fold is None:
            raise ValueError("Ambiguous local time; choose fold0 or1 explicitly.")
        selected = candidates[fold if ambiguous else next(iter(candidates))]
        return raw, selected.isoformat(timespec="microseconds"), None
    except (ValueError, OverflowError, IndexError) as exc:
        return raw, None, str(exc)


def _record(record, *, sequence, received_at, zone, fold):
    local, source_clock, timestamp_error = _clock(record.timestamp, zone, fold)
    kind = record.logDatum._choice
    value = getattr(record.logDatum, kind)
    flags = None if record.statusFlags is None else list(record.statusFlags)
    if flags is not None and len(flags) != 4:
        raise ValueError("Historical status flags must contain exactly four bits.")
    result = {
        "sequence": sequence,
        "source_clock": source_clock,
        "recorded_at": received_at,
        "local_timestamp": local,
        "timestamp_error": timestamp_error,
        "datum_type": kind,
        "quality": "unknown",
        "sample": False,
        "status_flags": None
        if flags is None
        else {
            name: bool(flag)
            for name, flag in zip(
                ("in_alarm", "fault", "overridden", "out_of_service"), flags, strict=True
            )
        },
    }
    if kind in ("booleanValue", "realValue", "enumValue", "unsignedValue", "signedValue"):
        scalar = (
            bool(value)
            if kind == "booleanValue"
            else float(value)
            if kind == "realValue"
            else int(value)
        )
        integer_outside_profile = kind in ("enumValue", "unsignedValue", "signedValue") and not (
            -(2**31) <= scalar < 2**31 if kind == "signedValue" else 0 <= scalar <= UINT32
        )
        if integer_outside_profile:
            encoded = scalar.to_bytes((scalar.bit_length() + 8) // 8, "big", signed=True)
            result.update(
                value=None,
                quality="fault",
                value_error="Device integer datum exceeds the 32-bit result profile.",
                integer_bit_length=abs(scalar).bit_length(),
                integer_value_sha256=hashlib.sha256(encoded).hexdigest(),
                integer_hash_encoding="minimal signed big-endian decoded integer",
            )
            if abs(scalar).bit_length() <= 256:
                result["exact_integer"] = str(scalar)
        elif isinstance(scalar, float) and not math.isfinite(scalar):
            result.update(
                value=None, value_error="Device logged a nonfinite numeric value.", quality="fault"
            )
        else:
            result.update(value=scalar, sample=source_clock is not None)
            if flags is not None:
                result["quality"] = (
                    "unreliable" if any(flags[1:]) else "good" if source_clock else "unknown"
                )
            result["quality_basis"] = (
                "Historical record status flags only; device reliability was not recorded."
            )
    elif kind in ("logStatus", "bitstringValue"):
        bits = list(value)
        if len(bits) > 256:
            raise ValueError("Logged bitstring exceeds the256-bit result profile.")
        result["value"] = (
            {
                name: bool(flag)
                for name, flag in zip(
                    ("log_disabled", "buffer_purged", "log_interrupted"), bits, strict=True
                )
            }
            if kind == "logStatus"
            else [bool(bit) for bit in bits]
        )
    elif kind == "nullValue":
        result["value"] = None
    elif kind == "failure":
        result.update(
            value=None,
            quality="fault",
            failure={"error_class": str(value.errorClass), "error_code": str(value.errorCode)},
        )
    elif kind == "timeChange":
        result["value"] = float(value) if math.isfinite(value) else None
        if not math.isfinite(value):
            result.update(
                quality="fault", value_error="Device logged a nonfinite clock adjustment."
            )
        result["meaning"] = "Logged device clock adjustment in seconds; not a process sample."
    elif kind == "anyValue":
        encoded = bytes(value.tagList.encode().pduData)
        result.update(
            value=None,
            opaque_bytes=len(encoded),
            opaque_sha256=hashlib.sha256(encoded).hexdigest(),
            opaque_base64=base64.b64encode(encoded[:1024]).decode(),
            opaque_truncated=len(encoded) > 1024,
        )
    else:
        raise ValueError("Unsupported BACnet log record alternative.")
    return result


class BacnetHistory:
    profile = PROFILE
    source_kind = "device-history"
    storage_name = "bacnet-history"

    def __init__(self, bacnet, store_or_directory=None, *, timeout=3.0, operation_timeout=30.0):
        if not 0.05 <= timeout <= 6 or not timeout <= operation_timeout <= 60:
            raise ValueError(
                "History timeout must be0.05..6s; operation timeout must be timeout..60s."
            )
        self.bacnet = bacnet
        self.timeout, self.operation_timeout = timeout, operation_timeout
        self.store = store_or_directory if hasattr(store_or_directory, "record") else None
        directory = getattr(store_or_directory, "directory", store_or_directory)
        self.directory = Path(directory or bacnet.store.directory) / self.storage_name
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._reports = OrderedDict()

    def status(self):
        return {
            "profile": self.profile,
            "scope": SCOPE,
            "read_only": True,
            "connected": self.bacnet.status()["connected"],
            "source_kind": "device-history",
            "auto_poll": False,
            "limits": {
                "records": 1000,
                "page_size": 100,
                "pages": MAX_PAGES,
                "response_bytes": MAX_BYTES,
                "request_seconds": self.timeout,
                "operation_seconds": self.operation_timeout,
                "saved_captures": MAX_CAPTURES,
                "saved_bytes": MAX_STORAGE,
                "capture_lock_seconds": CAPTURE_LOCK_SECONDS,
            },
            "library": {
                "name": "BACpypes3",
                "version": "0.0.110",
                "source_revision": "21f918c0396c72c95e7e635abde18514e58feb8d",
            },
            "captures": self.captures(),
        }

    async def _page(self, app, config, address, object_id, mode, reference, reference_time, count):
        if self.bacnet.require() is not app or self.bacnet.config != config:
            raise ValueError("BACnet interface changed during history retrieval.")
        selection = (
            Range(byPosition=RangeByPosition(referenceIndex=reference, count=count))
            if mode == "position"
            else Range(
                bySequenceNumber=RangeBySequenceNumber(
                    referenceSequenceNumber=reference, count=count
                )
            )
            if mode == "sequence"
            else Range(byTime=RangeByTime(referenceTime=DateTime(reference_time), count=count))
        )
        target = self.bacnet.target_address(address)
        request = ReadRangeRequest(
            objectIdentifier=object_id,
            propertyIdentifier="log-buffer",
            range=selection,
            destination=target,
        )
        try:
            reply = await asyncio.wait_for(confirmed_exchange(app, request), self.timeout)
            if isinstance(reply, ErrorRejectAbortNack):
                raise ValueError("BACnet history read rejected: " + str(reply))
            if (
                not isinstance(reply, ReadRangeACK)
                or reply.pduSource != target
                or reply.apduInvokeID != request.apduInvokeID
                or reply.objectIdentifier != ObjectIdentifier(object_id)
                or str(reply.propertyIdentifier) != "log-buffer"
                or reply.propertyArrayIndex is not None
            ):
                raise ValueError("BACnet ReadRange acknowledgement identity/property mismatch.")
            size = len(reply.itemData.tagList.encode().pduData)
            if size > MAX_BYTES or int(reply.itemCount) > count:
                raise ValueError("BACnet history response exceeds the requested result bounds.")
            values = reply.itemData.cast_out(ListOf(LogRecord))
            if len(values) != int(reply.itemCount):
                raise ValueError(
                    "BACnet ReadRange itemCount differs from the decoded record count."
                )
            flags = list(reply.resultFlags)
            if len(flags) != 3:
                raise ValueError("Invalid BACnet ReadRange result flags.")
            if flags[1] and flags[2]:
                raise ValueError(
                    "ReadRange cannot report both lastItem and moreItems for a forward range."
                )
            first = None if reply.firstSequenceNumber is None else int(reply.firstSequenceNumber)
            if first is not None and not 0 <= first <= UINT32:
                raise ValueError("ReadRange sequence metadata exceeds Unsigned32.")
            if values and first is not None and not 1 <= first <= UINT32:
                raise ValueError("Populated Trend Log sequence numbers must be1..4294967295.")
            if mode != "position" and values and first is None:
                raise ValueError("Sequence/time response omitted its firstSequenceNumber.")
            if mode == "sequence" and values:
                offset = first if reference == 0 else (first - reference) % UINT32
                if offset + len(values) > count:
                    raise ValueError(
                        "ReadRange sequence response exceeds the requested forward sequence window."
                    )
            return values, first, flags
        except ErrorRejectAbortNack as exc:
            raise ValueError("BACnet history read rejected: " + str(exc)) from exc
        except (DecodingError, InvalidTag, TypeError, AttributeError) as exc:
            raise ValueError("Malformed BACnet Trend Log response: " + str(exc)) from exc

    async def read(self, **parameters):
        request = BacnetHistoryRequest(**parameters)
        zone = _zone(request.device_timezone)
        mode, reference = request.mode, request.reference
        reference_time = (
            None
            if request.reference_time is None
            else request.reference_time.astimezone(zone).replace(tzinfo=None)
        )
        report = {
            "id": secrets.token_hex(16),
            "profile": PROFILE,
            "scope": SCOPE,
            "source_kind": "device-history",
            "target": {"address": request.address, "object_id": request.object_id},
            "request": request.model_dump(mode="json"),
            "timezone": _timezone_provenance(request.device_timezone),
            "read_at": datetime.now(UTC).isoformat(),
            "received_at": None,
            "records": [],
            "pages": [],
            "complete": False,
            "truncated": False,
            "errors": [],
            "warnings": [],
            "next_cursor": None,
            "consistency": "Sequence-anchored when available; device clock changes are preserved without sorting.",
        }
        deadline = time.monotonic() + self.operation_timeout
        expected_sequence = None
        encoded_record_bytes = 0
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.bacnet.lock:
                    app, config = self.bacnet.require(), copy.deepcopy(self.bacnet.config)
                    report["connector_config"] = config
                    report["target"]["address"] = str(self.bacnet.target_address(request.address))
                    while (
                        len(report["records"]) < request.count and len(report["pages"]) < MAX_PAGES
                    ):
                        if time.monotonic() >= deadline:
                            raise TimeoutError("History operation deadline reached.")
                        count = min(request.page_size, request.count - len(report["records"]))
                        values, first, flags = await self._page(
                            app,
                            config,
                            request.address,
                            request.object_id,
                            mode,
                            reference,
                            reference_time,
                            count,
                        )
                        receipt = datetime.now(UTC).isoformat()
                        report["received_at"] = receipt
                        gap = (
                            bool(values)
                            and expected_sequence is not None
                            and first != expected_sequence
                        )
                        page = {
                            "mode": mode,
                            "reference": reference,
                            "count": len(values),
                            "first_sequence": first,
                            "result_flags": {
                                "first_item": bool(flags[0]),
                                "last_item": bool(flags[1]),
                                "more_items": bool(flags[2]),
                            },
                            "recorded_at": receipt,
                        }
                        report["pages"].append(page)
                        if (
                            mode == "sequence"
                            and values
                            and first != reference
                            and expected_sequence is None
                        ):
                            if flags[0]:
                                report["warnings"].append(
                                    "Requested starting sequence is outside retained history; the device returned its first retained record."
                                )
                            else:
                                raise ValueError(
                                    "ReadRange sequence response did not begin at the requested sequence."
                                )
                        for index, value in enumerate(values):
                            sequence = None if first is None else _sequence(first, index)
                            decoded = _record(
                                value,
                                sequence=sequence,
                                received_at=receipt,
                                zone=zone,
                                fold=request.fold,
                            )
                            encoded_record_bytes += len(
                                json.dumps(decoded, allow_nan=False).encode()
                            )
                            if encoded_record_bytes > MAX_BYTES - 65536:
                                raise ValueError(
                                    "Decoded history report exceeds its2MiB bound; remaining records were not imported."
                                )
                            report["records"].append(decoded)
                        if gap:
                            raise ValueError(
                                "History sequence gap or repeated page; live buffer may have rolled over."
                            )
                        if not values:
                            if flags[2]:
                                raise ValueError(
                                    "Empty ReadRange page claimed moreItems; pagination cannot advance."
                                )
                            report["complete"] = True
                            break
                        next_sequence = None if first is None else _sequence(first, len(values))
                        report["next_cursor"] = (
                            {"mode": "sequence", "reference": next_sequence}
                            if next_sequence is not None
                            else {"mode": "position", "reference": reference + len(values)}
                        )
                        if flags[1]:
                            report["complete"] = True
                            break
                        if len(report["records"]) == request.count:
                            report["truncated"] = True
                            break
                        if next_sequence is None:
                            report["consistency"] = (
                                "Position-only response has no stable sequence anchor; automatic pagination stopped."
                            )
                            raise ValueError(
                                "Position response omitted sequence metadata; continue explicitly with next_cursor if appropriate."
                            )
                        mode, reference, expected_sequence = (
                            "sequence",
                            next_sequence,
                            next_sequence,
                        )
                    else:
                        report["truncated"] = True
                        report["errors"].append(
                            "History page limit reached; use next_cursor for a separate explicit read."
                        )
        except (ValueError, TimeoutError) as exc:
            if not report["pages"]:
                raise ValueError(
                    "BACnet history retrieval failed: " + (str(exc) or type(exc).__name__)
                ) from exc
            report["errors"].append(str(exc) or type(exc).__name__)
            report["truncated"] = True
        with self._lock:
            self._reports[report["id"]] = copy.deepcopy(report)
            while len(self._reports) > 8:
                self._reports.popitem(last=False)
        return report

    @staticmethod
    def _identifier(identifier):
        if (
            not isinstance(identifier, str)
            or len(identifier) != 32
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError("Invalid history capture identifier.")
        return identifier

    def save(self, id):
        id = self._identifier(id)
        with self._lock:
            report = copy.deepcopy(self._reports.get(id))
        with self._capture_lock():
            path = self.directory / ("capture-" + id + ".json")
            if path.exists():
                return self._summary(self.capture(id))
            if report is None:
                raise ValueError("History report is not in this session; read again before saving.")
            raw = json.dumps(
                report, sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
            wrapper = json.dumps(
                {
                    "format": self.profile,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "report": report,
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
            existing = self._capture_files()
            if (
                len(existing) >= MAX_CAPTURES
                or len(wrapper) > MAX_BYTES
                or sum(p.stat().st_size for p in existing) + len(wrapper) > MAX_STORAGE
            ):
                raise ValueError(
                    "Saved history capture capacity reached; no existing evidence was deleted."
                )
            temporary = self.directory / ("." + id + "." + secrets.token_hex(6) + ".tmp")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(wrapper)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.link(temporary, path)
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                temporary.unlink(missing_ok=True)
            return self._summary(report)

    @contextmanager
    def _capture_lock(self):
        flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.directory / ".capture.lock", flags, 0o600)
        with os.fdopen(fd, "a+b") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ValueError("History capture lock must be a regular file.")
            deadline = time.monotonic() + CAPTURE_LOCK_SECONDS
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError(
                            "History capture storage is busy; retry after the current save finishes."
                        ) from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def capture(self, id):
        id = self._identifier(id)
        path = self.directory / ("capture-" + id + ".json")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError as exc:
            raise ValueError("History capture unavailable.") from exc
        except OSError as exc:
            if path.is_symlink():
                raise ValueError("History capture must be a regular file, not a symlink.") from exc
            raise
        with os.fdopen(fd, "rb") as stream:
            information = os.fstat(stream.fileno())
            if not stat.S_ISREG(information.st_mode) or information.st_size > MAX_BYTES:
                raise ValueError("History capture must be a regular file within its size bound.")
            raw_file = stream.read(MAX_BYTES + 1)
        if len(raw_file) > MAX_BYTES:
            raise ValueError("History capture exceeds its bound.")
        try:
            wrapper = json.loads(raw_file)
        except RecursionError as exc:
            raise ValueError("Saved history capture JSON exceeds the nesting profile.") from exc
        if not isinstance(wrapper, dict):
            raise ValueError("Saved history capture metadata is invalid.")
        report = wrapper.get("report")
        try:
            raw = json.dumps(
                report, sort_keys=True, allow_nan=False, separators=(",", ":")
            ).encode()
        except RecursionError as exc:
            raise ValueError("Saved history report exceeds the nesting profile.") from exc
        if (
            wrapper.get("format") != self.profile
            or wrapper.get("sha256") != hashlib.sha256(raw).hexdigest()
            or not isinstance(report, dict)
            or report.get("id") != id
            or report.get("source_kind") != self.source_kind
            or report.get("profile") != self.profile
            or not isinstance(report.get("records"), list)
            or len(report["records"]) > 1000
            or any(not isinstance(record, dict) for record in report["records"])
            or any(
                type(report.get(key)) is not typ
                for key, typ in (
                    ("target", dict),
                    ("read_at", str),
                    ("received_at", str),
                    ("complete", bool),
                    ("truncated", bool),
                )
            )
        ):
            raise ValueError("Saved history capture integrity check failed.")
        return report

    @staticmethod
    def _summary(report):
        return {
            key: report[key]
            for key in (
                "id",
                "target",
                "read_at",
                "received_at",
                "complete",
                "truncated",
                "source_kind",
            )
        } | {
            "records": len(report["records"]),
            "sha256": hashlib.sha256(
                json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    def captures(self):
        return [
            self._summary(self.capture(path.stem.removeprefix("capture-")))
            for path in self._capture_files()
        ]

    def _capture_files(self):
        paths, total = [], 0
        for path in self.directory.glob("capture-*.json"):
            information = path.lstat()
            if not stat.S_ISREG(information.st_mode):
                raise ValueError("History capture inventory contains a nonregular file.")
            total += information.st_size
            paths.append(path)
            if len(paths) > MAX_CAPTURES or total > MAX_STORAGE:
                raise ValueError("History capture inventory exceeds the configured capacity.")
        return sorted(paths)
