"""Read-only authored Schedule peer supporting the current controller entry path."""

import asyncio
import json
import signal
import sys

from .test_schedule_inventory import SchedulePeer, oid, text, unsigned


class BrowserSchedulePeer(SchedulePeer):
    def value(self, obj, prop, index):
        if int(obj[0]) == 8:
            if prop == "object-list" and index is None:
                return b"".join(b"\xc4" + oid(*item) for item in self.object_list)
            texts = {
                "vendor-name": "Authored loopback fixture",
                "model-name": "Schedule trace peer",
                "firmware-revision": "test-1",
                "application-software-version": "authored-1",
                "location": "Local simulated network",
            }
            if prop in texts:
                return text(texts[prop])
            if prop in ("vendor-identifier", "protocol-revision", "max-apdu-length-accepted"):
                return unsigned(
                    {
                        "vendor-identifier": 5,
                        "protocol-revision": 22,
                        "max-apdu-length-accepted": 1476,
                    }[prop]
                )
            if prop in ("segmentation-supported", "system-status"):
                return b"\x91\x03" if prop == "segmentation-supported" else b"\x91\x00"
        return super().value(obj, prop, index)


async def main():
    peer = BrowserSchedulePeer(routed=sys.argv[1] == "routed")
    if sys.argv[2] == "dropped":
        peer.drop_reference = ("schedule,1", "list-of-object-property-references", None)
    if sys.argv[2] == "hold":
        peer.hold_property = "list-of-object-property-references"
    loop = asyncio.get_running_loop()
    stopped = asyncio.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stopped.set)
    await loop.create_datagram_endpoint(lambda: peer, local_addr=("127.0.0.1", 0))
    received = peer.datagram_received

    def observed(data, source):
        # Every incoming APDU is checked by the independent peer's decoder;
        # mutation/other services become errors rather than invisible traffic.
        received(data, source)
        print("READ", flush=True)

    peer.datagram_received = observed
    print(json.dumps({"endpoint": peer.endpoint}), flush=True)
    try:
        await stopped.wait()
    finally:
        tasks = list(peer.tasks)
        peer.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        print(
            "FINAL "
            + json.dumps({"requests": peer.requests, "errors": [str(e) for e in peer.errors]}),
            flush=True,
        )


if __name__ == "__main__":
    asyncio.run(main())
