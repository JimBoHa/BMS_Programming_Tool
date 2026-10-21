"""Native recorded Event Log history, independent of operator alarm delivery."""

from __future__ import annotations

import hashlib

from bacpypes3.basetypes import EventLogRecord
from bacpypes3.errors import DecodingError, InvalidTag
from bacpypes3.primitivedata import ObjectIdentifier
from pydantic import field_validator

from .bacnet_history import _clock
from .bacnet_history_multiple import (
    MultipleHistory,
    MultipleHistoryRequest,
    UndecodableHistoryPage,
    _bytes,
    _utc,
)
from .bacnet_values import json_value
from .device_details import _InterfaceChanged

PROFILE = "bacnet-event-log-history/1"
SCOPE = "Explicit read-only standard BACnet Event Log ReadRange. Recorded native notifications do not establish human receipt, alarm delivery, acknowledgement lifecycle, resolution, or proprietary JCI historian access."
CONFIG_PROPERTIES = (
    "object-name",
    "enable",
    "stop-when-full",
    "buffer-size",
    "status-flags",
    "reliability",
    "notification-class",
    "record-count",
    "total-record-count",
)


def _bounded_error(exc):
    value = str(exc) or type(exc).__name__
    if len(value) <= 2048:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return value[:2048] + " [truncated; full error SHA-256 " + digest + "]"


class EventLogHistoryRequest(MultipleHistoryRequest):
    @field_validator("object_id")
    @classmethod
    def trend_log_only(cls, value):
        obj = ObjectIdentifier(value)
        if int(obj[0]) != 25 or not 0 <= obj[1] <= 4194302:
            raise ValueError("This profile reads actual standard event-log objects only.")
        return str(obj)


def _enum(value):
    if value is None:
        return None
    return {
        "value": int(value),
        "name": str(value),
        "known": int(value) in type(value)._enum_map.values(),
    }


def _record(native, *, sequence, received_at, zone, fold, references):
    raw = json_value(native)
    local = {"date": list(native.timestamp.date), "time": list(native.timestamp.time)}
    if zone is None:
        source_clock, timestamp_error = (
            None,
            "Logger timezone was not supplied; native logger timestamp remains unresolved.",
        )
    else:
        _, source_clock, timestamp_error = _clock(native.timestamp, zone, fold)
    kind = native.logDatum._choice
    row = {
        "sequence": sequence,
        "local_timestamp": local,
        "source_clock": source_clock,
        "recorded_at": received_at,
        "read_received_at": received_at,
        "timestamp_error": timestamp_error,
        "datum_type": kind,
        "quality": "unknown",
        "quality_basis": "A stored notification/log entry does not establish present reliability, delivery or operator receipt.",
        "logger_clock_basis": "Outer EventLogRecord timestamp interpreted only in the explicitly supplied logger timezone.",
        "raw": raw,
    }
    if kind == "notification":
        value = native.logDatum.notification
        row["notification"] = {
            "raw": raw["logDatum"]["value"],
            "process_identifier": int(value.processIdentifier),
            "initiating_device": str(value.initiatingDeviceIdentifier),
            "event_object": str(value.eventObjectIdentifier),
            "notification_class": int(value.notificationClass),
            "priority": int(value.priority),
            "event_type": _enum(value.eventType),
            "notify_type": _enum(value.notifyType),
            "from_state": _enum(value.fromState),
            "to_state": _enum(value.toState),
            "ack_required": None if value.ackRequired is None else bool(value.ackRequired),
            "message_text": None if value.messageText is None else str(value.messageText),
            "event_timestamp": {
                "raw": json_value(value.timeStamp),
                "source_clock_utc": None,
                "basis": "Embedded event-source TimeStamp, preserved independently of logger time; initiating-device timezone/clock unknown.",
            },
            "event_values": None if value.eventValues is None else json_value(value.eventValues),
            "lifecycle_basis": "Native recorded notifyType/state/ackRequired fields only; no human receipt, delivery, resolution or acknowledgement lifecycle inferred.",
        }
    elif kind == "logStatus":
        bits = list(native.logDatum.logStatus)
        row["log_status"] = (
            dict(
                zip(
                    ("log_disabled", "buffer_purged", "log_interrupted"),
                    map(bool, bits),
                    strict=True,
                )
            )
            if len(bits) == 3
            else None
        )
        if len(bits) != 3:
            row["status_decode_error"] = (
                "Nonstandard LogStatus bit count; raw native bits retained without naming them."
            )
    elif kind == "timeChange":
        row["time_change"] = json_value(native.logDatum.timeChange)
        row["meaning"] = "Logged logger clock adjustment; not an alarm notification."
    else:
        raise ValueError("Unresolved native EventLogRecord choice.")
    return row


class EventLogHistory(MultipleHistory):
    profile = PROFILE
    scope = SCOPE
    source_kind = "device-history-event-log"
    storage_name = "bacnet-event-log-history"
    request_type = EventLogHistoryRequest
    record_type = EventLogRecord
    record_decoder = staticmethod(_record)
    _failure_text = staticmethod(_bounded_error)
    consistency = "Native sequence order retained; no atomic log snapshot, historical configuration, notification delivery or human receipt is established."

    def status(self):
        result = super().status()
        result["limits"].pop("channels", None)
        result["unsolicited_subscriptions"] = False
        result["operator_acknowledgement"] = False
        result["device_support"] = (
            "Unknown until explicitly read on the exact device/firmware. Loopback protocol tests do not establish physical support."
        )
        return result

    def _metadata_fields(self):
        return {
            "metadata": {},
            "current_configuration_basis": "Current logger properties acquired at read time, not proven historical source configuration or event delivery/receipt.",
            "current_configuration_consistency": "not-rechecked",
        }

    async def _properties(self, session, request):
        result = {}
        for prop in CONFIG_PROPERTIES:
            try:
                value = await self.path._read(session, request.object_id, prop)
                raw = json_value(value)
                encoded = _bytes(raw)
                if len(encoded) > 4096:
                    result[prop] = {
                        "status": "over_metadata_profile",
                        "received_at": _utc(),
                        "decoded_json_bytes": len(encoded),
                        "sha256": hashlib.sha256(encoded).hexdigest(),
                        "error": "Current metadata value exceeds the 4 KiB profile; no typed value was assigned.",
                    }
                else:
                    result[prop] = {"status": "acquired", "raw": raw, "received_at": _utc()}
            except _InterfaceChanged:
                raise
            except (ValueError, TimeoutError) as exc:
                result[prop] = {
                    "status": "unavailable",
                    "error": _bounded_error(exc),
                    "received_at": _utc(),
                }
        return result

    async def _metadata(self, session, request, report):
        await self._identities(session, request, report)
        report["metadata"] = await self._properties(session, request)
        return {}

    async def _verify_references(self, session, request, report, before):
        after = await self._properties(session, request)
        report["current_configuration_recheck"] = after
        # Record counters naturally change while logging; preserve them without
        # treating new entries as a configuration rewrite or an atomic snapshot.
        config = [
            key
            for key in CONFIG_PROPERTIES
            if key not in ("record-count", "total-record-count", "status-flags", "reliability")
        ]
        coherent = all(
            report["metadata"][key]["status"] == after[key]["status"] == "acquired"
            and report["metadata"][key]["raw"] == after[key]["raw"]
            for key in config
        )
        report["current_configuration_consistency"] = (
            "matching-current-snapshots; historical configuration unproven"
            if coherent
            else "changed-or-unverifiable-current-snapshots"
        )
        if not coherent:
            report["warnings"].append(
                "Current logger configuration changed or was unavailable during acquisition. Historical notification parameters remain raw evidence, not a reconstructed configuration."
            )

    def _cleanup_report(self, report):
        pass

    def _decode_records(self, reply, encoded):
        raw_tags = bytes(reply.itemData.tagList.encode().pduData)
        try:
            values = super()._decode_records(reply, encoded)
            for value in values:
                json_value(value)  # Verify bounded projection before importing any page records.
            return values
        except (DecodingError, InvalidTag, TypeError, AttributeError, ValueError) as exc:
            raise UndecodableHistoryPage(
                {
                    "status": "unsupported-native-record-encoding",
                    "error": "Pinned BACpypes3 EventLogRecord decoder/JSON profile cannot interpret this native page: "
                    + _bounded_error(exc),
                    "item_count": int(reply.itemCount),
                    "first_sequence_number": None
                    if reply.firstSequenceNumber is None
                    else int(reply.firstSequenceNumber),
                    "result_flags": list(reply.resultFlags),
                    "source": str(reply.pduSource),
                    "received_at": _utc(),
                    "decoded_ack_sha256": hashlib.sha256(encoded).hexdigest(),
                    "item_data_tags": {
                        "encoding": "base64",
                        "bytes": len(raw_tags),
                        "sha256": hashlib.sha256(raw_tags).hexdigest(),
                        "truncated": False,
                    },
                    "meaning": "Bounded native itemData tags or an explicitly truncated prefix retained as decoded. No typed notification values or lifecycle were guessed; page records were not imported.",
                },
                raw_tags=raw_tags,
            ) from exc
