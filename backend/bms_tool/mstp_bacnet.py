"""BACpypes3 application services over the explicit legacy MS/TP serial link.

This adapter carries real BACnet NPDUs through SerialMstpLink; it is neither a
BTCVT host driver nor a proprietary controller application loader. No socket,
port, broadcast discovery or physical device is opened on module import.
"""

from __future__ import annotations

import asyncio

from bacpypes3.app import Application
from bacpypes3.comm import Server
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import PDU, Address, LocalBroadcast, LocalStation

from .mstp import BROADCAST, SerialMstpLink, _integer


class _ConfirmedOwner:
    def __init__(self, layer, previous):
        self.layer, self.previous, self.retired = layer, previous, False


class MstpLinkLayer(Server[PDU]):
    def __init__(self, link: SerialMstpLink):
        super().__init__()
        self.link = link
        self.address = LocalStation(link.master.mac)
        self.closed = False
        self._task = None
        self.receive_errors = 0
        self.last_receive_error = None
        self.pump_error = None

    def start(self):
        if self.closed or self._task is not None:
            raise ValueError("This MS/TP link layer cannot be started again.")
        self.link.start()
        self._task = asyncio.create_task(self._receive(), name="bms-mstp-bacnet")

    async def indication(self, pdu: PDU):
        if self.closed or self.pump_error:
            raise ValueError(self.pump_error or "The MS/TP link layer is closed.")
        owner = pdu.pduUserData
        owner = owner if isinstance(owner, _ConfirmedOwner) and owner.layer is self else None
        if owner is not None and owner.retired:
            return
        destination = pdu.pduDestination
        if destination is None:
            raise ValueError("MS/TP requires an explicit destination MAC.")
        if destination.addrType == Address.localBroadcastAddr:
            mac = BROADCAST
        elif destination.addrType == Address.localStationAddr and destination.addrLen == 1:
            mac = destination.addrAddr[0]
        else:
            raise ValueError(
                "The MS/TP data link requires a one-octet local MAC or local broadcast."
            )
        if pdu.pduSource is not None and pdu.pduSource != self.address:
            raise ValueError("The MS/TP link cannot spoof a different source MAC.")
        npdu = bytes(pdu.pduData)
        expecting = len(npdu) >= 2 and bool(npdu[1] & 4)
        # BACpypes tracks service transactions/invoke IDs. Its response can use
        # the link's immediate-reply window; an expired window queues normally.
        if mac != BROADCAST and not expecting:
            self.link.send_reply(mac, npdu)
        else:
            self.link.send_npdu(mac, npdu, expecting_reply=expecting, owner=owner)

    def own_confirmed_request(self, request):
        owner = _ConfirmedOwner(self, request.pduUserData)
        request.pduUserData = owner
        return owner

    def retire_confirmed_request(self, request, owner):
        owner.retired = True
        try:
            return self.link.retire_owner(owner)
        finally:
            if request.pduUserData is owner:
                request.pduUserData = owner.previous

    async def _receive(self):
        try:
            while not self.closed:
                status = self.link.status()
                if not status["connected"]:
                    self.pump_error = status["fault"] or status["error"] or "MS/TP worker stopped."
                    break
                # Bound work per event-loop turn so a busy bus cannot starve
                # HTTP requests, shutdown or BACnet transaction timers.
                for _ in range(32):
                    packet = self.link.receive()
                    if packet is None:
                        break
                    pdu = PDU(
                        packet.data,
                        source=LocalStation(packet.source),
                        destination=LocalBroadcast()
                        if packet.destination == BROADCAST
                        else self.address,
                        expectingReply=packet.expecting_reply,
                    )
                    try:
                        await self.response(pdu)
                    except Exception as exc:
                        # Invalid NPDU/APDU bytes are one received packet's
                        # failure. They must not silently kill the serial pump.
                        self.receive_errors += 1
                        self.last_receive_error = str(exc)[:512]
                await asyncio.sleep(0.002)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.pump_error = str(exc)[:512]
        finally:
            if self.pump_error:
                await asyncio.to_thread(self.link.close)

    def status(self):
        return {
            **self.link.status(),
            "connected": not self.closed
            and not self.pump_error
            and self.link.status()["connected"],
            "receive_errors": self.receive_errors,
            "last_receive_error": self.last_receive_error,
            "pump_error": self.pump_error,
        }

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._task is not None:
            self._task.cancel()
        self.link.close()


async def create_mstp_application(
    port,
    mac,
    *,
    instance=4190001,
    max_master=127,
    max_info_frames=1,
    baudrate=38400,
):
    """Open the selected serial port and return a real BACpypes3 Application.

    app.mstp_link.status() exposes the worker and token state. app.close()
    closes the link and its receive task. The application advertises the legacy
    MS/TP APDU ceiling of 480 octets and no application-layer segmentation.
    """
    _integer(instance, "BACnet instance", 0, 4194302)
    link = SerialMstpLink(
        port,
        mac,
        max_master=max_master,
        max_info_frames=max_info_frames,
        baudrate=baudrate,
    )
    app = Application.from_object_list(
        [
            DeviceObject(
                objectIdentifier=("device", instance),
                objectName="BMS Studio MS/TP engineering client",
                vendorIdentifier=999,
                maxApduLengthAccepted=480,
                segmentationSupported="no-segmentation",
                maxMaster=max_master,
                maxInfoFrames=max_info_frames,
            )
        ]
    )
    layer = MstpLinkLayer(link)
    app.mstp_link = layer
    app.nsap.bind(layer, address=layer.address)
    app.link_layers["mstp"] = layer
    try:
        layer.start()
        await asyncio.sleep(0)
        if not layer.status()["connected"]:
            raise ValueError(layer.status()["pump_error"] or "MS/TP worker could not start.")
    except BaseException:
        app.close()
        raise
    return app
