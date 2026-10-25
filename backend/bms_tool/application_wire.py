"""Original-unicast evidence for owned application-transfer transactions."""

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from bacpypes3.apdu import APDU
from bacpypes3.npdu import NPDU
from bacpypes3.pdu import PDU

from .ipv4_ingress import raw_ingress
from .native_schedule_wire import apdu_bytes
from .property_evidence import PropertyEvidence
from .scoped_hooks import ScopedAttribute


class ApplicationWire:
    def __init__(self, path):
        self.reader = PropertyEvidence(path)

    @asynccontextmanager
    async def receive(self, session, request):
        if "evidence_layer" not in session:
            raise ValueError("Application transfer requires a pinned IPv4 socket and route.")
        layer = session["evidence_layer"]
        mux = layer.multiplexer
        expected_peer = session.get("evidence_router") or str(session["target"])
        original = mux.confirmation
        proof = {"response": None, "ignored_candidates": 0}
        active = True

        def inspect(packet):
            matched = False
            try:
                data = bytes(packet.pduData)
                if len(data) < 7 or data[0] != 0x81:
                    return False
                offset = 10 if data[1] == 4 else 4
                npdu = NPDU.decode(PDU(data[offset:]))
                if npdu.npduNetMessage is not None:
                    return False
                raw = bytes(npdu.pduData)
                header = APDU.decode(PDU(raw))
                source = npdu.npduSADR or packet.pduSource
                if header.apduInvokeID != request.apduInvokeID or source != session["target"]:
                    return False
                matched = True
                ingress = raw_ingress(layer, packet)
                if (
                    data[1] != 10
                    or int.from_bytes(data[2:4], "big") != len(data)
                    or data[offset + 1] & 0x50
                    or npdu.npduDADR is not None
                    or npdu.pduExpectingReply
                    or str(packet.pduSource) != expected_peer
                    or ingress is None
                ):
                    raise ValueError("Application response does not match its raw ingress.")
                if raw[0] in (0x20, 0x30, 0x50):
                    if len(raw) < 3 or raw[2] != request.apduService:
                        raise ValueError("Application response service mismatch.")
                    if raw[0] == 0x20 and len(raw) != 3:
                        raise ValueError("Application SimpleACK has trailing data.")
                elif raw[0] not in (0x60, 0x71) or len(raw) != 3:
                    raise ValueError("Unsupported application response framing.")
                self.reader.guard(session)
                if proof["response"] is None:
                    proof["response"] = {
                        "received_at": datetime.now(UTC).isoformat(),
                        "next_hop": str(packet.pduSource),
                        "source": str(source),
                        "invoke_id": header.apduInvokeID,
                        "service": request.apduService,
                        "response_apdu_hex": raw.hex(),
                        "udp_payload_sha256": hashlib.sha256(data).hexdigest(),
                        "receive_provenance": ingress,
                    }
                return False
            except Exception:
                if matched:
                    proof["ignored_candidates"] += 1
                return matched

        async def receive(packet):
            if active and inspect(packet):
                return
            await original(packet)

        hook = ScopedAttribute(mux, "confirmation", receive)
        try:
            yield proof
        finally:
            active = False
            hook.close()

    def validate(self, reply, session, request, proof):
        self.reader.guard(session)
        row = proof["response"]
        if (
            row is None
            or reply.pduSource != session["target"]
            or reply.apduInvokeID != request.apduInvokeID
            or apdu_bytes(reply) != bytes.fromhex(row["response_apdu_hex"])
        ):
            raise ValueError("Application response lacks exact owned wire evidence.")
        return row
