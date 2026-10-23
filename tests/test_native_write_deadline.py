"""Independent literal-peer timing at the durable-intent/send boundary."""

import asyncio
import json
import time

import pytest
from bms_tool import bacnet_exchange

from .test_native_schedule_write import apply_options, assert_retired, link, preview


@pytest.mark.parametrize(
    "response_seconds,native_milliseconds",
    [(0.1, 3000), (0.4, 40)],
    ids=["outer-response-budget", "native-ssm-budget"],
)
async def test_durable_intent_preparation_does_not_consume_response_budget(
    tmp_path, monkeypatch, response_seconds, native_milliseconds
):
    parts = await link(tmp_path)
    peer, client, inventory, _, service, _ = parts
    trace = []

    def record(event, **details):
        trace.append({"event": event, "monotonic": time.monotonic(), **details})

    try:
        plan = await preview(parts)
        service.timeout = response_seconds
        original_intent = service.journal.intent

        def slow_durable_intent(receipt):
            record("journal_enter")
            result = original_intent(receipt)
            record("journal_durable_commit")
            # Deliberately block this event loop, just like synchronous local
            # encoding/fsync work. This is preparation, before any send.
            time.sleep(0.16)
            record("journal_return")
            return result

        monkeypatch.setattr(service.journal, "intent", slow_durable_intent)
        native_class = bacnet_exchange.ClientSSM

        class TimedSSM(native_class):
            async def indication(self, packet):
                if packet.apduService == 15:
                    self.apduTimeout = native_milliseconds
                return await super().indication(packet)

            def start_timer(self, milliseconds):
                if getattr(self.segmentAPDU, "apduService", None) == 15:
                    record("native_timer_start", milliseconds=milliseconds)
                return super().start_timer(milliseconds)

            async def request(self, packet):
                if packet.apduService == 15:
                    record("native_request_handoff", invoke=packet.apduInvokeID)
                return await super().request(packet)

        monkeypatch.setattr(bacnet_exchange, "ClientSSM", TimedSSM)
        original_reply = peer.reply

        async def delayed_literal_reply(data, source):
            if len(data) > 9 and data[9] == 15:
                record("literal_peer_received_write", frame_hex=data.hex())
                # Shorter than either declared response budget, and makes an
                # already-expired timer deterministic rather than a race.
                await asyncio.sleep(0.01)
            return await original_reply(data, source)

        monkeypatch.setattr(peer, "reply", delayed_literal_reply)
        transport = peer.transport

        class TracedPeerTransport:
            def __getattr__(self, key):
                return getattr(transport, key)

            def sendto(self, data, destination):
                if len(data) == 9 and data[6] == 0x20 and data[8] == 15:
                    record("literal_peer_sent_ack", frame_hex=data.hex())
                return transport.sendto(data, destination)

        peer.transport = TracedPeerTransport()
        result = json.loads(await service.apply(**apply_options(plan)))
        await asyncio.sleep(0.02)
        record("receipt_complete", protocol_status=result["protocol_status"])
        proof = {
            "response_seconds": response_seconds,
            "native_milliseconds": native_milliseconds,
            "synthetic_synchronous_intent_delay_seconds": 0.16,
            "literal_peer_ack_delay_seconds": 0.01,
            "trace": trace,
            "receipt": result,
        }
        (tmp_path / "timing-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
        assert len(peer.write_packets) == 1 and not peer.errors
        assert any(item["event"] == "literal_peer_sent_ack" for item in trace)
        assert result["may_have_applied"] and result["dispatch_started"]
        assert_retired(client)
        assert result["protocol_accepted"], proof
        assert result["readback"]["status"] == "match"
        events = [item["event"] for item in trace]
        starts = [item for item in trace if item["event"] == "native_timer_start"]
        assert [item["milliseconds"] for item in starts] == [
            native_milliseconds,
            native_milliseconds,
        ]
        assert events.index("journal_return") < events.index("native_request_handoff")
        assert starts[-1]["monotonic"] >= next(
            item["monotonic"] for item in trace if item["event"] == "journal_return"
        )
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()


@pytest.mark.parametrize(
    "budget",
    [True, False, 0, -0.1, float("nan"), float("inf"), -float("inf"), "0.1", {}, 10**1000],
    ids=[
        "bool-true",
        "bool-false",
        "zero",
        "negative",
        "nan",
        "infinity",
        "negative-infinity",
        "string",
        "container",
        "overflowing-integer",
    ],
)
async def test_response_budget_rejects_invalid_values_before_registration(budget):
    with pytest.raises(ValueError, match="finite|single_attempt"):
        await bacnet_exchange.confirmed_exchange(
            None, None, single_attempt=True, response_timeout=budget
        )


async def test_response_budget_requires_explicit_single_attempt():
    with pytest.raises(ValueError, match="single_attempt"):
        await bacnet_exchange.confirmed_exchange(None, None, response_timeout=0.1)


async def test_actual_deadline_expiry_after_durable_intent_still_sends_nothing(
    tmp_path, monkeypatch
):
    parts = await link(tmp_path)
    peer, client, inventory, _, service, _ = parts
    try:
        plan = await preview(parts)
        original = service.journal.intent
        times = {}

        def expires_during_commit(receipt):
            # The explicit absolute pre-dispatch guard remains authoritative,
            # independently of the longer enclosing operation timeout.
            times["deadline"] = service.active["deadline"] = time.monotonic() + 0.02
            result = original(receipt)
            time.sleep(0.04)
            times["return"] = time.monotonic()
            return result

        monkeypatch.setattr(service.journal, "intent", expires_during_commit)
        result = json.loads(await service.apply(**apply_options(plan)))
        assert times["return"] >= times["deadline"]
        assert not result["dispatch_started"] and not result["may_have_applied"]
        assert result["status"] == "not_sent" and not peer.write_packets
        assert any("while recording intent" in error for error in result["errors"])
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()


async def test_no_ack_response_budget_elapses_after_send_without_retry(tmp_path, monkeypatch):
    parts = await link(tmp_path)
    peer, client, inventory, _, service, _ = parts
    times = {}
    try:
        plan = await preview(parts)
        peer.mode = "drop"  # Applies the exact day but deliberately sends no ACK.
        original_intent = service.journal.intent

        def slow_intent(receipt):
            result = original_intent(receipt)
            time.sleep(0.16)
            times["intent_return"] = time.monotonic()
            return result

        monkeypatch.setattr(service.journal, "intent", slow_intent)
        native_class = bacnet_exchange.ClientSSM

        class SendClock(native_class):
            async def request(self, packet):
                if packet.apduService == 15:
                    times["handoff"] = time.monotonic()
                return await super().request(packet)

        monkeypatch.setattr(bacnet_exchange, "ClientSSM", SendClock)
        original_readback = service._readback

        async def readback(*args, **kwargs):
            times["readback_start"] = time.monotonic()
            return await original_readback(*args, **kwargs)

        monkeypatch.setattr(service, "_readback", readback)
        result = json.loads(await service.apply(**apply_options(plan)))
        assert times["intent_return"] <= times["handoff"]
        assert times["readback_start"] - times["handoff"] >= service.timeout - 0.005
        assert result["protocol_status"] == "unknown" and not result["protocol_accepted"]
        assert result["may_have_applied"] and result["dispatch_started"]
        assert result["readback"]["status"] == "match"
        assert len(peer.write_packets) == 1 and not peer.errors
        assert any("single-attempt deadline" in error for error in result["errors"])
        assert_retired(client)
    finally:
        await service.close()
        await inventory.close()
        client.close()
        peer.close()
