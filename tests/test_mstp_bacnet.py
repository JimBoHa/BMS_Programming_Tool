"""Real BACpypes3 services through a kernel TTY and fixed-wire peer.

There is no mocked Application, serial API, BACnet service or point value.
Only OS port enumeration is replaced so this test-owned pseudoterminal can be
selected. Fixed frames were independently verified with upstream C encoding.
"""

import asyncio
import os
import select
import threading
import time

import pytest
from bacpypes3.pdu import PDU, LocalStation
from bms_tool.mstp_bacnet import create_mstp_application

POLL = bytes.fromhex("55ff0101000000f5")
POLL_REPLY = bytes.fromhex("55ff02000100006d")
TO_PEER = bytes.fromhex("55ff000100000073")
TO_CLIENT = bytes.fromhex("55ff000001000062")
WHO_IS = bytes.fromhex("55ff060100000c66010010080b3fef3c1b3fef3cd962")
I_AM = bytes.fromhex("55ff06000100117c01001000c4023fef3c2201e091032203e77141")
READ = bytes.fromhex("55ff050100000d1101040043000c0c000000011955a77d")
VALUE_12_5 = bytes.fromhex("55ff060001001383010030000c0c0000000119553e44414800003f4e6c")


def read_exact(fd, count, stop):
    data = b""
    deadline = time.monotonic() + 4
    while len(data) < count and time.monotonic() < deadline and not stop.is_set():
        if select.select([fd], [], [], 0.01)[0]:
            data += os.read(fd, count - len(data))
    if stop.is_set():
        return None
    assert len(data) == count, data.hex()
    return data


class FixedWirePeer:
    def __init__(self, fd):
        self.fd = fd
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.errors = []
        self.requests = []
        self.pending_i_am = False

    def send(self, data):
        # Fragment both header and APDU over the actual serial stream.
        for chunk in (data[:3], data[3:9], data[9:]):
            if chunk:
                os.write(self.fd, chunk)
                time.sleep(0.002)

    def run(self):
        try:
            while not self.stop.is_set():
                header = read_exact(self.fd, 8, self.stop)
                if header is None:
                    return
                assert header[:2] == b"\x55\xff"
                length = int.from_bytes(header[5:7], "big")
                assert length <= 501
                tail = read_exact(self.fd, length + 2, self.stop) if length else b""
                if tail is None:
                    return
                frame = header + tail
                # PTYs deliver a write immediately. Wait for the simulated
                # UART's final stop bit and the peer turnaround before reply.
                time.sleep(len(frame) * 10 / 38400 + 0.002)
                if frame == POLL:
                    self.send(POLL_REPLY)
                elif frame == TO_PEER:
                    if self.pending_i_am:
                        self.send(I_AM)
                        self.pending_i_am = False
                        time.sleep(len(I_AM) * 10 / 38400 + 0.002)
                    self.send(TO_CLIENT)
                elif frame == WHO_IS:
                    self.requests.append("who-is")
                    self.pending_i_am = True
                elif frame == READ:
                    self.requests.append("read-property")
                    self.send(VALUE_12_5)
                else:
                    raise AssertionError(f"Unexpected serial wire frame {frame.hex()}")
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(exc)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        assert not self.errors


@pytest.mark.skipif(os.name != "posix", reason="Real pseudoterminal test requires POSIX")
@pytest.mark.asyncio
async def test_actual_application_who_is_i_am_and_read_property_over_serial(monkeypatch):
    master, slave = os.openpty()
    path = os.ttyname(slave)
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: {path})
    peer = FixedWirePeer(master)
    app = await create_mstp_application(path, 0, max_master=1)
    peer.thread.start()
    try:
        devices = await asyncio.wait_for(
            app.who_is(4190012, 4190012, address=LocalStation(1), timeout=2), 3
        )
        assert len(devices) == 1
        assert str(devices[0].iAmDeviceIdentifier[0]) == "device"
        assert devices[0].iAmDeviceIdentifier[1] == 4190012
        assert devices[0].pduSource == LocalStation(1)
        assert devices[0].maxAPDULengthAccepted == 480
        value = await asyncio.wait_for(app.read_property("1", "analog-input,1", "present-value"), 3)
        assert value == 12.5
        assert peer.requests == ["who-is", "read-property"]
        status = app.mstp_link.status()
        assert status["connected"] and not status["fault"] and status["receive_errors"] == 0
        assert status["statistics"]["received_npdus"] == 2
        assert not status["btcvt"] and not status["physical_bus_verified"]
        assert app.device_object.maxApduLengthAccepted == 480
        assert str(app.device_object.segmentationSupported) == "no-segmentation"
    finally:
        app.close()
        await asyncio.sleep(0)
        peer.close()
        os.close(master)
        os.close(slave)
    assert not app.mstp_link.status()["connected"]
    assert not app.mstp_link.status()["worker_alive"]


@pytest.mark.skipif(os.name != "posix", reason="Real pseudoterminal test requires POSIX")
@pytest.mark.asyncio
async def test_duplicate_mac_worker_fault_reaches_application_status(monkeypatch):
    master, slave = os.openpty()
    path = os.ttyname(slave)
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: {path})
    app = await create_mstp_application(path, 0, max_master=1)
    try:
        # Independent fixed frame: token from MAC 0, the client's own MAC.
        # An echoing adapter or conflicting master must fail closed.
        os.write(master, TO_PEER)
        for _ in range(100):
            if not app.mstp_link.status()["connected"]:
                break
            await asyncio.sleep(0.005)
        status = app.mstp_link.status()
        assert not status["connected"] and status["fault"]
        assert "Duplicate" in status["fault"]
        with pytest.raises(ValueError):
            await app.mstp_link.indication(
                PDU(bytes.fromhex("01001008"), destination=LocalStation(1))
            )
    finally:
        app.close()
        await asyncio.sleep(0)
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(os.name != "posix", reason="Real pseudoterminal test requires POSIX")
@pytest.mark.asyncio
async def test_layer_rejects_spoofing_wrong_address_and_closed_requests(monkeypatch):
    master, slave = os.openpty()
    path = os.ttyname(slave)
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: {path})
    app = await create_mstp_application(path, 0, max_master=1)
    try:
        with pytest.raises(ValueError, match="spoof"):
            await app.mstp_link.indication(
                PDU(
                    bytes.fromhex("01001008"),
                    source=LocalStation(2),
                    destination=LocalStation(1),
                )
            )
        with pytest.raises(ValueError, match="one-octet"):
            await app.mstp_link.indication(
                PDU(bytes.fromhex("01001008"), destination=LocalStation(b"\x01\x02"))
            )
        with pytest.raises(ValueError, match="explicit"):
            await app.mstp_link.indication(PDU(bytes.fromhex("01001008")))
        app.close()
        with pytest.raises(ValueError, match="closed"):
            await app.mstp_link.indication(
                PDU(bytes.fromhex("01001008"), destination=LocalStation(1))
            )
    finally:
        app.close()
        await asyncio.sleep(0)
        os.close(master)
        os.close(slave)


@pytest.mark.asyncio
async def test_application_open_failure_closes_without_starting_pump(monkeypatch):
    monkeypatch.setattr("bms_tool.mstp.enumerated_ports", lambda: set())
    with pytest.raises(ValueError, match="enumerated"):
        await create_mstp_application("/dev/no-such-port", 0)
    with pytest.raises(ValueError, match="BACnet instance"):
        await create_mstp_application("/dev/no-such-port", 0, instance=4194303)
