"""Shared strict, bounded, source-pinned read-only native property evidence.

Callers own identity policy, finite operation, lifecycle, object-class profile and
report storage. This reader only sends owned single-attempt ReadProperty calls.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from bacpypes3.apdu import APDU, ErrorRejectAbortNack, ReadPropertyACK, ReadPropertyRequest
from bacpypes3.constructeddata import AnyAtomic, Array, Sequence
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, IPv4Address
from bacpypes3.primitivedata import (
    Date,
    Enumerated,
    Null,
    ObjectIdentifier,
    PropertyIdentifier,
    TagList,
    Time,
    Unsigned,
)

from .bacnet_exchange import confirmed_exchange
from .bacnet_values import json_value
from .device_details import _InterfaceChanged
from .scoped_hooks import ScopedAttribute

MAX_VALUE_BYTES = 16 * 1024


def _utc():
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


@dataclass
class ReadBudget:
    max_requests: int = 1024
    max_bytes: int = 2 * 1024 * 1024 - 128 * 1024
    requests: int = 0
    retained_bytes: int = 0
    ignored_peers: int = 0
    last_omitted: dict | None = None

    def snapshot(self):
        return {
            "requests": self.requests,
            "retained_property_bytes": self.retained_bytes,
            "ignored_transport_candidates": self.ignored_peers,
            **(
                {"last_omitted_property": copy.deepcopy(self.last_omitted)}
                if self.last_omitted
                else {}
            ),
        }


def native_value(value, issues, path="$", depth=0, remaining=None):
    remaining = [4096] if remaining is None else remaining
    remaining[0] -= 1
    if depth > 16 or remaining[0] < 0:
        raise ValueError("Native value exceeds the 16-level/4096-item profile.")
    if isinstance(value, AnyAtomic):
        evidence = json_value(value)
        try:
            primitive = value.get_value()
            return {
                "native_datatype": type(primitive).__name__,
                "value": json_value(primitive),
                "encoded": evidence,
            }
        except Exception as exc:
            error = str(exc)[:300] or type(exc).__name__
            if len(issues) < 32:
                issues.append({"path": path, "error": error})
            return {
                "native_datatype": "AnyAtomic",
                "decode_status": "opaque",
                "encoded": evidence,
                "error": error,
            }
    if isinstance(value, Null):
        return None
    if isinstance(value, ObjectIdentifier):
        return {
            "native_datatype": "ObjectIdentifier",
            "value": str(value),
            "object_type": int(value[0]),
            "instance": int(value[1]),
        }
    if isinstance(value, (Date, Time)):
        return {"native_datatype": type(value).__name__, "fields": list(value)}
    if isinstance(value, Enumerated):
        return {
            "native_datatype": type(value).__name__,
            "value": int(value),
            "name": str(value),
            "known": int(value) in type(value)._enum_map.values(),
        }
    if isinstance(value, Sequence):
        choice = getattr(value, "_choice", None)
        if choice:
            return {
                "type": choice,
                "value": native_value(
                    getattr(value, choice), issues, path + "." + choice, depth + 1, remaining
                ),
            }
        return {
            name: native_value(
                getattr(value, name), issues, path + "." + name, depth + 1, remaining
            )
            for name in value._elements
            if getattr(value, name, None) is not None
        }
    if isinstance(value, (list, tuple)):
        return [
            native_value(item, issues, f"{path}[{index}]", depth + 1, remaining)
            for index, item in enumerate(value)
        ]
    return json_value(value)


class PropertyEvidence:
    def __init__(self, path):
        self.path = path

    @staticmethod
    def pin(session, router):
        adapter = session["app"].nsap.local_adapter
        session.update(
            evidence_router=router,
            evidence_adapter=adapter,
            evidence_layer=adapter.clientPeer,
            evidence_socket=adapter.clientPeer.server.local_transport,
        )

    def guard(self, session):
        self.path._guard(session)
        if "evidence_adapter" in session:
            adapter = session["app"].nsap.local_adapter
            if (
                adapter is not session["evidence_adapter"]
                or adapter.clientPeer is not session["evidence_layer"]
                or adapter.clientPeer.server.local_transport is not session["evidence_socket"]
            ):
                raise _InterfaceChanged("Read-only property interface/socket identity changed.")

    @asynccontextmanager
    async def wire(self, session, budget, request):
        layer = session["app"].nsap.local_adapter.clientPeer
        mux = layer.multiplexer
        original = mux.confirmation
        expected_peer = session.get("evidence_router") or str(session["target"])
        local_endpoint = layer.server.local_transport.get_extra_info("sockname")
        evidence = {}
        listening = True

        def inspect_packet(packet):
            raw = bytes(packet.pduData)
            try:
                if len(raw) < 6 or raw[0] != 0x81 or raw[1] not in (4, 10, 11):
                    return False
                offset = 10 if raw[1] == 4 else 4
                npdu = NPDU.decode(PDU(raw[offset:]))
                if npdu.npduNetMessage is not None:
                    return False
                header = APDU.decode(PDU(bytes(npdu.pduData)))
                if (
                    header.apduType not in (3, 5, 6, 7)
                    or header.apduInvokeID != request.apduInvokeID
                ):
                    return False
                if header.apduType in (3, 5) and header.apduService != 12:
                    return False
                advertised = IPv4Address(raw[4:10]) if raw[1] == 4 else packet.pduSource
                source = npdu.npduSADR if npdu.npduSADR is not None else advertised
                if source != session["target"]:
                    return False
                if (
                    raw[1] != 10
                    or str(packet.pduSource) != expected_peer
                    or getattr(packet.pduDestination, "addrTuple", None) != local_endpoint
                ):
                    budget.ignored_peers += 1
                    return True
                self.guard(session)
                evidence.clear()
                evidence.update(
                    received_at=_utc(),
                    next_hop=str(packet.pduSource),
                    local_endpoint=list(local_endpoint),
                    npdu_source=str(npdu.npduSADR) if npdu.npduSADR else None,
                    udp_payload_hex=raw[:4096].hex(),
                    udp_payload_bytes=len(raw),
                    udp_payload_sha256=hashlib.sha256(raw).hexdigest(),
                    raw_complete=len(raw) <= 4096,
                    basis="Matching transport candidate; only a validated transaction response is accepted.",
                )
            except Exception:
                return False
            return False

        async def receive(packet):
            if listening and inspect_packet(packet):
                return
            # Dispatch the original exactly once, even if its handler raises.
            return await original(packet)

        hook = ScopedAttribute(mux, "confirmation", receive)
        try:
            yield evidence
        finally:
            listening = False
            hook.close()

    async def read(
        self, session, budget, obj, prop, object_class, index=None, *, timeout=1.0, request_gap=0.02
    ):
        self.guard(session)
        if budget.requests >= budget.max_requests:
            raise ValueError("Inventory request capacity reached.")
        delay = request_gap - (asyncio.get_running_loop().time() - session["last_request"])
        if delay > 0:
            await asyncio.sleep(delay)
        self.guard(session)
        session["last_request"] = asyncio.get_running_loop().time()
        budget.requests += 1
        identifier, property_id = ObjectIdentifier(obj), PropertyIdentifier(prop)
        row = {
            "object": str(identifier),
            "property": str(property_id),
            "property_id": int(property_id),
            "array_index": index,
            "requested_at": _utc(),
            "status": "not_read",
        }
        request = ReadPropertyRequest(
            objectIdentifier=identifier,
            propertyIdentifier=property_id,
            destination=session["target"],
        )
        if index is not None:
            request.propertyArrayIndex = index
        native = None
        try:
            async with self.wire(session, budget, request) as wire:
                try:
                    reply = await asyncio.wait_for(
                        confirmed_exchange(session["app"], request, single_attempt=True),
                        timeout,
                    )
                finally:
                    if wire:
                        row["transport_evidence"] = copy.deepcopy(wire)
            self.guard(session)
            if isinstance(reply, ErrorRejectAbortNack):
                raise reply
            if (
                not isinstance(reply, ReadPropertyACK)
                or reply.pduSource != session["target"]
                or reply.objectIdentifier != identifier
                or reply.propertyIdentifier != property_id
                or reply.propertyArrayIndex != index
            ):
                raise ValueError(
                    "ReadProperty acknowledgement source/object/property/index mismatch."
                )
            raw = bytes(reply.propertyValue.tagList.encode().pduData)
            row.update(
                received_at=_utc(),
                invoke_id=request.apduInvokeID,
                encoded_value={
                    "hex": raw[:MAX_VALUE_BYTES].hex(),
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "complete": len(raw) <= MAX_VALUE_BYTES,
                    "encoding": "BACpypes3 property-tag re-encoding; not a packet-capture hash",
                },
            )
            if len(raw) > MAX_VALUE_BYTES:
                raise ValueError("Native property exceeds the 16 KiB value profile.")
            tags = TagList(list(reply.propertyValue.tagList))
            # A few native Any decoders tolerate incomplete nesting. Validate
            # structural bounds before interpreting nested native choices.
            if len(tags) > 4096:
                raise ValueError("Native property exceeds the 4096-tag profile.")
            stack = []
            for tag in tags:
                if tag.tag_class == 2:
                    stack.append(tag.tag_number)
                    if len(stack) > 16:
                        raise ValueError("Native property nesting exceeds 16 levels.")
                elif tag.tag_class == 3:
                    if not stack or stack.pop() != tag.tag_number:
                        raise ValueError("Unbalanced native closing tag.")
            if stack:
                raise ValueError("Unclosed native property tag.")
            if (
                len(tags) < 2
                or tags[0].tag_class != 2
                or tags[0].tag_number != 3
                or tags[-1].tag_class != 3
                or tags[-1].tag_number != 3
            ):
                raise ValueError("PropertyValue context-3 envelope is missing.")
            tags = TagList(list(tags)[1:-1])
            datatype = object_class.get_property_type(property_id)
            if datatype is None:
                raise ValueError(
                    "No standard native datatype for this property; evidence retained."
                )
            if issubclass(datatype, Array) and index is not None:
                datatype = Unsigned if index == 0 else datatype._subtype
            # Explicit remaining-tag checks avoid silently accepting concatenated
            # or malformed values that the native convenience API can ignore.
            native = datatype.decode(tags)
            if len(tags):
                raise ValueError("Trailing unmatched native property tags.")
            issues = []
            row.update(
                status="partial" if issues else "ok",
                datatype=datatype.__name__,
                value=native_value(native, issues),
                nested_decode_errors=issues,
            )
            if issues:
                row["status"] = "partial"
        except TimeoutError:
            row.update(status="timeout", error="No attributable property response before deadline.")
        except ErrorRejectAbortNack as exc:
            row.update(
                status="native_error", error=str(exc)[:1000], native_error_type=type(exc).__name__
            )
            row["native_error"] = {
                name: native_value(getattr(exc, name), [])
                for name in ("errorClass", "errorCode", "apduAbortRejectReason", "apduService")
                if getattr(exc, name, None) is not None
            }
        except _InterfaceChanged:
            raise
        except Exception as exc:
            row.update(
                status="decode_error" if "encoded_value" in row else "protocol_error",
                error=str(exc)[:1000] or type(exc).__name__,
            )
            native = None
        row["invoke_id"] = request.apduInvokeID
        if len(_encoded(row)) > 64 * 1024:
            row.pop("value", None)
            row.update(
                status="limit_exceeded",
                error="Decoded property exceeds its 64 KiB evidence profile.",
            )
            native = None
        size = len(_encoded(row))
        if budget.retained_bytes + size > budget.max_bytes:
            budget.last_omitted = {
                "object": str(identifier),
                "property": str(property_id),
                "array_index": index,
                "reason": "Report evidence capacity reached; this response was not retained.",
            }
            raise ValueError(
                "Inventory report evidence capacity reached; completed reads retained."
            )
        budget.retained_bytes += size
        return native, row
