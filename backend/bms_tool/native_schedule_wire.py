"""Scoped service-15 response evidence for one owned Schedule write.

This is deliberately separate from PropertyEvidence's service-12 reader. Native
acceptance must match the exact original-unicast datagram on the owned socket;
an ACK is protocol acceptance, never proof of physical or atomic application.
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from bacpypes3.apdu import APDU, APCISequence, ErrorPDU
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU, IPv4Address
from bacpypes3.primitivedata import Enumerated, TagList

from .ipv4_ingress import raw_ingress
from .property_evidence import native_value
from .scoped_hooks import ScopedAttribute


def apdu_bytes(value):
    """Return the full native APDU, including its header, without PCI metadata."""
    result = value.encode()
    if isinstance(result, APDU):
        result = result.encode()
    return bytes(result.pduData)


def response_header(raw, invoke):
    """Accept only the bounded, exact native response forms in this profile."""
    if len(raw) < 3 or raw[1] != invoke:
        raise ValueError("Write response invoke/length mismatch.")
    if raw[0] == 0x20 and len(raw) == 3 and raw[2] == 15:
        pass
    elif raw[0] == 0x50 and raw[2] == 15 and len(raw) <= 32:
        # Error ::= error-class ENUMERATED, error-code ENUMERATED. A successful
        # native decoder alone need not prove exhaustion of trailing tags.
        tags = TagList.decode(PDU(raw[3:]))
        Enumerated.decode(tags)
        Enumerated.decode(tags)
        if tags:
            raise ValueError("Write Error has trailing native tags.")
    elif raw[0] == 0x60 and len(raw) == 3:
        pass
    elif raw[0] == 0x71 and len(raw) == 3:
        # 0x70 is a client-origin Abort. It cannot establish a remote server's
        # rejection, even though the SDK can deliver it as an AbortPDU.
        pass
    else:
        raise ValueError("Unsupported write response type/service/server direction.")
    return APDU.decode(PDU(raw))


class ScheduleWriteWire:
    def __init__(self, reader):
        self.reader = reader

    @asynccontextmanager
    async def receive(self, session, request):
        layer = session["evidence_layer"]
        mux, expected = layer.multiplexer, session.get("evidence_router") or str(session["target"])
        original = mux.confirmation
        proof = {"ignored_candidates": 0, "response": None}
        listening = True

        def inspect(packet):
            data = bytes(packet.pduData)
            matched = False
            try:
                if len(data) < 7 or data[0] != 0x81:
                    return False
                offset = 10 if data[1] == 4 else 4
                npdu = NPDU.decode(PDU(data[offset:]))
                if npdu.npduNetMessage is not None:
                    return False
                raw = bytes(npdu.pduData)
                header = APDU.decode(PDU(raw))
                advertised = IPv4Address(data[4:10]) if data[1] == 4 else packet.pduSource
                source = npdu.npduSADR if npdu.npduSADR is not None else advertised
                if (
                    header.apduType not in (2, 5, 6, 7)
                    or header.apduInvokeID != request.apduInvokeID
                    or source != session["target"]
                ):
                    return False  # unrelated traffic must still reach its owner
                matched = True
                provenance = raw_ingress(layer, packet)
                if (
                    data[1] != 10
                    or int.from_bytes(data[2:4], "big") != len(data)
                    or data[offset + 1] & 0x50
                    or str(packet.pduSource) != expected
                    or provenance is None
                    or npdu.npduDADR is not None
                    or npdu.pduExpectingReply
                ):
                    raise ValueError("Write response does not match pinned raw ingress.")
                response_header(raw, request.apduInvokeID)
                self.reader.guard(session)
                if proof["response"] is None:
                    proof["response"] = {
                        "received_at": datetime.now(UTC).isoformat(timespec="microseconds"),
                        "next_hop": str(packet.pduSource),
                        "npdu_source": str(npdu.npduSADR) if npdu.npduSADR else None,
                        "receive_provenance": provenance,
                        "udp_payload_hex": data.hex(),
                        "udp_payload_bytes": len(data),
                        "udp_payload_sha256": hashlib.sha256(data).hexdigest(),
                        "response_apdu_hex": raw.hex(),
                        "response_apdu_sha256": hashlib.sha256(raw).hexdigest(),
                        "physical_ip_destination": None,
                    }
                return False
            except Exception:
                # A matching but invalid candidate must not complete the native
                # transaction. Other invokes/sources were passed through above.
                if matched:
                    proof["ignored_candidates"] += 1
                return matched

        async def receive(packet):
            if listening and inspect(packet):
                return
            return await original(packet)

        hook = ScopedAttribute(mux, "confirmation", receive)
        try:
            yield proof
        finally:
            listening = False
            hook.close()

    @staticmethod
    def validate(reply, session, request, proof):
        row = proof.get("response")
        if row is None or reply.pduSource != session["target"]:
            raise ValueError("Write response lacks matching owned transport evidence.")
        raw = bytes.fromhex(row["response_apdu_hex"])
        response_header(raw, request.apduInvokeID)
        if (
            reply.apduInvokeID != request.apduInvokeID
            or apdu_bytes(reply) != raw
            or (reply.apduType in (2, 5) and reply.apduService != 15)
            or (reply.apduType == 7 and reply.apduSrv is not True)
        ):
            raise ValueError("Native write response differs from its exact raw evidence.")
        # For Error, independently prove that the native service decoder agrees
        # with the two application enum fields seen on the wire.
        if isinstance(reply, ErrorPDU):
            decoded = APCISequence.decode(APDU.decode(PDU(raw)))
            if apdu_bytes(decoded) != raw:
                raise ValueError("Native write Error did not round-trip exact tags.")
        result = {
            "type": {2: "SimpleACK", 5: "Error", 6: "Reject", 7: "Abort"}[reply.apduType],
            "invoke_id": reply.apduInvokeID,
            "service_choice": reply.apduService if reply.apduType in (2, 5) else None,
            "server_origin": bool(reply.apduSrv) if reply.apduType == 7 else None,
            "source": str(reply.pduSource),
            "raw_proof": row,
        }
        if reply.apduType == 5:
            result.update(
                error_class=native_value(reply.errorClass, []),
                error_code=native_value(reply.errorCode, []),
            )
        elif reply.apduType in (6, 7):
            result["reason"] = native_value(reply.apduAbortRejectReason, [])
        return result
