"""Authored literal UDP peers; no site captures or production writes."""

import asyncio

import httpx
import pytest
from bms_tool.app import create_app
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerWorkspace
from bms_tool.metasys_source_mapping import MetasysSourceMapping, MetasysSourceMappingRequest
from bms_tool.storage import Store
from pydantic import ValidationError

from .test_connections import free_udp
from .test_point_status import PointPeer
from .test_schedule_inventory import oid, text, unsigned


class MappingPeer(PointPeer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.vendor = 5
        self.source = unsigned(41)
        self.source_reads = 0
        self.change_source = False
        self.change_point = False
        self.change_reference = False

    def value(self, obj, prop, index):
        if prop == "vendor-identifier":
            return unsigned(self.vendor)
        if prop == "32589":
            self.source_reads += 1
            return unsigned(81) if self.change_source and self.source_reads > 1 else self.source
        if prop == "32527":
            return text(
                "Site:Engine/Bus.Meter.Changed"
                if self.change_reference and self.source_reads
                else "Site:Engine/Bus.Meter.Current"
            )
        if prop == "2564":
            return text("Feeder Current")
        if prop == "538":
            return b"\x09\x01\x1a\x00\x07"  # opaque native address; do not infer a route
        if (
            prop == "object-identifier"
            and int(obj[0]) != 8
            and self.change_point
            and self.source_reads
        ):
            return b"\xc4" + oid(int(obj[0]), 999)
        return super().value(obj, prop, index)


@pytest.fixture
async def mapping_link(tmp_path):
    peers = []
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = MetasysSourceMapping(
        ControllerWorkspace(client, client.store, timeout=0.08, operation_timeout=4)
    )

    async def peer(routed=False):
        result = MappingPeer(routed=routed)
        await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: result, local_addr=("127.0.0.1", 0)
        )
        peers.append(result)
        return result

    try:
        yield client, service, peer
    finally:
        client.close()
        for item in peers:
            item.close()
        await asyncio.sleep(0.03)


def target(peer, object_id="analog-input,501"):
    return dict(
        address="3001:7" if peer.routed else peer.endpoint,
        device="device,42",
        router=peer.endpoint if peer.routed else None,
        dnet=3001 if peer.routed else None,
        object_id=object_id,
    )


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("object_id", ["analog-input,501", "binary-value,502"])
async def test_distinguishes_local_identity_from_source_with_no_write_authority(
    mapping_link, routed, object_id
):
    client, service, make_peer = mapping_link
    peer = await make_peer(routed)
    report = await service.inspect(**target(peer, object_id))
    assert report["complete"] and report["identity_verified"], report
    assert report["mapping"]["local_object"] == object_id
    assert report["mapping"]["source_instance"] == 41
    assert report["mapping"]["source_object_type"] is None
    assert report["mapping"]["item_reference"] == "Site:Engine/Bus.Meter.Current"
    assert report["mapping"]["remote_object_name"] == "Feeder Current"
    assert not report["write_support"]["available"]
    assert report["read_only"] and report["mapping_observed"]
    assert report["properties"]["538"]["encoded_value"]["complete"]
    assert report["target"]["router"] == target(peer)["router"]
    assert report["connector_config"] == client.config
    assert len(peer.requests) == 14 and not peer.errors  # peer rejects every non-read APDU
    assert not client.app._requests and not client.app.asap.clientTransactions


@pytest.mark.parametrize(
    "failure",
    [
        "source_changed",
        "point_changed",
        "reference_changed",
        "wrong_vendor",
        "wrong_point",
        "boolean_source",
        "signed_source",
        "wildcard_source",
        "native_error",
        "timeout",
        "trailing",
    ],
)
async def test_incomplete_or_changed_evidence_never_becomes_a_verified_mapping(
    mapping_link, failure
):
    _, service, make_peer = mapping_link
    peer = await make_peer(True)
    if failure == "source_changed":
        peer.change_source = True
    elif failure == "point_changed":
        peer.change_point = True
    elif failure == "reference_changed":
        peer.change_reference = True
    elif failure == "wrong_vendor":
        peer.vendor = 999
    elif failure == "wrong_point":
        peer.wrong_point = True
    elif failure == "boolean_source":
        peer.source = b"\x11"
    elif failure == "signed_source":
        peer.source = b"\x31\x29"
    elif failure == "wildcard_source":
        peer.source = unsigned(4194303)
    else:
        peer.behavior, peer.corrupt_property = failure, "32589"
    report = await service.inspect(**target(peer))
    assert not report["complete"] and not report["mapping_observed"], report
    assert report["mapping"] is None and report["errors"]
    assert not report["write_support"]["available"]
    assert not peer.errors
    if failure == "wrong_vendor":
        assert all(prop not in ("32589", "32527", "2564", "538") for _, prop, _ in peer.requests)


@pytest.mark.parametrize(
    "changes",
    [
        {"object_id": "device,42"},
        {"object_id": "analog-output,1"},
        {"object_id": "analog-input,4194303"},
        {"proposed_instance": 81},
        {"apply": True},
    ],
)
def test_request_is_inspection_only(changes):
    with pytest.raises(ValidationError):
        MetasysSourceMappingRequest(
            **(
                {"address": "192.0.2.10", "device": "device,42", "object_id": "analog-input,501"}
                | changes
            )
        )


async def test_api_retains_route_requires_session_and_has_no_apply_operation(
    mapping_link, tmp_path
):
    _, _, make_peer = mapping_link
    peer = await make_peer(True)
    app = create_app(tmp_path / "mapping-api")
    path = "/api/bacnet/controller/metasys-source-mapping/"
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
            assert (await client.post(path + "inspect", json=target(peer))).status_code == 403
            assert not peer.requests
            assert (
                await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
            ).status_code == 200
            before = (await client.get("/api/bacnet/status")).json()
            response = await client.post(path + "inspect", headers=headers, json=target(peer))
            assert response.status_code == 200 and response.json()["complete"], response.text
            assert response.json()["target"]["router"] == peer.endpoint
            count = len(peer.requests)
            for extra in ({"apply": True}, {"source_instance": 81}, {"property_id": 32589}):
                rejected = await client.post(
                    path + "inspect", headers=headers, json=target(peer) | extra
                )
                assert rejected.status_code == 422
            assert (
                await client.post(path + "apply", headers=headers, json=target(peer))
            ).status_code == 404
            assert len(peer.requests) == count
            after = (await client.get("/api/bacnet/status")).json()
            assert before["config"] == after["config"] and before["commands"] == after["commands"]
            await client.post("/api/bacnet/disconnect", headers=headers, json={})
            offline = await client.post(path + "inspect", headers=headers, json=target(peer))
            assert not offline.json()["mapping_observed"] and len(peer.requests) == count
