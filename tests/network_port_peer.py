"""Read-only MS/TP counter fixture for the controller workspace."""

import asyncio
import json
import struct

from .test_schedule_inventory import SchedulePeer, text, unsigned


class PortPeer(SchedulePeer):
    def __init__(self, vendor):
        super().__init__()
        self.vendor = vendor
        self.object_list = [(8, 42), (56, 7), (56, 8), (195, 11), (195, 12)]
        self.rounds = 0
        self.legacy_rounds = 0

    def value(self, obj, prop, index):
        if int(obj[0]) == 8:
            if prop == "vendor-identifier":
                return unsigned(self.vendor)
            if prop in (
                "model-name",
                "firmware-revision",
                "application-software-version",
                "vendor-name",
                "location",
            ):
                return text("Example supervisor")
            if prop == "max-apdu-length-accepted":
                return unsigned(480)
            if prop == "protocol-revision":
                return unsigned(22)
            if prop == "protocol-services-supported":
                return bytes.fromhex("83000000")
            if prop == "segmentation-supported":
                return bytes.fromhex("9103")
            if prop == "system-status":
                return bytes.fromhex("9100")
        if int(obj[0]) == 195:
            if prop == "object-name":
                return text("Example legacy field bus")
            if prop == "object-type":
                return bytes((0x91, 195))
            if prop == "max-master":
                return unsigned(127)
            if prop == "max-info-frames":
                return unsigned(2)
            if prop == "875":
                return unsigned(123)
            if prop == "2861":
                return bytes((0x91, 3)) if obj[1] == 11 else text("Unqualified")
            if prop.isdecimal():
                assert self.vendor == 5 and obj[1] == 11, "Unqualified legacy counter request"
                if prop == "2867":
                    self.legacy_rounds += 1
                    return unsigned(13 * self.legacy_rounds)
                return unsigned(0)
        if int(obj[0]) == 56:
            if prop == "object-name":
                return text("Test field port" if obj[1] == 7 else "Test IP port")
            if prop == "network-type":
                return bytes((0x91, 2 if obj[1] == 7 else 5))
            if prop == "network-number":
                return unsigned(80 + obj[1])
            if prop == "link-speed":
                return b"\x44" + struct.pack(">f", 38400)
            if prop == "reliability":
                return bytes.fromhex("9100")
            if prop.isdecimal():
                assert self.vendor == 5 and obj[1] == 7, "Unexpected vendor counter request"
                if prop == "2867":
                    self.rounds += 1
                    return unsigned(10 * self.rounds)
                if prop == "2868":
                    return unsigned(20 // self.rounds)
                if prop == "2884":
                    return text("Unknown counter encoding")
                return unsigned(0)
        return super().value(obj, prop, index)


async def main():
    peers = [PortPeer(5), PortPeer(999)]
    for peer in peers:
        await asyncio.get_running_loop().create_datagram_endpoint(
            lambda peer=peer: peer, local_addr=("127.0.0.1", 0)
        )
    print(json.dumps([p.endpoint for p in peers]), flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        for peer in peers:
            peer.close()


if __name__ == "__main__":
    asyncio.run(main())
