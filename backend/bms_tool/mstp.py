"""Legacy BACnet MS/TP framing and an explicit, fixed-address serial master.

This module transports NPDUs, not proprietary controller application images.
It does not implement the Johnson Controls BTCVT Bluetooth host protocol.
An RS-485 adapter must perform automatic direction control without local echo.
The OS/USB serial path is not a real-time or BTL-certified implementation.

Protocol references: BACnet Annex G CRC check vectors and the independently
maintained bacnet-stack MS/TP implementation at commit
e295d20baba977132b47bc09f61f28e12f2dfac3:
https://github.com/bacnet-stack/bacnet-stack/tree/e295d20baba977132b47bc09f61f28e12f2dfac3/src/bacnet/datalink
The Python implementation uses bit-at-a-time CRCs and its own bounded event
model. No upstream C source is included or required at runtime. Extended/COBS,
auto-baud, zero-configuration MAC selection and vendor frames are unsupported.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import IntEnum

import serial
from serial.tools import list_ports

MAX_NPDU = 501
MAX_QUEUE = 64
BROADCAST = 255
BAUDRATES = (9600, 19200, 38400, 57600, 76800, 115200)


class FrameType(IntEnum):
    TOKEN = 0
    POLL_FOR_MASTER = 1
    REPLY_TO_POLL_FOR_MASTER = 2
    TEST_REQUEST = 3
    TEST_RESPONSE = 4
    DATA_EXPECTING_REPLY = 5
    DATA_NOT_EXPECTING_REPLY = 6
    REPLY_POSTPONED = 7


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{name} must be an integer in {lower}..{upper}.")
    return value


def _time(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("MS/TP time must be finite, nonnegative monotonic seconds.")
    return float(value)


def header_crc(data: bytes) -> int:
    """Return the complemented Annex G CRC-8 (reflected polynomial 0x81)."""
    crc = 0xFF
    for octet in data:
        crc ^= octet
        for _ in range(8):
            crc = (crc >> 1) ^ (0x81 if crc & 1 else 0)
    return crc ^ 0xFF


def data_crc(data: bytes) -> int:
    """Return the complemented Annex G CRC-16 (wire order is little endian)."""
    crc = 0xFFFF
    for octet in data:
        crc ^= octet
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    return crc ^ 0xFFFF


@dataclass(frozen=True)
class Frame:
    frame_type: int
    destination: int
    source: int
    data: bytes = b""

    def __post_init__(self):
        _integer(int(self.frame_type), "Frame type", 0, 7)
        if type(self.frame_type) not in (int, FrameType):
            raise ValueError("Unsupported MS/TP frame type.")
        _integer(self.destination, "Destination MAC", 0, 255)
        _integer(self.source, "Source MAC", 0, 254)
        if not isinstance(self.data, bytes) or len(self.data) > MAX_NPDU:
            raise ValueError("Legacy MS/TP data must be bytes of at most 501 octets.")
        if self.frame_type in (0, 1, 2, 7) and self.data:
            raise ValueError("MS/TP control frames cannot contain data.")
        if self.frame_type in (0, 1, 2):
            if self.source > 127 or self.destination > 127:
                raise ValueError("Token and poll frames require unicast master MACs 0..127.")
        if self.frame_type == FrameType.REPLY_POSTPONED and self.destination == BROADCAST:
            raise ValueError("Reply Postponed cannot be broadcast.")
        if self.frame_type == FrameType.DATA_EXPECTING_REPLY and self.destination == BROADCAST:
            raise ValueError("Data Expecting Reply cannot be broadcast.")

    def encode(self) -> bytes:
        header = bytes((self.frame_type, self.destination, self.source)) + len(self.data).to_bytes(
            2, "big"
        )
        encoded = b"\x55\xff" + header + bytes((header_crc(header),))
        if self.data:
            encoded += self.data + data_crc(self.data).to_bytes(2, "little")
        return encoded


class FrameDecoder:
    """Bounded legacy stream receiver, with frame-abort and CRC rejection.

    A CRC-valid unsupported/oversized frame is skipped for its declared length
    without buffering its contents. Preambles inside that data never become
    control frames. Silence longer than frame_abort releases an incomplete
    frame. Optional 0xFF padding and repeated first-preamble bytes are accepted.
    """

    def __init__(self, frame_abort=0.095):
        self.frame_abort = _time(frame_abort)
        if not 0.030 <= self.frame_abort <= 0.100:
            raise ValueError("Frame abort must be 0.030..0.100 seconds.")
        self.buffer = bytearray()
        self.skip = 0
        self.last_octet = None
        self.stats = {
            "frames": 0,
            "header_crc_errors": 0,
            "data_crc_errors": 0,
            "unsupported_frames": 0,
            "oversized_frames": 0,
            "invalid_frames": 0,
            "aborted_frames": 0,
            "noise_octets": 0,
        }

    @property
    def pending(self):
        return bool(self.buffer or self.skip)

    def expire(self, now):
        now = _time(now)
        if (
            self.pending
            and self.last_octet is not None
            and now - self.last_octet > self.frame_abort
        ):
            self.buffer.clear()
            self.skip = 0
            self.stats["aborted_frames"] += 1
            return True
        return False

    def feed(self, data: bytes, now: float) -> list[Frame]:
        now = _time(now)
        if not isinstance(data, bytes) or len(data) > 65536:
            raise ValueError("Receive data must be bytes of at most 65536 octets per call.")
        self.expire(now)
        frames = []
        for octet in data:
            self.last_octet = now
            if self.skip:
                self.skip -= 1
                continue
            if not self.buffer:
                if octet == 0x55:
                    self.buffer.append(octet)
                else:
                    self.stats["noise_octets"] += 1
                continue
            if len(self.buffer) == 1:
                if octet == 0xFF:
                    self.buffer.append(octet)
                elif octet != 0x55:
                    self.buffer.clear()
                    self.stats["noise_octets"] += 2
                continue
            self.buffer.append(octet)
            if len(self.buffer) == 8:
                header = self.buffer[2:7]
                if header_crc(header) != self.buffer[7]:
                    self.stats["header_crc_errors"] += 1
                    # A fresh preamble beginning inside the bad header may
                    # already be present. Re-feed only the bounded suffix.
                    suffix = bytes(self.buffer[1:])
                    self.buffer.clear()
                    frames.extend(self.feed(suffix, now))
                    continue
                length = int.from_bytes(self.buffer[5:7], "big")
                if length > MAX_NPDU or self.buffer[2] > 7:
                    key = "oversized_frames" if length > MAX_NPDU else "unsupported_frames"
                    self.stats[key] += 1
                    self.skip = length + (2 if length else 0)
                    self.buffer.clear()
                    continue
            if len(self.buffer) < 8:
                continue
            length = int.from_bytes(self.buffer[5:7], "big")
            if len(self.buffer) < 8 + length + (2 if length else 0):
                continue
            raw = bytes(self.buffer)
            self.buffer.clear()
            payload = raw[8 : 8 + length]
            if length and data_crc(payload) != int.from_bytes(raw[-2:], "little"):
                self.stats["data_crc_errors"] += 1
                continue
            try:
                frame = Frame(raw[2], raw[3], raw[4], payload)
            except ValueError:
                self.stats["invalid_frames"] += 1
                continue
            self.stats["frames"] += 1
            frames.append(frame)
        return frames


@dataclass(frozen=True)
class ReceivedNPDU:
    source: int
    destination: int
    data: bytes
    expecting_reply: bool


def _broadcast_confirmed(npdu):
    """Recognize a confirmed application request in a bounded BACnet NPDU."""
    if len(npdu) < 2 or npdu[0] != 1:
        return False
    control = npdu[1]
    if control & 0x80:  # Network-layer message, not an APDU.
        return False
    index = 2
    if control & 0x20:
        if len(npdu) < index + 3:
            return False
        length = npdu[index + 2]
        index += 3 + length
    if control & 0x08:
        if len(npdu) < index + 3:
            return False
        length = npdu[index + 2]
        index += 3 + length
    if control & 0x20:
        index += 1  # Hop count follows both optional addresses.
    return index < len(npdu) and npdu[index] & 0xF0 == 0


class MstpMaster:
    """Deterministic, fixed-address legacy master, driven by monotonic time.

    Call ingest for received bytes and advance at intervals of five milliseconds
    or less. An emitted Frame must be sent as one contiguous UART write; notify
    transmit_complete after writing it. UART wire time is accounted for even
    when the OS write returns before the UART drains. At most one frame is
    emitted by an advance call. No application frame is sent without the token
    except an explicit immediate reply to a request addressed to this master.
    """

    def __init__(self, mac, *, max_master=127, max_info_frames=1, baudrate=38400, now=None):
        self.mac = _integer(mac, "Master MAC", 0, 127)
        self.max_master = _integer(max_master, "Max master", self.mac, 127)
        self.max_info_frames = _integer(max_info_frames, "Max info frames", 1, 255)
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("Unsupported MS/TP baud rate.")
        self.baudrate = baudrate
        self.decoder = FrameDecoder()
        self.tx_queue = deque()
        self.rx_queue = deque()
        self.stats = {
            "transmitted_frames": 0,
            "received_npdus": 0,
            "receive_overruns": 0,
            "reply_timeouts": 0,
            "postponed_replies": 0,
            "token_retries": 0,
            "broadcast_confirmed_discarded": 0,
        }
        self.state = "idle"
        self.next_station = self.mac
        self.poll_station = self.mac
        self.token_count = 50
        self.frame_count = 0
        self.retry_count = 0
        self.sole_master = False
        self.event_count = 0
        self.last_activity = _time(time.monotonic() if now is None else now)
        self.wire_until = self.last_activity
        self.last_now = self.last_activity
        self.pending_tx = None
        self.wait_peer = None
        self.wait_type = None
        self.answer_peer = None
        self.answer_started = None
        self.fault = None

    def _now(self, now):
        now = _time(now)
        if now < self.last_now:
            raise ValueError("MS/TP monotonic time cannot move backwards.")
        self.last_now = now
        return now

    def send_npdu(self, destination, data, *, expecting_reply=False):
        _integer(destination, "Destination MAC", 0, 255)
        if destination == self.mac:
            raise ValueError("Select a different destination MAC.")
        if type(expecting_reply) is not bool:
            raise ValueError("expecting_reply must be boolean.")
        if not isinstance(data, bytes) or not 2 <= len(data) <= MAX_NPDU or data[0] != 1:
            raise ValueError("A BACnet version-1 NPDU must contain 2..501 octets.")
        if self.fault:
            raise ValueError(self.fault)
        frame = Frame(
            FrameType.DATA_EXPECTING_REPLY
            if expecting_reply
            else FrameType.DATA_NOT_EXPECTING_REPLY,
            destination,
            self.mac,
            data,
        )
        if self._queued_application_frames() >= MAX_QUEUE:
            raise ValueError("MS/TP transmit queue is full (64 frames).")
        self.tx_queue.append(frame)

    def send_reply(self, destination, data, *, now=None):
        """Send immediately only for the matching open request; otherwise queue.

        False means the immediate-reply window has ended and the response will
        await a token. This method never invents a request/response correlation.
        The BACnet application layer remains responsible for APDU invoke IDs.
        """
        now = self.last_now if now is None else self._now(now)
        if (
            self.state == "answer-request"
            and destination == self.answer_peer
            and now - self.answer_started < 0.245
        ):
            if not isinstance(data, bytes) or not 2 <= len(data) <= MAX_NPDU or data[0] != 1:
                raise ValueError("A BACnet version-1 NPDU must contain 2..501 octets.")
            if self.pending_tx is not None:
                raise ValueError("An MS/TP reply is already awaiting transmission.")
            if self._queued_application_frames() >= MAX_QUEUE:
                raise ValueError("MS/TP transmit queue is full (64 frames).")
            self._schedule(
                Frame(FrameType.DATA_NOT_EXPECTING_REPLY, destination, self.mac, data), "idle"
            )
            self.answer_peer = None
            return True
        self.send_npdu(destination, data)
        return False

    def receive(self):
        return self.rx_queue.popleft() if self.rx_queue else None

    def _deliver(self, frame):
        if frame.destination == BROADCAST and _broadcast_confirmed(frame.data):
            self.stats["broadcast_confirmed_discarded"] += 1
            return
        if len(self.rx_queue) >= 256:
            self.rx_queue.popleft()
            self.stats["receive_overruns"] += 1
        self.rx_queue.append(
            ReceivedNPDU(
                frame.source,
                frame.destination,
                frame.data,
                frame.frame_type == FrameType.DATA_EXPECTING_REPLY,
            )
        )
        self.stats["received_npdus"] += 1

    def _schedule(self, frame, after):
        self.pending_tx = (frame, after)

    def _queued_application_frames(self):
        pending = self.pending_tx is not None and self.pending_tx[0].frame_type in (
            FrameType.DATA_EXPECTING_REPLY,
            FrameType.DATA_NOT_EXPECTING_REPLY,
        )
        return len(self.tx_queue) + int(pending)

    def _cancel_pending(self):
        if self.pending_tx is not None:
            frame = self.pending_tx[0]
            if frame.frame_type in (
                FrameType.DATA_EXPECTING_REPLY,
                FrameType.DATA_NOT_EXPECTING_REPLY,
            ):
                # A packet popped from the token queue or an immediate reply
                # still belongs to the application if other traffic makes us
                # yield during turnaround. It must wait for another token.
                self.tx_queue.appendleft(frame)
            self.pending_tx = None

    def _next(self, address):
        return (address + 1) % (self.max_master + 1)

    def _poll(self, address):
        if self.max_master == 0:
            self.sole_master = True
            self.frame_count = 0
            self.state = "use-token"
            return
        self.poll_station = self._next(address) if address == self.mac else address
        self.retry_count = 0
        self._schedule(Frame(FrameType.POLL_FOR_MASTER, self.poll_station, self.mac), "poll-master")

    def _pass(self):
        if self.next_station == self.mac:
            self._poll(self._next(self.mac))
            return
        self.event_count = 0
        self.retry_count = 0
        self._schedule(Frame(FrameType.TOKEN, self.next_station, self.mac), "pass-token")

    def _frame(self, frame, now):
        if frame.source == self.mac:
            self.fault = (
                "A received frame uses this master's MAC. Duplicate address or local echo; "
                "transmission is suspended. Disconnect and correct the interface."
            )
            self.state = "fault"
            self.pending_tx = None
            return
        if self.fault:
            return
        if self.state in ("pass-token", "no-token"):
            self.state = "idle"
        if self.pending_tx is not None:
            # Another station began transmitting during our turnaround. Yield
            # before sending a queued control frame or using a disputed token.
            self._cancel_pending()
            self.state = "idle"
        if self.state == "poll-master":
            if (
                frame.frame_type == FrameType.REPLY_TO_POLL_FOR_MASTER
                and frame.destination == self.mac
                and frame.source == self.poll_station
            ):
                self.sole_master = False
                self.next_station = frame.source
                self.poll_station = self.mac
                self.token_count = 0
                self._pass()
                return
            self.state = "idle"
        if self.state == "wait-reply":
            expected_type = (
                FrameType.TEST_RESPONSE
                if self.wait_type == FrameType.TEST_REQUEST
                else FrameType.DATA_NOT_EXPECTING_REPLY
            )
            if (
                frame.destination == self.mac
                and frame.source == self.wait_peer
                and frame.frame_type in (expected_type, FrameType.REPLY_POSTPONED)
            ):
                if frame.frame_type == FrameType.DATA_NOT_EXPECTING_REPLY:
                    self._deliver(frame)
                elif frame.frame_type == FrameType.REPLY_POSTPONED:
                    self.stats["postponed_replies"] += 1
                self.state = "done-token"
                self.wait_peer = None
                return
            # A foreign frame can indicate a duplicate token. Relinquish the
            # token and process a valid request/token through normal idle rules.
            self.state = "idle"
            self.wait_peer = None
        if self.state == "answer-request":
            self.answer_peer = None
            self.state = "idle"
        if self.state != "idle":
            # Unexpected traffic while holding a token synchronizes the node.
            self.state = "idle"
        if frame.destination not in (self.mac, BROADCAST):
            return
        kind = frame.frame_type
        if kind == FrameType.TOKEN:
            self.frame_count = 0
            self.sole_master = False
            self.state = "use-token"
        elif kind == FrameType.POLL_FOR_MASTER:
            self._schedule(
                Frame(FrameType.REPLY_TO_POLL_FOR_MASTER, frame.source, self.mac), "idle"
            )
        elif kind == FrameType.DATA_NOT_EXPECTING_REPLY:
            self._deliver(frame)
        elif kind == FrameType.DATA_EXPECTING_REPLY:
            self._deliver(frame)
            self.answer_peer = frame.source
            self.answer_started = now
            self.state = "answer-request"
        elif kind == FrameType.TEST_REQUEST:
            if frame.destination != BROADCAST:
                self._schedule(
                    Frame(FrameType.TEST_RESPONSE, frame.source, self.mac, frame.data), "idle"
                )

    def ingest(self, data: bytes, now: float):
        now = self._now(now)
        previous_errors = sum(
            self.decoder.stats[k]
            for k in ("header_crc_errors", "data_crc_errors", "invalid_frames", "aborted_frames")
        )
        frames = self.decoder.feed(data, now)
        if data:
            self.last_activity = now
            self.event_count = min(255, self.event_count + len(data))
            if self.event_count > 4 and self.state in ("pass-token", "no-token"):
                self.state = "idle"
        errors = sum(
            self.decoder.stats[k]
            for k in ("header_crc_errors", "data_crc_errors", "invalid_frames", "aborted_frames")
        )
        if errors != previous_errors and self.state == "wait-reply":
            self.frame_count = self.max_info_frames
            self.wait_peer = None
            self.state = "done-token"
        elif errors != previous_errors and self.pending_tx is not None:
            self._cancel_pending()
            self.state = "idle"
        for frame in frames:
            self._frame(frame, now)

    def transmit_complete(self, now):
        now = self._now(now)
        self.wire_until = max(self.wire_until, now)
        self.last_activity = max(self.last_activity, self.wire_until)
        self.event_count = 0

    def advance(self, now: float) -> Frame | None:
        now = self._now(now)
        if self.decoder.expire(now) and self.state == "wait-reply":
            self.frame_count = self.max_info_frames
            self.state = "done-token"
            self.wait_peer = None
        if self.fault or now < self.wire_until:
            return None
        # This bound also prevents an empty sole-master queue from spinning
        # indefinitely through USE/DONE. Normal maintenance emits before it.
        for _ in range(512):
            if self.pending_tx is not None:
                if self.decoder.pending or now < self.last_activity + 40 / self.baudrate:
                    return None
                frame, self.state = self.pending_tx
                self.pending_tx = None
                self.wire_until = now + len(frame.encode()) * 10 / self.baudrate
                self.last_activity = self.wire_until
                self.event_count = 0
                self.stats["transmitted_frames"] += 1
                return frame
            silence = max(0.0, now - self.last_activity)
            if self.state == "idle":
                if silence < 0.500:
                    return None
                self.state = "no-token"
                self.event_count = 0
            elif self.state == "no-token":
                slot_start = 0.500 + self.mac * 0.010
                slot_end = slot_start + 0.010
                whole_ring = 0.500 + (self.max_master + 1) * 0.010
                if silence >= slot_start and (silence < slot_end or silence > whole_ring):
                    self.next_station = self.mac
                    self.token_count = 0
                    self._poll(self._next(self.mac))
                else:
                    return None
            elif self.state == "use-token":
                if self.tx_queue:
                    frame = self.tx_queue.popleft()
                    self.frame_count += 1
                    waiting = frame.frame_type in (
                        FrameType.DATA_EXPECTING_REPLY,
                        FrameType.TEST_REQUEST,
                    )
                    self.wait_peer = frame.destination if waiting else None
                    self.wait_type = frame.frame_type if waiting else None
                    self._schedule(frame, "wait-reply" if waiting else "done-token")
                else:
                    if self.sole_master and self.max_master == 0:
                        return None
                    self.frame_count = self.max_info_frames
                    self.state = "done-token"
            elif self.state == "wait-reply":
                if silence < 0.255:
                    return None
                self.stats["reply_timeouts"] += 1
                self.frame_count = self.max_info_frames
                self.wait_peer = None
                self.state = "done-token"
            elif self.state == "done-token":
                if self.frame_count < self.max_info_frames:
                    self.state = "use-token"
                elif not self.sole_master and self.next_station == self.mac:
                    self._poll(self._next(self.mac))
                elif self.token_count < 49:
                    self.token_count += 1
                    if self.sole_master and self.next_station != self._next(self.mac):
                        self.frame_count = 0
                        self.state = "use-token"
                    else:
                        self._pass()
                elif self._next(self.poll_station) == self.next_station:
                    self.token_count = 1
                    if self.sole_master:
                        poll = self._next(self.next_station)
                        self.next_station = self.mac
                        self._poll(poll)
                    else:
                        self.poll_station = self.mac
                        self._pass()
                else:
                    self._poll(self._next(self.poll_station))
            elif self.state == "pass-token":
                if silence <= 0.035:
                    return None
                if self.retry_count == 0:
                    self.retry_count = 1
                    self.stats["token_retries"] += 1
                    self._schedule(
                        Frame(FrameType.TOKEN, self.next_station, self.mac), "pass-token"
                    )
                else:
                    poll = self._next(self.next_station)
                    self.next_station = self.mac
                    self.token_count = 0
                    self._poll(poll)
            elif self.state == "poll-master":
                if silence <= 0.035:
                    return None
                if self.sole_master:
                    self.frame_count = 0
                    self.state = "use-token"
                elif self.next_station != self.mac:
                    self._pass()
                elif self._next(self.poll_station) != self.mac:
                    self._poll(self._next(self.poll_station))
                else:
                    self.sole_master = True
                    self.frame_count = 0
                    self.state = "use-token"
            elif self.state == "answer-request":
                if now - self.answer_started < 0.245:
                    return None
                peer, self.answer_peer = self.answer_peer, None
                self._schedule(Frame(FrameType.REPLY_POSTPONED, peer, self.mac), "idle")
            else:
                return None
        return None

    def status(self):
        return {
            "state": self.state,
            "mac": self.mac,
            "max_master": self.max_master,
            "max_info_frames": self.max_info_frames,
            "baudrate": self.baudrate,
            "next_station": self.next_station,
            "poll_station": self.poll_station,
            "sole_master": self.sole_master,
            "queued_frames": self._queued_application_frames(),
            "received_pending": len(self.rx_queue),
            "fault": self.fault,
            "statistics": {**self.stats, **self.decoder.stats},
            "scope": "legacy-ms-tp-npdu",
            "btcvt": False,
            "physical_bus_verified": False,
        }


def enumerated_ports():
    return {item.device for item in list_ports.comports()}


class SerialMstpLink:
    """Own one explicitly selected OS serial device and a background master.

    No device is opened by construction. start validates that the port is
    currently enumerated, opens 8-N-1 with hardware handshaking disabled, and
    runs the receiver/token state machine. The adapter must implement automatic
    RS-485 direction control and suppress local echo. close stops the worker
    and closes the descriptor; no discovery broadcast is issued automatically.
    """

    def __init__(self, port, mac, *, max_master=127, max_info_frames=1, baudrate=38400):
        if not isinstance(port, str) or not port or len(port) > 256:
            raise ValueError("Select a serial port path of at most 256 characters.")
        self.port = port
        self.master = MstpMaster(
            mac,
            max_master=max_master,
            max_info_frames=max_info_frames,
            baudrate=baudrate,
        )
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._serial = None
        self._received = queue.Queue(maxsize=256)
        self.error = None
        self._started = False

    def start(self):
        with self._lock:
            if self._started:
                raise ValueError(
                    "This MS/TP link was already started. Create a new link to reconnect."
                )
            if self.port not in enumerated_ports():
                raise ValueError("Select a currently enumerated serial port.")
            self._serial = serial.Serial(
                self.port,
                baudrate=self.master.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=0,
                write_timeout=1,
                rtscts=False,
                dsrdtr=False,
                xonxoff=False,
                exclusive=True,
            )
            self.master.last_activity = time.monotonic()
            self.master.wire_until = self.master.last_activity
            self.master.last_now = self.master.last_activity
            self._started = True
            self._thread = threading.Thread(target=self._run, name="bms-mstp", daemon=True)
            self._thread.start()
        return self.status()

    def _run(self):
        try:
            while not self._stop.is_set():
                data = self._serial.read(min(4096, max(1, self._serial.in_waiting)))
                with self._lock:
                    now = time.monotonic()
                    if data:
                        self.master.ingest(data, now)
                    # Never call Serial.flush/tcdrain: some OS serial drivers
                    # can block there indefinitely, beyond write_timeout.
                    # Hold transmission while the OS queue contains bytes;
                    # the master separately accounts for full UART wire time.
                    frame = self.master.advance(now) if self._serial.out_waiting == 0 else None
                    while self.master.rx_queue:
                        packet = self.master.receive()
                        try:
                            self._received.put_nowait(packet)
                        except queue.Full:
                            self.master.stats["receive_overruns"] += 1
                    if self.master.fault:
                        raise ValueError(self.master.fault)
                if frame is not None:
                    encoded = frame.encode()
                    written = self._serial.write(encoded)
                    if written != len(encoded):
                        raise OSError("Incomplete MS/TP serial write; link stopped.")
                    with self._lock:
                        self.master.transmit_complete(time.monotonic())
                self._stop.wait(0.001)
        except Exception as exc:
            with self._lock:
                self.error = str(exc)
                self.master.fault = self.master.fault or self.error
                self.master.state = "fault"
                self.master.pending_tx = None
            self._stop.set()
        finally:
            if self._serial is not None:
                self._serial.close()

    def send_npdu(self, destination, data, *, expecting_reply=False):
        with self._lock:
            self._require()
            self.master.send_npdu(destination, data, expecting_reply=expecting_reply)

    def send_reply(self, destination, data):
        with self._lock:
            self._require()
            return self.master.send_reply(destination, data, now=time.monotonic())

    def _require(self):
        if not self._started or self._stop.is_set():
            raise ValueError(self.error or "Start the MS/TP serial link first.")

    def receive(self, timeout=0):
        if (
            type(timeout) not in (float, int)
            or not math.isfinite(timeout)
            or not 0 <= timeout <= 60
        ):
            raise ValueError("Receive timeout must be 0..60 seconds.")
        try:
            return self._received.get(timeout=timeout)
        except queue.Empty:
            return None

    def status(self):
        with self._lock:
            return {
                **self.master.status(),
                "port": self.port,
                "connected": self._started and not self._stop.is_set(),
                "worker_alive": bool(self._thread and self._thread.is_alive()),
                "error": self.error,
            }

    def close(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                # A stalled serial driver must be interrupted before returning.
                if self._serial is not None:
                    self._serial.cancel_read()
                    self._serial.cancel_write()
                    self._serial.close()
                thread.join(timeout=2)
        elif self._serial is not None:
            self._serial.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.close()
