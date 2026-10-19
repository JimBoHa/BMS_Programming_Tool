"""Legacy MS/TP: independent Annex G vectors, token cases and real OS serial.

The fixed request/reply octets were cross-checked against bacnet-stack's C
MSTP_Create_Frame/CRC functions at e295d20baba977132b47bc09f61f28e12f2dfac3.
They are BACnet ReadProperty for analog-input,1 present-value and a 12.5 reply.
These tests never open a physical serial port or use a building network.
"""

import os
import random
import select
import threading
import time

import pytest
from bms_tool.mstp import (
    BAUDRATES,
    MAX_NPDU,
    Frame,
    FrameDecoder,
    FrameType,
    MstpMaster,
    SerialMstpLink,
    _broadcast_confirmed,
    data_crc,
    header_crc,
)

TOKEN_5_TO_16 = bytes.fromhex("55ff00100500008c")
POLL_0_TO_1 = bytes.fromhex("55ff0101000000f5")
POLL_REPLY_1_TO_0 = bytes.fromhex("55ff02000100006d")
TOKEN_0_TO_1 = bytes.fromhex("55ff000100000073")
TOKEN_1_TO_0 = bytes.fromhex("55ff000001000062")
READ_REQUEST = bytes.fromhex("55ff050100000d1101040005010c0c000000011955f389")
READ_RESPONSE = bytes.fromhex("55ff060001001383010030010c0c0000000119553e44414800003f5ee2")
REQUEST_NPDU = bytes.fromhex("01040005010c0c000000011955")
RESPONSE_NPDU = bytes.fromhex("010030010c0c0000000119553e44414800003f")


def test_annex_g_crc_vectors_and_wire_order():
    # Public Annex G vectors also used by the independent BACnet-stack tests:
    # test/bacnet/datalink/crc/src/main.c (MIT-licensed test source).
    assert header_crc(bytes.fromhex("0010050000")) == 0x8C
    assert data_crc(bytes.fromhex("012230")) == 0xBD10
    assert Frame(FrameType.TOKEN, 16, 5).encode() == TOKEN_5_TO_16
    assert Frame(5, 1, 0, REQUEST_NPDU).encode() == READ_REQUEST
    assert Frame(6, 0, 1, RESPONSE_NPDU).encode() == READ_RESPONSE


@pytest.mark.parametrize("fragment", [1, 2, 3, 5, 8, 13, 128])
def test_fragmented_independent_frames_noise_padding_and_repeated_preamble(fragment):
    decoder = FrameDecoder()
    stream = b"\x00\xff\x55\x55" + TOKEN_5_TO_16 + b"\xff" + READ_REQUEST + READ_RESPONSE
    frames = []
    for offset in range(0, len(stream), fragment):
        frames += decoder.feed(stream[offset : offset + fragment], offset / 10000)
    assert frames == [Frame(0, 16, 5), Frame(5, 1, 0, REQUEST_NPDU), Frame(6, 0, 1, RESPONSE_NPDU)]
    assert not decoder.pending


@pytest.mark.parametrize("position", [2, 3, 4, 5, 6, 7, 8, 14, 22])
def test_corruption_is_rejected_and_next_frame_recovered(position):
    decoder = FrameDecoder()
    damaged = bytearray(READ_REQUEST)
    damaged[position] ^= 1
    frames = decoder.feed(bytes(damaged) + TOKEN_5_TO_16, 0)
    assert frames == [Frame(0, 16, 5)]
    assert decoder.stats["header_crc_errors"] + decoder.stats["data_crc_errors"] == 1


def raw_header(kind, destination, source, length):
    header = bytes((kind, destination, source)) + length.to_bytes(2, "big")
    return b"\x55\xff" + header + bytes((header_crc(header),))


def test_oversized_and_unsupported_payload_cannot_inject_control_frames():
    decoder = FrameDecoder()
    payload = (TOKEN_5_TO_16 * 70)[:502]
    assert len(payload) == 502
    oversized = raw_header(6, 0, 1, 502) + payload + b"\x00\x00"
    unsupported = raw_header(128, 0, 1, len(TOKEN_5_TO_16)) + TOKEN_5_TO_16 + b"\x00\x00"
    assert decoder.feed(oversized + unsupported + TOKEN_0_TO_1, 0) == [Frame(0, 1, 0)]
    assert decoder.stats["oversized_frames"] == 1
    assert decoder.stats["unsupported_frames"] == 1
    assert len(decoder.buffer) <= MAX_NPDU + 10


def test_timeout_aborts_incomplete_and_maximum_payload_roundtrip():
    decoder = FrameDecoder()
    assert decoder.feed(READ_REQUEST[:12], 0) == []
    assert not decoder.expire(0.095)
    assert decoder.expire(0.096)
    payload = bytes(range(251)) * 2
    frame = Frame(6, 200, 1, payload[:501])
    assert decoder.feed(frame.encode(), 0.1) == [frame]
    assert decoder.stats["aborted_frames"] == 1
    assert not decoder.pending


def test_bad_header_resynchronizes_to_embedded_preamble():
    decoder = FrameDecoder()
    # The second preamble begins in a deliberately bad eight-octet header.
    assert decoder.feed(b"\x55\xff\x23\x44" + TOKEN_0_TO_1, 0) == [Frame(0, 1, 0)]
    assert decoder.stats["header_crc_errors"] >= 1


def test_bounded_random_stream_and_all_legacy_frame_payloads():
    rng = random.Random(1900)
    decoder = FrameDecoder()
    for index in range(200):
        data = rng.randbytes(rng.randrange(0, 3000))
        decoder.feed(data, index * 0.2)
        assert len(decoder.buffer) <= 511
    for length in (0, 1, 2, 250, 500, 501):
        for kind in (3, 4, 5, 6):
            frame = Frame(kind, 3, 2, rng.randbytes(length))
            assert decoder.feed(frame.encode(), 41 + length) == [frame]


@pytest.mark.parametrize(
    "args",
    [
        (0, 255, 1, b""),
        (1, 1, 128, b""),
        (2, 128, 1, b""),
        (0, 1, 1, b"x"),
        (5, 255, 1, b"\x01\x04"),
        (7, 255, 1, b""),
        (6, 0, 255, b""),
        (8, 1, 1, b""),
        (True, 1, 1, b""),
        (6, 0, 1, b"x" * 502),
    ],
)
def test_invalid_frame_bounds(args):
    with pytest.raises(ValueError):
        Frame(*args)


def test_crc_valid_invalid_controls_never_authorize_transmission():
    decoder = FrameDecoder()
    broadcast_token = raw_header(0, 255, 1, 0)
    slave_token = raw_header(0, 0, 129, 0)
    der_broadcast = raw_header(5, 255, 1, 0)
    assert decoder.feed(broadcast_token + slave_token + der_broadcast, 0) == []
    assert decoder.stats["invalid_frames"] == 3


def test_transmission_needs_token_and_honors_turnaround_and_info_limit():
    master = MstpMaster(0, max_master=1, max_info_frames=2, now=0)
    master.send_npdu(1, REQUEST_NPDU)
    master.send_npdu(1, REQUEST_NPDU)
    master.send_npdu(1, REQUEST_NPDU)
    assert master.advance(0.1) is None
    assert len(master.tx_queue) == 3
    master.next_station = 1
    master.token_count = 0
    master.ingest(TOKEN_1_TO_0, 0.2)
    assert master.advance(0.2005) is None  # Less than forty bit times.
    first = master.advance(0.202)
    assert first == Frame(6, 1, 0, REQUEST_NPDU)
    assert master.advance(master.wire_until - 0.00001) is None
    second = master.advance(master.wire_until + 0.002)
    assert second == first
    token = master.advance(master.wire_until + 0.002)
    assert token == Frame(0, 1, 0)
    assert len(master.tx_queue) == 1
    assert master.state == "pass-token"


def test_valid_confirmed_reply_then_token_and_no_duplicate_delivery():
    master = MstpMaster(0, max_master=1, now=0)
    master.next_station = 1
    master.token_count = 0
    master.send_npdu(1, REQUEST_NPDU, expecting_reply=True)
    master.ingest(TOKEN_1_TO_0, 0.1)
    assert master.advance(0.102).encode() == READ_REQUEST
    assert master.state == "wait-reply"
    master.ingest(READ_RESPONSE, 0.2)
    packet = master.receive()
    assert packet.source == 1 and packet.data == RESPONSE_NPDU and not packet.expecting_reply
    assert master.receive() is None
    assert master.advance(0.202).encode() == TOKEN_0_TO_1


def test_wrong_reply_source_drops_token_and_waits_for_next_token():
    master = MstpMaster(0, max_master=3, now=0)
    master.send_npdu(1, REQUEST_NPDU, expecting_reply=True)
    master.ingest(TOKEN_1_TO_0, 0.1)
    master.advance(0.102)
    master.ingest(Frame(6, 0, 2, RESPONSE_NPDU).encode(), 0.2)
    assert master.state == "idle"
    assert master.advance(0.21) is None


def test_request_timeout_does_not_retry_data_without_new_token():
    master = MstpMaster(0, max_master=1, now=0)
    master.next_station = 1
    master.token_count = 0
    master.send_npdu(1, REQUEST_NPDU, expecting_reply=True)
    master.ingest(TOKEN_1_TO_0, 0.1)
    assert master.advance(0.102).frame_type == 5
    finish = master.wire_until
    assert master.advance(finish + 0.254) is None
    assert master.advance(finish + 0.256).frame_type == 0
    assert master.stats["reply_timeouts"] == 1
    assert not master.tx_queue


def test_postponed_reply_keeps_later_npdu_delivery():
    master = MstpMaster(0, max_master=1, now=0)
    master.next_station = 1
    master.token_count = 0
    master.send_npdu(1, REQUEST_NPDU, expecting_reply=True)
    master.ingest(TOKEN_1_TO_0, 0.1)
    master.advance(0.102)
    master.ingest(Frame(7, 0, 1).encode(), 0.2)
    assert master.stats["postponed_replies"] == 1
    assert master.advance(0.202).frame_type == 0
    master.ingest(READ_RESPONSE, 0.3)
    assert master.receive().data == RESPONSE_NPDU


def test_poll_response_without_token_and_broadcast_test_request_ignored():
    master = MstpMaster(1, max_master=1, now=0)
    master.ingest(POLL_0_TO_1, 0.1)
    assert master.advance(0.1005) is None
    assert master.advance(0.102).encode() == POLL_REPLY_1_TO_0
    master.ingest(Frame(3, 255, 0, b"test").encode(), 0.2)
    assert master.advance(0.202) is None
    master.ingest(Frame(3, 1, 0, b"test").encode(), 0.3)
    assert master.advance(0.302) == Frame(4, 0, 1, b"test")


def test_sole_master_generation_and_discovery_of_new_successor():
    master = MstpMaster(0, max_master=2, now=0)
    master.send_npdu(200, b"\x01\x00\x10\x08")
    assert master.advance(0.499) is None
    assert master.advance(0.501) == Frame(1, 1, 0)
    assert master.advance(master.wire_until + 0.036) == Frame(1, 2, 0)
    data = master.advance(master.wire_until + 0.036)
    assert data.frame_type == 6 and data.destination == 200
    assert master.sole_master
    # Empty cycles perform periodic master discovery; the new peer can join.
    pfm = master.advance(master.wire_until + 0.002)
    assert pfm.frame_type == 1 and pfm.destination in (1, 2)
    reply_at = master.wire_until + 0.002
    master.ingest(Frame(2, 0, pfm.destination).encode(), reply_at)
    token = master.advance(reply_at + 0.002)
    assert token.frame_type == 0 and token.destination == pfm.destination
    assert not master.sole_master


def test_address_zero_can_be_configured_as_only_master():
    master = MstpMaster(0, max_master=0, now=0)
    assert master.advance(0.501) is None
    assert master.sole_master and master.state == "use-token"
    master.send_npdu(200, b"\x01\x00\x10\x08")
    assert master.advance(0.502).destination == 200
    assert master.advance(master.wire_until + 0.002) is None


def test_no_token_address_slot_and_missed_slot_do_not_create_early_token():
    master = MstpMaster(3, max_master=7, now=0)
    assert master.advance(0.529) is None
    assert master.advance(0.531) == Frame(1, 4, 3)
    late = MstpMaster(3, max_master=7, now=0)
    assert late.advance(0.550) is None  # Missed local slot; other MACs may claim.
    assert late.advance(0.581) == Frame(1, 4, 3)  # Entire ring was silent.


def test_failed_token_retry_once_then_searches_past_dead_successor():
    master = MstpMaster(0, max_master=3, now=0)
    master.next_station = 1
    master.token_count = 0
    master.ingest(TOKEN_1_TO_0, 0.1)
    assert master.advance(0.102) == Frame(0, 1, 0)
    assert master.advance(master.wire_until + 0.036) == Frame(0, 1, 0)
    assert master.advance(master.wire_until + 0.036) == Frame(1, 2, 0)
    assert master.stats["token_retries"] == 1


def test_token_user_raw_activity_prevents_duplicate_token_retry():
    master = MstpMaster(0, max_master=1, now=0)
    master.next_station = 1
    master.token_count = 0
    master.ingest(TOKEN_1_TO_0, 0.1)
    master.advance(0.102)
    master.ingest(b"\x55\xff\x06\x22\x01", 0.11)
    assert master.state == "idle"
    assert master.advance(0.2) is None
    assert master.stats["token_retries"] == 0


def test_immediate_response_or_reply_postponed_and_later_token_response():
    master = MstpMaster(1, max_master=1, now=0)
    master.ingest(READ_REQUEST, 0.1)
    assert master.receive().expecting_reply
    assert master.send_reply(0, RESPONSE_NPDU)
    assert master.advance(0.102) == Frame(6, 0, 1, RESPONSE_NPDU)
    assert master.state == "idle"
    master.ingest(READ_REQUEST, 0.2)
    assert master.advance(0.444) is None
    assert master.advance(0.446) == Frame(7, 0, 1)
    assert not master.send_reply(0, RESPONSE_NPDU)
    assert master.advance(0.5) is None
    master.ingest(TOKEN_0_TO_1, 0.6)
    assert master.advance(0.602) == Frame(6, 0, 1, RESPONSE_NPDU)


def test_broadcast_confirmed_requests_discarded_and_network_messages_passed():
    master = MstpMaster(0, max_master=1, now=0)
    master.ingest(Frame(6, 255, 1, REQUEST_NPDU).encode(), 0.1)
    assert master.receive() is None
    assert master.stats["broadcast_confirmed_discarded"] == 1
    for npdu in (b"\x01\x00\x10\x08", b"\x01\x80\x00", b"\x01\x20\x00\x04\x00\xff\x10\x08"):
        master.ingest(Frame(6, 255, 1, npdu).encode(), master.last_now + 0.1)
        assert master.receive().data == npdu
    assert _broadcast_confirmed(b"\x01\x28\x00\x04\x01\x02\x00\x05\x01\x03\xff\x00\x05")
    for length in range(12):
        _broadcast_confirmed(b"\x01\x28" + b"\x05" * length)


def test_duplicate_address_fault_stops_transmission_and_queued_data():
    master = MstpMaster(0, max_master=1, now=0)
    master.send_npdu(1, REQUEST_NPDU)
    master.ingest(Frame(6, 1, 0, RESPONSE_NPDU).encode(), 0.1)
    assert master.fault and master.state == "fault"
    assert master.advance(4) is None
    with pytest.raises(ValueError, match="Duplicate"):
        master.send_npdu(1, REQUEST_NPDU)


def test_turnaround_collision_preserves_unsent_application_packet():
    master = MstpMaster(0, max_master=2, now=0)
    master.send_npdu(1, REQUEST_NPDU)
    master.ingest(TOKEN_1_TO_0, 0.1)
    assert master.advance(0.1005) is None
    assert master.pending_tx is not None
    master.ingest(Frame(6, 2, 1, RESPONSE_NPDU).encode(), 0.1006)
    assert master.state == "idle" and master.pending_tx is None
    assert len(master.tx_queue) == 1
    assert master.advance(0.11) is None
    master.ingest(TOKEN_1_TO_0, 0.2)
    assert master.advance(0.202) == Frame(6, 1, 0, REQUEST_NPDU)


def test_late_reply_waits_for_token_and_pending_frame_counts_in_queue_limit():
    master = MstpMaster(1, max_master=1, now=0)
    master.ingest(READ_REQUEST, 0.1)
    assert not master.send_reply(0, RESPONSE_NPDU, now=0.346)
    assert master.advance(0.346) == Frame(7, 0, 1)
    assert len(master.tx_queue) == 1
    master.ingest(TOKEN_0_TO_1, 0.4)
    assert master.advance(0.4005) is None
    assert master.pending_tx is not None
    for _ in range(63):
        master.send_npdu(0, RESPONSE_NPDU)
    assert master.status()["queued_frames"] == 64
    with pytest.raises(ValueError, match="full"):
        master.send_npdu(0, RESPONSE_NPDU)
    master.ingest(Frame(6, 0, 2, RESPONSE_NPDU).encode(), 0.4006)
    assert master.pending_tx is None and len(master.tx_queue) == 64


def test_queue_limits_monotonic_time_and_configuration_validation():
    master = MstpMaster(0, now=0)
    for _ in range(64):
        master.send_npdu(1, REQUEST_NPDU)
    with pytest.raises(ValueError, match="full"):
        master.send_npdu(1, REQUEST_NPDU)
    master.ingest(b"", 1)
    with pytest.raises(ValueError, match="backwards"):
        master.advance(0.5)
    with pytest.raises(ValueError, match="finite"):
        master.advance(float("nan"))
    for values in (
        {"mac": 128},
        {"mac": -1},
        {"mac": True},
        {"mac": 3, "max_master": 2},
        {"mac": 0, "baudrate": 12345},
        {"mac": 0, "max_info_frames": 0},
    ):
        with pytest.raises(ValueError):
            MstpMaster(**values)
    assert all(MstpMaster(0, baudrate=baud).baudrate == baud for baud in BAUDRATES)


def test_receive_backpressure_is_bounded_and_counted():
    master = MstpMaster(0, now=0)
    for index in range(300):
        master.ingest(READ_RESPONSE, index * 0.01)
    assert len(master.rx_queue) == 256
    assert master.stats["receive_overruns"] == 44


def test_two_independent_master_instances_form_ring_and_exchange_confirmed_npdu():
    nodes = [MstpMaster(0, max_master=1, now=0), MstpMaster(1, max_master=1, now=0)]
    nodes[0].send_npdu(1, REQUEST_NPDU, expecting_reply=True)
    packets = []
    wire = []
    for step in range(1, 3000):
        now = step * 0.001
        for index, master in enumerate(nodes):
            frame = master.advance(now)
            if frame is not None:
                wire.append((now, index, frame.frame_type))
                # Deliver only after the serial frame's stop bit, as on a bus.
                packets.append((master.wire_until, 1 - index, frame.encode()))
        ready = [item for item in packets if item[0] <= now]
        packets = [item for item in packets if item[0] > now]
        for _, index, data in ready:
            nodes[index].ingest(data, now)
        request = nodes[1].receive()
        if request:
            assert request.data == REQUEST_NPDU
            assert nodes[1].send_reply(0, RESPONSE_NPDU)
        response = nodes[0].receive()
        if response:
            assert response.data == RESPONSE_NPDU
            assert any(kind == 0 for _, _, kind in wire)
            assert not any(node.fault for node in nodes)
            return
    pytest.fail(f"No confirmed response; states {[node.status() for node in nodes]}, wire {wire}")


def read_exact(fd, count, timeout=4):
    result = b""
    deadline = time.monotonic() + timeout
    while len(result) < count and time.monotonic() < deadline:
        if select.select([fd], [], [], 0.01)[0]:
            result += os.read(fd, count - len(result))
    assert len(result) == count, result.hex()
    return result


@pytest.mark.skipif(os.name != "posix", reason="Real pseudoterminal test requires POSIX")
@pytest.mark.parametrize("corrupt", [False, True])
def test_real_pyserial_token_poll_and_fragmented_confirmed_exchange(monkeypatch, corrupt):
    tty_master, tty_slave = os.openpty()
    path = os.ttyname(tty_slave)
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: {path})
    errors = []
    link = SerialMstpLink(path, 0, max_master=1)

    def device():
        try:
            # The peer uses independent fixed wire octets, not this parser or
            # CRC generator. A real kernel TTY and pyserial carry every byte.
            assert read_exact(tty_master, 8) == POLL_0_TO_1
            for chunk in (POLL_REPLY_1_TO_0[:3], POLL_REPLY_1_TO_0[3:]):
                os.write(tty_master, chunk)
                time.sleep(0.003)
            assert read_exact(tty_master, 8) == TOKEN_0_TO_1
            time.sleep(0.004)
            os.write(tty_master, TOKEN_1_TO_0)
            assert read_exact(tty_master, len(READ_REQUEST)) == READ_REQUEST
            time.sleep(0.01)
            response = bytearray(READ_RESPONSE)
            if corrupt:
                response[-1] ^= 1
            for chunk in (response[:4], response[4:11], response[11:]):
                os.write(tty_master, chunk)
                time.sleep(0.003)
            assert read_exact(tty_master, 8) == TOKEN_0_TO_1
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=device, daemon=True)
    try:
        assert not link.status()["connected"]
        link.start()
        link.send_npdu(1, REQUEST_NPDU, expecting_reply=True)
        thread.start()
        packet = link.receive(timeout=2)
        if corrupt:
            assert packet is None
            assert link.status()["statistics"]["data_crc_errors"] == 1
        else:
            assert packet.source == 1 and packet.data == RESPONSE_NPDU
        thread.join(timeout=5)
        assert not thread.is_alive() and not errors
        assert not link.status()["btcvt"]
        assert not link.status()["physical_bus_verified"]
        with pytest.raises(ValueError, match="already started"):
            link.start()
    finally:
        link.close()
        assert not link.status()["connected"] and not link.status()["worker_alive"]
        os.close(tty_master)
        os.close(tty_slave)


def test_serial_open_is_explicit_and_rejects_unlisted_port(monkeypatch):
    opened = []
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: set())
    monkeypatch.setattr("bms_tool.mstp.serial.Serial", lambda *a, **kw: opened.append(kw))
    link = SerialMstpLink("/dev/does-not-exist", 1)
    assert not opened
    with pytest.raises(ValueError, match="enumerated"):
        link.start()
    assert not opened
    with pytest.raises(ValueError, match="Start"):
        link.send_npdu(2, REQUEST_NPDU)
    link.close()
