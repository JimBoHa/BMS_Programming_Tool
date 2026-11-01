"""Run production HTTP against two explicitly owned kernel TTY test peers.

Only serial-port enumeration is replaced. No production endpoint, connector,
BACnet service, frame implementation or acquisition response is mocked.
"""

import argparse
import json
import os
from pathlib import Path

import uvicorn
from bacpypes3.apdu import APDU
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString

from tests.serial_monitor_peer import MonitoringWirePeer


class BrowserWirePeer(MonitoringWirePeer):
    def __init__(self, fd, name, audit):
        super().__init__(fd)
        self.name, self.audit = name, audit

    def value(self, obj, prop, index):
        if str(obj) == "device,123" and int(prop) == 77:
            return CharacterString(f"Authored serial controller {self.name}")
        return super().value(obj, prop, index)

    def reply(self, npdu):
        decoded = APDU.decode(PDU(npdu[2:]))
        with self.audit.open("a") as stream:
            stream.write(json.dumps({"peer": self.name, "service": decoded.apduService}) + "\n")
        return super().reply(npdu)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("This authored serial fixture requires POSIX kernel TTYs.")
    args.fixture.parent.mkdir(parents=True, exist_ok=True)
    descriptors, peers, ports = [], [], []
    for name in ("A", "B"):
        master, slave = os.openpty()
        descriptors.extend((master, slave))
        path = os.ttyname(slave)
        audit = args.fixture.with_name(args.fixture.stem + "-" + name + "-wire.jsonl")
        audit.write_text("")
        peer = BrowserWirePeer(master, name, audit)
        if name == "B":
            peer.value_now = 44.5
        peers.append(peer)
        ports.append(
            {"device": path, "description": f"Authored kernel TTY {name}", "audit": str(audit)}
        )
    import bms_tool.app as app_module
    import bms_tool.connections as connections
    import bms_tool.mstp as mstp

    app_module.ports = connections.ports = lambda: ports
    mstp.enumerated_ports = lambda: {item["device"] for item in ports}
    args.fixture.write_text(
        json.dumps({"ports": ports, "physical_bus": False, "btcvt": False}, indent=2) + "\n"
    )
    app = app_module.create_app()
    for peer in peers:
        peer.thread.start()
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    finally:
        app.state.bacnet.close()
        errors = []
        for peer in peers:
            try:
                peer.close()
            except AssertionError as failure:
                errors.append(str(failure))
        for fd in descriptors:
            os.close(fd)
        if errors:
            raise AssertionError(errors)


if __name__ == "__main__":
    main()
