"""Native source experiments use newly created isolated objects, never fixtures of site points."""

import asyncio
import copy
import struct

import httpx
import pytest
from bacpypes3.apdu import APDU, APCISequence, WritePropertyRequest
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import Unsigned
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerWorkspace
from bms_tool.metasys_configuration_api import MetasysConfigurationApi
from bms_tool.metasys_temporary_mapping import MetasysTemporaryMapping
from bms_tool.metasys_temporary_source_probe import MetasysTemporarySourceProbe
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_metasys_temporary_mapping import (
    BASE,
    CREATED,
    ENGINE,
    PARENT,
    ConfigurationPeer,
    EnginePeer,
    schema,
)
from .test_schedule_inventory import retired, text, unsigned

AI_CLASS = "objectTypeEnumSet.bacnetAiClass"


class SourcePeer(EnginePeer):
    def __init__(self):
        super().__init__()
        self.body = None
        self.source = 77
        self.mode = "accept"
        self.writes = []

    def value(self, obj, prop, index):
        if int(obj[0]) == 0 and self.body:
            if prop == "32527":
                return text(self.body["reference"])
            if prop == "description":
                return text(self.body["item"]["description"])
            if prop == "32589":
                return unsigned(self.source)
        return super().value(obj, prop, index)

    async def reply(self, data, source):
        request = APCISequence.decode(APDU.decode(PDU(data[6:])))
        if not isinstance(request, WritePropertyRequest):
            return await super().reply(data, source)
        assert self.body and str(request.objectIdentifier) == "analog-input,501"
        assert int(request.propertyIdentifier) == 32589
        assert request.priority is None and request.propertyArrayIndex is None
        value = int(request.propertyValue.cast_out(Unsigned))
        self.writes.append(value)
        if self.mode == "reject":
            apdu = bytes([0x50, request.apduInvokeID, 15, 0x91, 2, 0x91, 40])
        else:
            self.source = value
            if self.mode == "lost_reply":
                return
            apdu = bytes([0x20, request.apduInvokeID, 15])
        payload = b"\x01\x00" + apdu
        self.transport.sendto(b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload, source)


class SourceConfigurationPeer(ConfigurationPeer):
    def __init__(self, native):
        super().__init__()
        self.native = native
        self.parent_class = "objectTypeEnumSet.bacnetDeviceClass"
        self.create_schema = schema(AI_CLASS)

    async def handle(self, request):
        path = request.url.path
        if request.method == "DELETE":
            assert path.endswith("/objects/" + CREATED) and not request.content
            if self.native.mode == "reject":
                return httpx.Response(403, json={"message": "Authored cleanup refusal"})
            self.native.occupied = False
            self.native.body = None
            self.created = None
            if self.native.mode == "lost_reply":
                raise httpx.ReadTimeout("Authored lost cleanup reply")
            return httpx.Response(204)
        if request.method == "PATCH":
            assert path.endswith("/objects/" + CREATED)
            import json

            body = json.loads(request.content)
            assert set(body) == {"item"} and set(body["item"]) == {"instanceNumber"}
            if self.native.mode == "reject":
                return httpx.Response(400, json={"message": "Attribute is read-only"})
            self.native.source = body["item"]["instanceNumber"]
            if self.native.mode == "lost_reply":
                raise httpx.ReadTimeout("Authored lost configuration reply")
            return httpx.Response(200, json={})
        if request.method == "GET" and "/objects/" + CREATED + "/attributes/" in path:
            key = path.rsplit("/", 1)[-1]
            if key == "instanceNumber":
                return httpx.Response(200, json={"item": {key: self.native.source}})
            if key in ("intrinsicAlarmingDefined", "useRemoteAlarming"):
                return httpx.Response(200, json={"item": {key: False}})
        if path.endswith("/objects/" + CREATED + "/objects"):
            return httpx.Response(200, json={"items": [{"id": CREATED, "items": []}]})
        return await super().handle(request)


@pytest.fixture
async def probe_mapping(tmp_path):
    peer = SourcePeer()
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    bacnet = Bacnet(Store(tmp_path / "bacnet"))
    await bacnet.connect(f"127.0.0.1:{free_udp()}")
    workspace = ControllerWorkspace(bacnet, bacnet.store, timeout=0.08, operation_timeout=4)
    remote = SourceConfigurationPeer(peer)
    client = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(remote.handle))
    api = MetasysConfigurationApi(BASE, client)
    await api.login(username="authored-user", password="authored-password")
    mappings = MetasysTemporaryMapping(workspace, api, tmp_path / "journal")
    creation = await mappings.prepare(
        target={"address": peer.endpoint, "device": "device,42"},
        engine_id=ENGINE,
        parent_id=PARENT,
        object_type=AI_CLASS,
        local_instance=501,
        source_instance=77,
    )
    await mappings.create(**{k: creation[k] for k in ["operation_id", "token", "review_sha256"]})
    peer.body = {
        "item": copy.deepcopy(remote.posts[0]["item"]),
        "reference": creation["expected_reference"],
    }
    peer.occupied = True
    service = MetasysTemporarySourceProbe(mappings)
    try:
        yield service, creation["operation_id"], peer, remote, api
    finally:
        await api.close()
        bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


def apply_args(review):
    return {k: review[k] for k in ["operation_id", "phase", "token", "review_sha256"]}


@pytest.mark.parametrize("mode", ["accept", "reject", "lost_reply"])
async def test_single_native_attempt_retains_intent_and_independently_verifies_then_restores(
    probe_mapping, mode
):
    service, operation_id, peer, _, _ = probe_mapping
    peer.mode = mode
    review = await service.prepare(operation_id=operation_id, replacement_source=88)
    assert not peer.writes
    review["replacement_source"] = 999
    result = await service.apply(**apply_args(review))
    assert peer.writes == [88]
    assert result["production_source_edit_qualified"] is False
    records = service.mappings.records(operation_id)
    assert records["probe-intent"]["status"] == "outcome_uncertain"
    verified = await service.verify(operation_id=operation_id)
    if mode == "reject":
        assert result["status"] == "native_rejection"
        assert (result["error_class"], result["error_code"]) == (2, 40)
        assert result["transport_evidence"]["raw_complete"] is True
        assert verified["status"] == "original_source_verified" and peer.source == 77
    else:
        assert verified["status"] == "replacement_source_verified" and peer.source == 88
        assert result["status"] == (
            "acknowledged_unverified" if mode == "accept" else "outcome_uncertain"
        )
        if mode == "accept":
            assert result["transport_evidence"]["raw_complete"] is True
        peer.mode = "accept"
        restore = await service.prepare(operation_id=operation_id, restore=True)
        assert restore["replacement_source"] == 77
        await service.apply(**apply_args(restore))
        final = await service.verify(operation_id=operation_id, restored=True)
        assert final["status"] == "replacement_source_verified" and peer.source == 77
        assert peer.writes == [88, 77]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply(**apply_args(review))
    with pytest.raises(ValueError, match="already dispatched"):
        await service.prepare(operation_id=operation_id, replacement_source=88)
    assert not peer.errors and not service.workspace.bacnet.status()["commands"]
    retired(service.workspace.bacnet)


@pytest.mark.parametrize("change", ["source", "firmware", "owner", "account", "hash", "token"])
async def test_stale_probe_does_not_send_a_write(probe_mapping, change):
    service, operation_id, peer, _, api = probe_mapping
    review = await service.prepare(operation_id=operation_id, replacement_source=88)
    if change == "source":
        peer.source = 79
    elif change == "firmware":
        peer.firmware = "changed"
    elif change == "owner":
        peer.body["item"]["description"] = "Changed owner"
    elif change == "account":
        await api.login(username="other", password="authored-password")
    elif change == "hash":
        review["review_sha256"] = "0" * 64
    else:
        review["token"] = "wrong"
    with pytest.raises(ValueError):
        await service.apply(**apply_args(review))
    assert not peer.writes
    assert "probe-intent" not in service.mappings.records(operation_id)


async def test_production_or_unowned_guid_cannot_be_submitted_as_a_probe(probe_mapping):
    service, _, peer, _, _ = probe_mapping
    with pytest.raises(ValueError, match="tool-created"):
        await service.prepare(operation_id=CREATED, replacement_source=88)
    assert not peer.writes


@pytest.mark.parametrize("mode", ["accept", "reject", "lost_reply"])
async def test_authenticated_configuration_experiment_is_owned_and_single_attempt(
    probe_mapping, mode
):
    service, operation_id, peer, _, _ = probe_mapping
    peer.mode = mode
    review = await service.prepare(
        operation_id=operation_id, replacement_source=88, method="configuration-api"
    )
    response = await service.apply(**apply_args(review))
    assert not peer.writes
    if mode == "reject":
        assert response["status"] == "configuration_rejection"
        assert response["response_problem"] == {"message": "Attribute is read-only"}
    verified = await service.verify(operation_id=operation_id, method="configuration-api")
    assert verified["source"] == (77 if mode == "reject" else 88)
    if mode != "reject":
        peer.mode = "accept"
        restore = await service.prepare(
            operation_id=operation_id, restore=True, method="configuration-api"
        )
        await service.apply(**apply_args(restore))
        restored = await service.verify(
            operation_id=operation_id, restored=True, method="configuration-api"
        )
        assert restored["source"] == 77
    with pytest.raises(ValueError, match="already dispatched"):
        await service.prepare(
            operation_id=operation_id, replacement_source=88, method="configuration-api"
        )


@pytest.mark.parametrize("mode", ["accept", "lost_reply", "reject"])
async def test_cleanup_only_removes_owned_empty_mapping_without_replaying_uncertainty(
    probe_mapping, mode
):
    service, operation_id, peer, remote, _ = probe_mapping
    mappings = service.mappings
    review = await mappings.prepare_cleanup(operation_id)
    assert len(remote.posts) == 1 and peer.occupied
    peer.mode = mode
    args = {k: review[k] for k in ["operation_id", "token", "review_sha256"]}
    if mode == "accept":
        response = await mappings.cleanup(**args)
        assert response["status"] == "removal_acknowledged_unverified"
    else:
        with pytest.raises((httpx.HTTPError, ValueError)):
            await mappings.cleanup(**args)
    assert "cleanup-intent" in mappings.records(operation_id)
    if mode == "reject":
        with pytest.raises(ValueError):
            await mappings.verify_removed(operation_id)
        assert peer.occupied
    else:
        result = await mappings.verify_removed(operation_id)
        assert result["status"] == "temporary_mapping_removed_verified"
        assert not peer.occupied
    with pytest.raises(ValueError, match="consumed"):
        await mappings.cleanup(**args)
    assert not peer.writes


async def test_changed_source_or_unowned_object_cannot_be_cleaned_up(probe_mapping):
    service, operation_id, peer, _, _ = probe_mapping
    with pytest.raises(ValueError, match="tool-created"):
        await service.mappings.prepare_cleanup(CREATED)
    peer.source = 88
    with pytest.raises(ValueError):
        await service.mappings.prepare_cleanup(operation_id)
    assert "cleanup-intent" not in service.mappings.records(operation_id)
