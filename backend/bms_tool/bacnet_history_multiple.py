"""Explicit standard Trend Log Multiple reads, with native channel evidence."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import secrets
from collections import OrderedDict
from datetime import UTC, datetime

from bacpypes3.apdu import ErrorPDU, ErrorRejectAbortNack, ReadRangeACK, ReadRangeRequest
from bacpypes3.basetypes import (
    DateTime,
    DeviceObjectPropertyReference,
    LogMultipleRecord,
    Range,
    RangeByPosition,
    RangeBySequenceNumber,
    RangeByTime,
)
from bacpypes3.constructeddata import ListOf
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import Field, field_validator, model_validator

from .bacnet_exchange import confirmed_exchange
from .bacnet_history import (
    MAX_BYTES,
    MAX_PAGES,
    UINT32,
    BacnetHistory,
    BacnetHistoryRequest,
    _clock,
    _sequence,
    _timezone_provenance,
    _zone,
)
from .bacnet_values import json_value
from .device_details import DeviceDetails, DeviceDetailsRequest, _InterfaceChanged
from .models import StrictModel

PROFILE = "bacnet-trend-log-multiple-history/1"
SCOPE = "Read-only standard BACnet Trend Log Multiple ReadRange; native channels and timestamp choices, not proprietary JCI history or a device/program backup."
MAX_CHANNELS = 32
MAX_PAGE_BYTES = 256 * 1024


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class MultipleHistoryRequest(BacnetHistoryRequest, DeviceDetailsRequest):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
    device_timezone: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("object_id")
    @classmethod
    def trend_log_only(cls, value):
        obj = ObjectIdentifier(value)
        if int(obj[0]) != 27 or not 0 <= obj[1] <= 4194302:
            raise ValueError("This profile reads actual standard trend-log-multiple objects only.")
        return str(obj)

    @field_validator("device_timezone")
    @classmethod
    def installed_zone(cls, value):
        if value is not None:
            _zone(value)
        return value

    @model_validator(mode="after")
    def range_parameters(self):
        if self.mode == "time" and self.device_timezone is None:
            raise ValueError("Time-based ranges require the explicit device clock timezone.")
        super().range_parameters()
        if self.mode == "sequence" and self.reference == 0:
            raise ValueError("This forward sequence profile requires a sequence in 1..4294967295.")
        return self


class MultipleHistoryCancel(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class UndecodableHistoryPage(ValueError):
    """A verified native ACK whose bounded record tags cannot be decoded safely."""

    def __init__(self, evidence, *, raw_tags):
        super().__init__(evidence["error"])
        self.evidence = evidence
        self.raw_tags = raw_tags


def _record(native, *, sequence, received_at, zone, fold, references):
    raw = json_value(native)
    if zone is None:
        local = {"date": list(native.timestamp.date), "time": list(native.timestamp.time)}
        source_clock, timestamp_error = (
            None,
            "Device timezone was not supplied; native timestamp is unresolved.",
        )
    else:
        local, source_clock, timestamp_error = _clock(native.timestamp, zone, fold)
    kind = native.logData._choice
    result = {
        "sequence": sequence,
        "local_timestamp": local,
        "source_clock": source_clock,
        "recorded_at": received_at,
        "timestamp_error": timestamp_error,
        "datum_type": kind,
        "quality": "unknown",
        "quality_basis": "LogMultipleRecord supplies no per-channel historical status flags or reliability.",
        "channels": [],
        "raw": raw,
    }
    if kind == "logData":
        values = list(native.logData.logData)
        if len(values) > MAX_CHANNELS:
            raise ValueError("Trend Log Multiple record exceeds the 32-channel result profile.")
        aligned = bool(references) and len(values) == len(references)
        result["channel_count"] = len(values)
        result["current_reference_count"] = len(references) or None
        result["reference_alignment"] = (
            "current-count-matches; historical identity unverified"
            if aligned
            else "current-count-mismatch; references not bound to historical channels"
            if references
            else "current-reference-metadata-unavailable"
        )
        for index, value in enumerate(values, 1):
            datum = value._choice
            result["channels"].append(
                {
                    "index": index,
                    "reference": copy.deepcopy(references.get(index)) if aligned else None,
                    "reference_basis": "Current property reference acquired with this read, not proof of historical channel identity.",
                    "datum_type": datum,
                    "raw": json_value(value),
                    "quality": "fault" if datum == "failure" else "unknown",
                    "quality_basis": "Native failure datum"
                    if datum == "failure"
                    else "No per-channel historical quality/status flags supplied.",
                }
            )
    elif kind == "logStatus":
        bits = list(native.logData.logStatus)
        if len(bits) != 3:
            raise ValueError("Native LogStatus requires exactly three bits.")
        result["log_status"] = dict(
            zip(("log_disabled", "buffer_purged", "log_interrupted"), map(bool, bits), strict=True)
        )
    elif kind == "timeChange":
        result["time_change"] = json_value(native.logData.timeChange)
        result["meaning"] = "Logged device clock adjustment; not process channels."
    else:
        raise ValueError("Unresolved LogMultipleRecord logData choice.")
    return result


class MultipleHistory(BacnetHistory):
    profile = PROFILE
    scope = SCOPE
    request_type = MultipleHistoryRequest
    record_type = LogMultipleRecord
    record_decoder = staticmethod(_record)
    consistency = "Native order retained; sequence-anchored continuation when supplied. No atomic snapshot or historical channel mapping is implied."
    source_kind = "device-history-trend-log-multiple"
    storage_name = "bacnet-history-multiple"

    def __init__(self, bacnet, store=None, *, timeout=1.5, operation_timeout=15, request_gap=0.05):
        super().__init__(bacnet, store, timeout=timeout, operation_timeout=operation_timeout)
        self.path = DeviceDetails(
            bacnet,
            store,
            timeout=timeout,
            operation_timeout=operation_timeout,
            request_gap=request_gap,
        )
        self._active = None
        self._cancelled = OrderedDict()

    def status(self):
        result = super().status()
        result.update(
            profile=self.profile,
            scope=self.scope,
            source_kind=self.source_kind,
            active_operation=None if self._active is None else self._active["operation_id"],
        )
        result["limits"].update(channels=MAX_CHANNELS, page_bytes=MAX_PAGE_BYTES)
        return result

    def cancel(self, operation_id, *, reason="cancelled"):
        MultipleHistoryCancel(operation_id=operation_id)
        self._cancelled[operation_id] = True
        while len(self._cancelled) > 64:
            self._cancelled.popitem(last=False)
        found = self._active is not None and self._active["operation_id"] == operation_id
        if found:
            self._active["cancel_reason"] = reason
            self._active["task"].cancel()
        return {"operation_id": operation_id, "cancel_requested": found}

    async def close(self):
        active = self._active
        if active is not None:
            self.cancel(active["operation_id"], reason="interface_changed")
            if active["task"] is not asyncio.current_task():
                await asyncio.gather(active["task"], return_exceptions=True)

    async def _identities(self, session, request, report):
        identity = await self.path._read(session, request.device, "object-identifier")
        report["device_identity"] = {"raw": json_value(identity), "received_at": _utc()}
        if identity != ObjectIdentifier(request.device):
            raise ValueError("Selected Device identity mismatch.")
        report["identity_verified"] = True
        obj = await self.path._read(session, request.object_id, "object-identifier")
        report["object_identity"] = {"raw": json_value(obj), "received_at": _utc()}
        if obj != ObjectIdentifier(request.object_id):
            raise ValueError("Selected history object identity mismatch.")

    async def _metadata(self, session, request, report):
        await self._identities(session, request, report)
        properties = report["metadata"]
        for prop in (
            "object-name",
            "record-count",
            "total-record-count",
            "buffer-size",
            "logging-type",
            "log-interval",
        ):
            try:
                value = await self.path._read(session, request.object_id, prop)
                properties[prop] = {
                    "status": "acquired",
                    "raw": json_value(value),
                    "received_at": _utc(),
                }
            except _InterfaceChanged:
                raise
            except (ValueError, TimeoutError, ErrorRejectAbortNack) as exc:
                properties[prop] = {
                    "status": "unavailable",
                    "error": str(exc),
                    "received_at": _utc(),
                }
        references = {}
        try:
            count = await self.path._read(
                session, request.object_id, "log-device-object-property", 0
            )
            report["channel_reference_length_evidence"] = {
                "raw": json_value(count),
                "received_at": _utc(),
            }
            if type(count) is bool or not isinstance(count, int) or not 0 <= count <= MAX_CHANNELS:
                raise ValueError(
                    "Current channel reference array exceeds the 32-channel profile or has invalid length."
                )
            report["channel_reference_count"] = int(count)
            for index in range(1, count + 1):
                try:
                    value = await self.path._read(
                        session, request.object_id, "log-device-object-property", index
                    )
                    row = {
                        "index": index,
                        "status": "acquired",
                        "raw": json_value(value),
                        "received_at": _utc(),
                    }
                    if not isinstance(value, DeviceObjectPropertyReference):
                        raise ValueError(
                            "Current channel reference has an unexpected native datatype."
                        )
                    if value.objectIdentifier[1] == 4194303 or (
                        value.deviceIdentifier is not None and value.deviceIdentifier[1] == 4194303
                    ):
                        row["status"] = "uninitialized"
                except _InterfaceChanged:
                    raise
                except (ValueError, TimeoutError, ErrorRejectAbortNack) as exc:
                    row = {
                        "index": index,
                        "status": "unavailable",
                        "error": str(exc),
                        "received_at": _utc(),
                    }
                references[index] = row
                report["channel_references"].append(row)
        except _InterfaceChanged:
            raise
        except (ValueError, TimeoutError, ErrorRejectAbortNack) as exc:
            report["warnings"].append("Current channel references unavailable: " + str(exc))
        return references

    async def _verify_references(self, session, request, report, before):
        if report["channel_reference_count"] is None:
            report["channel_reference_consistency"] = "unavailable"
            return
        after = {"count": None, "references": [], "started_at": _utc()}
        report["channel_reference_recheck"] = after
        try:
            count = await self.path._read(
                session, request.object_id, "log-device-object-property", 0
            )
            after["count_raw"] = json_value(count)
            if not isinstance(count, int) or type(count) is bool or not 0 <= count <= MAX_CHANNELS:
                raise ValueError("Rechecked reference array count exceeds the bounded profile.")
            after["count"] = int(count)
            for index in range(1, count + 1):
                value = await self.path._read(
                    session, request.object_id, "log-device-object-property", index
                )
                if not isinstance(value, DeviceObjectPropertyReference):
                    raise ValueError("Rechecked channel reference has an unexpected datatype.")
                after["references"].append(
                    {"index": index, "raw": json_value(value), "received_at": _utc()}
                )
            coherent = count == report["channel_reference_count"] and all(
                before.get(row["index"], {}).get("status") in ("acquired", "uninitialized")
                and before[row["index"]]["raw"] == row["raw"]
                for row in after["references"]
            )
            report["channel_reference_consistency"] = (
                "unchanged-current-snapshots" if coherent else "changed-or-unverifiable"
            )
            if not coherent:
                report["warnings"].append(
                    "Current channel references changed or could not be verified across acquisition; references were not assigned to historical channels."
                )
        except _InterfaceChanged:
            raise
        except (ValueError, ErrorRejectAbortNack, TimeoutError) as exc:
            after["error"] = str(exc) or type(exc).__name__
            report["channel_reference_consistency"] = "recheck-unavailable"
            report["warnings"].append(
                "Current reference recheck unavailable; historical channel references remain unresolved."
            )
        finally:
            after["finished_at"] = _utc()

    async def _multiple_page(self, session, request, mode, reference, reference_time, count):
        self.path._guard(session)
        delay = self.path.request_gap - (
            asyncio.get_running_loop().time() - session["last_request"]
        )
        if delay > 0:
            await asyncio.sleep(delay)
        session["last_request"] = asyncio.get_running_loop().time()
        self.path._guard(session)
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
        native = ReadRangeRequest(
            objectIdentifier=request.object_id,
            propertyIdentifier="log-buffer",
            range=selection,
            destination=session["target"],
        )
        try:
            reply = await asyncio.wait_for(confirmed_exchange(session["app"], native), self.timeout)
        except ErrorRejectAbortNack as exc:
            if (
                exc.pduSource != session["target"]
                or exc.apduInvokeID != native.apduInvokeID
                or (isinstance(exc, ErrorPDU) and exc.apduService != native.apduService)
            ):
                raise ValueError(
                    "Native history rejection source/invoke/service mismatch."
                ) from exc
            raise ValueError("Native history ReadRange rejected: " + str(exc)) from exc
        self.path._guard(session)
        if (
            not isinstance(reply, ReadRangeACK)
            or reply.pduSource != session["target"]
            or reply.apduInvokeID != native.apduInvokeID
            or reply.apduService != native.apduService
            or reply.objectIdentifier != ObjectIdentifier(request.object_id)
            or str(reply.propertyIdentifier) != "log-buffer"
            or reply.propertyArrayIndex is not None
        ):
            raise ValueError("Native history ACK source/invoke/service/object/property mismatch.")
        encoded = bytes(reply.encode().encode().pduData)
        if len(encoded) > MAX_PAGE_BYTES or int(reply.itemCount) > count:
            raise ValueError("Native history page exceeds request/byte bounds.")
        flags = list(reply.resultFlags)
        if len(flags) != 3 or (flags[1] and flags[2]):
            raise ValueError("Invalid forward ReadRange result flags.")
        first = None if reply.firstSequenceNumber is None else int(reply.firstSequenceNumber)
        if first is not None and not 0 <= first <= UINT32:
            raise ValueError("Native sequence metadata exceeds Unsigned32.")
        if reply.itemCount and (
            (first is not None and first == 0) or (mode != "position" and first is None)
        ):
            raise ValueError(
                "Populated sequence/time page requires an actual native sequence anchor."
            )
        if (
            mode == "sequence"
            and reply.itemCount
            and ((first - reference) % UINT32 + int(reply.itemCount) > count)
        ):
            raise ValueError(
                "Native history page falls outside the requested forward sequence window."
            )
        values = self._decode_records(reply, encoded)
        if len(values) != int(reply.itemCount):
            raise ValueError("Native history itemCount differs from decoded records.")
        return values, first, flags, encoded, native.apduInvokeID

    def _decode_records(self, reply, encoded):
        return reply.itemData.cast_out(ListOf(self.record_type))

    def _failure_text(self, exc):
        return str(exc) or type(exc).__name__

    def _metadata_fields(self):
        return {
            "metadata": {},
            "channel_references": [],
            "channel_reference_count": None,
            "channel_reference_consistency": "not-checked",
            "channel_reference_basis": "Current references only. Historical channel assignments cannot be established from LogMultipleRecord.",
        }

    def _cleanup_report(self, report):
        if report["channel_reference_consistency"] != "unchanged-current-snapshots":
            for row in report["records"]:
                for channel in row["channels"]:
                    channel["reference"] = None
                if row["channels"]:
                    row["reference_alignment"] = (
                        "current-reference-coherence-unverified; no historical reference assignment"
                    )

    async def read(self, **parameters):
        request = self.request_type(**parameters)
        if self._active is not None:
            raise ValueError("A native history read is already running.")
        if request.operation_id in self._cancelled:
            raise ValueError("Read was cancelled before admission; use a new operation_id.")
        active = {
            "operation_id": request.operation_id,
            "task": asyncio.current_task(),
            "cancel_reason": None,
        }
        self._active = active
        report = {
            "id": secrets.token_hex(16),
            "profile": self.profile,
            "scope": self.scope,
            "source_kind": self.source_kind,
            "request": request.model_dump(mode="json"),
            "target": {
                key: getattr(request, key)
                for key in ("address", "device", "router", "dnet", "object_id")
            },
            "read_at": _utc(),
            "received_at": _utc(),
            "identity_verified": False,
            **self._metadata_fields(),
            "timezone": None
            if request.device_timezone is None
            else _timezone_provenance(request.device_timezone),
            "timestamp_basis": "Native BACnet date/time fields retained; no UTC conversion without an explicitly supplied timezone.",
            "records": [],
            "pages": [],
            "complete": False,
            "records_complete": False,
            "truncated": False,
            "status": "reading",
            "errors": [],
            "warnings": [],
            "next_cursor": None,
            "consistency": self.consistency,
        }
        mode, reference = request.mode, request.reference
        zone = None if request.device_timezone is None else _zone(request.device_timezone)
        reference_time = (
            None
            if request.reference_time is None
            else request.reference_time.astimezone(zone).replace(tzinfo=None)
        )
        expected, session = None, None
        try:
            async with asyncio.timeout(self.operation_timeout):
                async with self.path._path(
                    DeviceDetailsRequest(
                        **{
                            key: getattr(request, key)
                            for key in ("address", "device", "router", "dnet")
                        }
                    )
                ) as session:
                    report["connector_config"] = copy.deepcopy(session["config"])
                    refs = await self._metadata(session, request, report)
                    while (
                        len(report["records"]) < request.count and len(report["pages"]) < MAX_PAGES
                    ):
                        count = min(request.page_size, request.count - len(report["records"]))
                        values, first, flags, encoded, invoke = await self._multiple_page(
                            session, request, mode, reference, reference_time, count
                        )
                        received = _utc()
                        if values and expected is not None and first != expected:
                            raise ValueError(
                                "Repeated/stale page or sequence gap; the new page was not imported."
                            )
                        if mode == "sequence" and values and first != reference:
                            if flags[0] and expected is None:
                                report["warnings"].append(
                                    "Starting sequence is outside retained history; first retained record returned."
                                )
                            else:
                                raise ValueError(
                                    "Native page did not begin at the requested sequence."
                                )
                        if not values and flags[2]:
                            raise ValueError(
                                "Empty native page claimed moreItems; pagination cannot advance."
                            )
                        decoded = [
                            self.record_decoder(
                                value,
                                sequence=None if first is None else _sequence(first, index),
                                received_at=received,
                                zone=zone,
                                fold=request.fold,
                                references=refs,
                            )
                            for index, value in enumerate(values)
                        ]
                        page = {
                            "mode": mode,
                            "reference": reference,
                            "count": len(values),
                            "first_sequence": first,
                            "result_flags": dict(
                                zip(
                                    ("first_item", "last_item", "more_items"),
                                    map(bool, flags),
                                    strict=True,
                                )
                            ),
                            "received_at": received,
                            "invoke_id": invoke,
                            "decoded_ack_sha256": hashlib.sha256(encoded).hexdigest(),
                            "ack_bytes": len(encoded),
                        }
                        if (
                            len(_bytes(report)) + len(_bytes(decoded)) + len(_bytes(page))
                            > MAX_BYTES - 65536
                        ):
                            raise ValueError(
                                "Native history report exceeds the 2 MiB capture profile; page not imported."
                            )
                        report["records"].extend(decoded)
                        report["pages"].append(page)
                        report["received_at"] = received
                        if not values or flags[1]:
                            report.update(
                                complete=True,
                                records_complete=True,
                                status="complete",
                                next_cursor=None,
                            )
                            break
                        next_sequence = None if first is None else _sequence(first, len(values))
                        report["next_cursor"] = (
                            {"mode": "sequence", "reference": next_sequence}
                            if next_sequence is not None
                            else {"mode": "position", "reference": reference + len(values)}
                        )
                        if len(report["records"]) >= request.count:
                            report.update(truncated=True, status="bounded")
                            break
                        if next_sequence is None:
                            raise ValueError(
                                "Position-only response has no stable sequence anchor; automatic pagination stopped."
                            )
                        mode, reference, expected = "sequence", next_sequence, next_sequence
                    else:
                        report.update(truncated=True, status="bounded")
                        report["errors"].append(
                            "Page bound reached; continue only with an explicit new read."
                        )
                    await self._verify_references(session, request, report, refs)
        except UndecodableHistoryPage as exc:
            report.update(
                status="partial" if report["pages"] else "unsupported_native_records",
                truncated=True,
                complete=False,
            )
            tags = exc.evidence["item_data_tags"]
            raw = exc.raw_tags
            # Enforce the report budget before expanding the bounded native
            # ACK tags to base64. Preserve a labelled prefix and full hash
            # when previously acquired records leave insufficient room.
            expanded_bytes = 4 * ((len(raw) + 2) // 3)
            if len(_bytes(report)) + len(_bytes(exc.evidence)) + expanded_bytes > MAX_BYTES - 8192:
                raw = raw[:3072]
                tags["truncated"] = True
            tags["base64"] = base64.b64encode(raw).decode("ascii")
            report["undecoded_pages"] = [exc.evidence]
            report["errors"].append(self._failure_text(exc))
        except asyncio.CancelledError:
            if active["cancel_reason"] is None:
                raise
            report.update(status=active["cancel_reason"], truncated=True, complete=False)
            report["errors"].append("Read cancelled; completed pages remain evidence.")
        except (
            ValueError,
            TimeoutError,
            OSError,
            ErrorRejectAbortNack,
            DecodingError,
            InvalidTag,
            TypeError,
            AttributeError,
        ) as exc:
            report.update(
                status="partial" if report["pages"] else "failed", truncated=True, complete=False
            )
            report["errors"].append(self._failure_text(exc))
        finally:
            if session is not None:
                report["ignored_router_packets"] = session.get("ignored_router_packets", 0)
            self._cleanup_report(report)
            if self._active is active:
                self._active = None
        report["finished_at"] = _utc()
        report["evidence_sha256"] = hashlib.sha256(_bytes(report)).hexdigest()
        with self._lock:
            self._reports[report["id"]] = copy.deepcopy(report)
            while len(self._reports) > 8:
                self._reports.popitem(last=False)
        return report
