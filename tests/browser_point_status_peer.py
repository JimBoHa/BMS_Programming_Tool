"""Loopback point data and device properties for the controller workspace."""

import asyncio
import struct
import sys

from .browser_schedule_trace_peer import BrowserSchedulePeer
from .test_point_status import PointPeer


class BrowserPointPeer(BrowserSchedulePeer):
    def __init__(self, *, routed):
        super().__init__(routed=routed)
        self.points = PointPeer()
        self.object_list = [(8, 42), (0, 1), (1, 2)]
        self.compare_priorities = False
        self.completed_array = False

    def value(self, obj, prop, index):
        if int(obj[0]) == 8:
            return super().value(obj, prop, index)
        if self.compare_priorities and str(obj) == "analog-output,2" and prop == "priority-array":
            if index == 8 and self.completed_array:
                return b"\x44" + struct.pack(">f", 0.0)
            if index == 15 and not self.completed_array:
                return b"\x44" + struct.pack(">f", 12.5)
            if index == 16:
                self.completed_array = True
        return self.points.value(obj, prop, index)

    def datagram_received(self, data, source):
        print("READ", flush=True)
        super().datagram_received(data, source)


async def main():
    routed, behavior = sys.argv[1:]
    peer = BrowserPointPeer(routed=routed == "1")
    peer.compare_priorities = behavior == "slot-change"
    if behavior == "unsupported":
        peer.behavior = "native_error"
        peer.corrupt_property = "reliability"
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    print(peer.endpoint.rsplit(":", 1)[1], flush=True)
    try:
        if behavior == "hold":
            # Controller selection and inventory finish before the first held read.
            command = await asyncio.to_thread(sys.stdin.readline)
            if command.strip() != "hold":
                raise ValueError("Expected the point inspection hold request")
            peer.behavior = "hold"
            print("HOLDING", flush=True)
        await asyncio.Event().wait()
    finally:
        peer.close()


if __name__ == "__main__":
    asyncio.run(main())
