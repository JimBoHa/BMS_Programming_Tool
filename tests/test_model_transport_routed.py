"""Actual UDP routed admission; independent literal NPDU proxy to a BACnet peer."""

import asyncio
import copy
import json
import os
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from bacpypes3.apdu import APDU, APCISequence, ReadPropertyMultipleRequest, ReadPropertyRequest
from bacpypes3.pdu import PDU
from bms_tool.hardware_workbench import HardwareWorkbench

from .test_hardware_survey import hardware_link as hardware_link
from .test_model_transport import finished, qualification


class RoutedProxy(asyncio.DatagramProtocol):
    """Forward native APDUs unchanged; construct/check routed envelopes independently."""

    def __init__(self, upstream):
        self.upstream = upstream
        self.clients = {}
        self.requests, self.responses, self.errors = [], [], []

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, frame, source):
        try:
            assert frame[:2] == b"\x81\x0a" and int.from_bytes(frame[2:4], "big") == len(frame)
            npdu = frame[4:]
            if source == self.upstream:
                assert npdu[:2] == b"\x01\x00"
                apdu = npdu[2:]
                assert apdu[0] >> 4 in (2, 3, 5, 6, 7)
                recipient = self.clients.pop(apdu[1])
                routed = b"\x01\x08" + struct.pack(">H", 3001) + b"\x01\x07" + apdu
                reply = b"\x81\x0a" + struct.pack(">H", len(routed) + 4) + routed
                self.responses.append(
                    {"upstream_frame_hex": frame.hex(), "routed_reply_hex": reply.hex()}
                )
                self.transport.sendto(reply, recipient)
                return
            assert npdu[:2] == b"\x01\x24"
            assert npdu[2:7] == struct.pack(">H", 3001) + b"\x01\x07\xff"
            apdu = npdu[7:]
            request = APCISequence.decode(APDU.decode(PDU(apdu)))
            assert isinstance(request, (ReadPropertyRequest, ReadPropertyMultipleRequest))
            assert not request.apduSeg
            self.clients[request.apduInvokeID] = source
            forwarded = b"\x01\x04" + apdu
            direct = b"\x81\x0a" + struct.pack(">H", len(forwarded) + 4) + forwarded
            self.requests.append(
                {
                    "type": type(request).__name__,
                    "routed_request_hex": frame.hex(),
                    "forwarded_frame_hex": direct.hex(),
                }
            )
            self.transport.sendto(direct, self.upstream)
        except BaseException as error:
            self.errors.append(repr(error))


@pytest.mark.parametrize("model", ["MS-FAC2611-0", "MS-FAC3613-0"])
async def test_actual_routed_mstp_target_is_not_rejected_as_ip_and_bad_mode_sends_nothing(
    hardware_link, model
):
    peer, client, _, options = hardware_link
    peer.device_object.modelName = model
    host, port = options["address"].split(":")
    transport, proxy = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: RoutedProxy((host, int(port))), local_addr=("127.0.0.1", 0)
    )
    workbench = HardwareWorkbench(client, client.store, SimpleNamespace(captures=lambda: []))
    config_before = copy.deepcopy(client.config)
    chosen = options | {"address": "3001:7", "router": proxy.endpoint, "dnet": 3001}
    try:
        for protocol in ("bacnet-sc", "n2", "unknown"):
            with pytest.raises(ValueError, match="not admitted"):
                workbench.start(
                    "survey", chosen | {"model_qualification": qualification(model, protocol)}
                )
        assert not proxy.requests and not workbench.jobs
        job = await finished(
            workbench,
            workbench.start(
                "survey", chosen | {"model_qualification": qualification(model, "bacnet-mstp")}
            ),
        )
        assert job["status"] == "complete", job
        assert job["model_transport_admission"]["path"] == "routed-explicit"
        assert job["model_transport_admission"]["dispatch_admitted"]
        assert job["target"]["address"] == "3001:7" and job["target"]["router"] == proxy.endpoint
        assert job["model_transport_observation"]["raw_identity"]["model"] == model
        assert job["model_transport_observation"]["model_text_status"] == "exact_text_match"
        assert job["model_transport_observation"]["target_matches_admission"]
        assert not job["model_transport_observation"]["native_compatibility_verified"]
        assert proxy.requests and len(proxy.responses) == len(proxy.requests) and not proxy.errors
        assert not proxy.clients and client.config == config_before and not client.commands
        assert not client.require().asap.clientTransactions
        if destination := os.environ.get("BMS_MODEL_TRANSPORT_EVIDENCE"):
            folder = Path(destination)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / (model + "-routed.json")).write_text(
                json.dumps(
                    {
                        "job": job,
                        "requests": proxy.requests,
                        "responses": proxy.responses,
                        "qualification": "Actual original UDP envelopes/APDUs retained from local proxy. BACnet Application peer supplies native service replies, proxy only checks/rewrites BVLC/NPDU. One-octet routed link emulated over UDP; no physical MS/TP/controller/firmware acceptance.",
                    },
                    indent=2,
                )
                + "\n"
            )
    finally:
        await workbench.close()
        transport.close()
        await asyncio.sleep(0.02)
