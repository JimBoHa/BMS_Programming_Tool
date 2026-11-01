"""Selected-controller acquisition over real direct and routed loopback UDP."""

import asyncio
import copy
import struct
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import pytest
from bacpypes3.apdu import (
    APDU,
    APCISequence,
    ReadPropertyACK,
    ReadPropertyRequest,
    ReadRangeACK,
    ReadRangeRequest,
)
from bacpypes3.basetypes import DateTime, LogRecord, LogRecordLogDatum, Reliability, StatusFlags
from bacpypes3.constructeddata import Any, ArrayOf, ListOf
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import (
    BitString,
    Boolean,
    CharacterString,
    ObjectIdentifier,
    Real,
    Unsigned,
)
from bms_tool.app import create_app
from bms_tool.bacnet_history import BacnetHistory, BacnetHistoryRequest
from bms_tool.bacnet_history_multiple import MultipleHistoryRequest
from bms_tool.connections import Bacnet
from bms_tool.field_trends import FieldTrends, FieldTrendStart
from bms_tool.storage import Store

from .test_connections import free_udp


class ContextPeer(asyncio.DatagramProtocol):
    """No application writes; literal route framing and independently selected history."""

    def __init__(self, routed=False):
        self.routed = routed
        self.requests, self.errors, self.tasks = [], [], set()
        self.value = -0.0
        self.device_checks = 0
        self.fail_device_after = None
        self.fail_object_after = None
        self.object_checks = 0
        self.hold_property = None
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.rogue = None

    def connection_made(self, transport):
        self.transport = transport
        host, port = transport.get_extra_info("sockname")
        self.endpoint = f"{host}:{port}"

    def datagram_received(self, data, source):
        task = asyncio.create_task(self.reply(data, source))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def reply(self, data, source):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            packet = data[4:]
            if self.routed:
                assert packet[:7] == b"\x01\x24\x0b\xb9\x01\x07\xff"
                request_bytes, prefix = packet[7:], b"\x01\x08\x0b\xb9\x01\x07"
            else:
                assert packet[:2] == b"\x01\x04"
                request_bytes, prefix = packet[2:], b"\x01\x00"
            request = APCISequence.decode(APDU.decode(PDU(request_bytes)))
            assert isinstance(request, (ReadPropertyRequest, ReadRangeRequest))
            obj, prop = str(request.objectIdentifier), str(request.propertyIdentifier)
            self.requests.append((type(request).__name__, obj, prop))
            if prop == self.hold_property:
                self.entered.set()
                await self.release.wait()
            if isinstance(request, ReadPropertyRequest):
                if prop == "object-identifier":
                    if obj.startswith("device,"):
                        self.device_checks += 1
                        wrong = (
                            self.fail_device_after and self.device_checks >= self.fail_device_after
                        )
                    else:
                        self.object_checks += 1
                        wrong = (
                            self.fail_object_after and self.object_checks >= self.fail_object_after
                        )
                    value = ObjectIdentifier(obj if not wrong else "device,99")
                else:
                    values = {
                        "present-value": Real(self.value),
                        "reliability": Reliability("no-fault-detected"),
                        "status-flags": StatusFlags([0, 0, 0, 0]),
                        "out-of-service": Boolean(False),
                        "object-name": CharacterString(f"Authored {obj}"),
                        "description": CharacterString("Loopback context fixture"),
                        "vendor-identifier": Unsigned(0),
                        "vendor-name": CharacterString("Authored test peer"),
                        "model-name": CharacterString("Unlisted context peer"),
                        "firmware-revision": CharacterString("fixture-1"),
                        "application-software-version": CharacterString("fixture-1"),
                        "max-apdu-length-accepted": Unsigned(480),
                        "protocol-revision": Unsigned(22),
                        "protocol-services-supported": BitString([0] * 40),
                        "protocol-object-types-supported": BitString([0] * 64),
                    }
                    if prop == "object-list":
                        objects = [
                            ObjectIdentifier(o)
                            for o in ("device,42", "trend-log,1", "analog-input,1")
                        ]
                        index = request.propertyArrayIndex
                        value = (
                            Unsigned(len(objects))
                            if index == 0
                            else objects[index - 1]
                            if index is not None
                            else ArrayOf(ObjectIdentifier)(objects)
                        )
                    else:
                        value = values.get(prop, CharacterString("Unsupported fixture metadata"))
                response = ReadPropertyACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier=request.propertyIdentifier,
                    propertyValue=Any(value),
                    **(
                        {"propertyArrayIndex": request.propertyArrayIndex}
                        if request.propertyArrayIndex is not None
                        else {}
                    ),
                )
                response.apduService = 12
            else:
                assert obj == "trend-log,1" and prop == "log-buffer"
                selection = request.range
                start = (
                    int(selection.byPosition.referenceIndex) - 1
                    if selection.byPosition is not None
                    else int(selection.bySequenceNumber.referenceSequenceNumber) - 100
                )
                count = int((selection.byPosition or selection.bySequenceNumber).count)
                chosen = [
                    LogRecord(
                        timestamp=DateTime(datetime(2026, 10, 31, 12, 0, index)),
                        logDatum=LogRecordLogDatum(realValue=-0.0 if index == 0 else index + 0.25),
                        statusFlags=[0, 0, 0, 0],
                    )
                    for index in range(max(0, start), min(3, start + count, start + 2))
                ]
                response = ReadRangeACK(
                    objectIdentifier=request.objectIdentifier,
                    propertyIdentifier="log-buffer",
                    resultFlags=[
                        int(start == 0),
                        int(start + len(chosen) >= 3),
                        int(start + len(chosen) < min(3, start + count)),
                    ],
                    itemCount=len(chosen),
                    itemData=Any(ListOf(LogRecord)(chosen)),
                    **({"firstSequenceNumber": start + 100} if chosen else {}),
                )
                response.apduService = 26
            response.apduInvokeID = request.apduInvokeID
            response.apduSeg = response.apduMor = False
            body = prefix + bytes(response.encode().encode().pduData)
            frame = b"\x81\x0a" + struct.pack(">H", len(body) + 4) + body
            if self.rogue:
                poisoned = copy.deepcopy(response)
                if isinstance(poisoned, ReadPropertyACK) and prop == "present-value":
                    poisoned.propertyValue = Any(Real(9876.5))
                if isinstance(poisoned, ReadRangeACK):
                    for item in chosen:
                        item.logDatum = LogRecordLogDatum(realValue=9876.5)
                    poisoned.itemData = Any(ListOf(LogRecord)(chosen))
                rogue_body = prefix + bytes(poisoned.encode().encode().pduData)
                self.rogue.sendto(
                    b"\x81\x0a" + struct.pack(">H", len(rogue_body) + 4) + rogue_body, source
                )
                await asyncio.sleep(0.002)
            self.transport.sendto(frame, source)
        except Exception as exc:
            self.errors.append(str(exc))

    def close(self):
        self.release.set()
        for task in self.tasks:
            task.cancel()
        self.transport.close()


async def make_peer(routed=False):
    peer = ContextPeer(routed)
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    return peer


def target(peer):
    return {
        "address": "3001:7" if peer.routed else peer.endpoint,
        "device": "device,42",
        "router": peer.endpoint if peer.routed else None,
        "dnet": 3001 if peer.routed else None,
    }


def body(peer, connector):
    return {
        "controller_target": target(peer),
        "expected_connector_config": copy.deepcopy(connector.config),
    }


def history_body(peer, connector):
    return {
        **body(peer, connector),
        "address": target(peer)["address"],
        "object_id": "trend-log,1",
        "device_timezone": "UTC",
        "mode": "sequence",
        "reference": 100,
        "count": 3,
        "page_size": 2,
    }


def trend_body(peer, connector):
    return {
        **body(peer, connector),
        "points": [
            {"signal": "sensor", "address": target(peer)["address"], "object_id": "analog-input,1"}
        ],
        "interval_seconds": 5,
        "verify_quality": True,
    }


@asynccontextmanager
async def link(tmp_path, routed):
    peer, connector = await make_peer(routed), Bacnet(Store(tmp_path))
    await connector.connect(f"127.0.0.1:{free_udp()}")
    try:
        yield peer, connector
    finally:
        connector.close()
        peer.close()
        await asyncio.sleep(0.02)
        assert not peer.errors


async def wait_for_job(service, identifier):
    async with asyncio.timeout(3):
        while True:
            job = next(j for j in service.status()["jobs"] if j["id"] == identifier)
            if job["samples"] or not job["running"]:
                return job
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("routed", [False, True])
async def test_bound_history_exact_route_identity_pages_and_immutable_restart(tmp_path, routed):
    async with link(tmp_path, routed) as (peer, connector):
        service = BacnetHistory(connector, connector.store, timeout=0.2, operation_timeout=3)
        config = copy.deepcopy(connector.config)
        result = await service.read(**history_body(peer, connector))
        assert result["identity_verified"] and result["complete"]
        assert result["controller_target"] == target(peer)
        assert result["target"] == target(peer) | {"object_id": "trend-log,1"}
        assert result["connector_config"] == config == connector.config
        assert [r["value"] for r in result["records"]] == [-0.0, 1.25, 2.25]
        assert struct.pack(">d", result["records"][0]["value"]) == bytes.fromhex("8000000000000000")
        assert len(result["pages"]) == 2 and peer.device_checks >= 4
        service.save(result["id"])
        raw = (service.directory / f"capture-{result['id']}.json").read_bytes()
        connector.close()
        reopened = BacnetHistory(connector, connector.store)
        assert reopened.capture(result["id"]) == result
        assert (service.directory / f"capture-{result['id']}.json").read_bytes() == raw
        assert not connector.commands


@pytest.mark.parametrize("routed", [False, True])
async def test_bound_poll_stages_samples_and_persists_exact_source(tmp_path, routed):
    async with link(tmp_path, routed) as (peer, connector):
        service = FieldTrends(connector, tmp_path, min_request_gap=0)
        try:
            started = await service.start(**trend_body(peer, connector))
            current = await wait_for_job(service, started["id"])
            assert current["samples"] == 1 and current["running"], current
            await service.stop(started["id"])
            samples = service.store.trends(source=started["source"])
            assert len(samples) == 1 and samples[0]["quality"] == "good"
            assert samples[0]["provenance"]["controller_target"] == target(peer)
            assert samples[0]["provenance"]["connector_config"] == connector.config
            assert not connector.commands and peer.device_checks == 2 and peer.object_checks == 2
            connector.close()
            reopened = FieldTrends(connector, tmp_path)
            assert reopened.store.trends() == samples
            assert not reopened.status()["jobs"]
            await reopened.close()
        finally:
            await service.close()


async def test_bound_32_point_cycle_fits_identity_quality_and_staging_limits(tmp_path):
    async with link(tmp_path, True) as (peer, connector):
        service = FieldTrends(connector, tmp_path, min_request_gap=0)
        request = trend_body(peer, connector)
        request["points"] = [
            {"signal": f"sensor_{index}", "address": "3001:7", "object_id": f"analog-input,{index}"}
            for index in range(1, 33)
        ]
        try:
            started = await service.start(**request)
            result = await wait_for_job(service, started["id"])
            assert result["samples"] == 32 and len(result["latest"]) == 32, result
            await service.stop(started["id"])
            assert len(peer.requests) == 194
            assert peer.device_checks == 2 and peer.object_checks == 64
            samples = service.store.trends()
            assert len(samples) == 32 and all(sample["quality"] == "good" for sample in samples)
            assert all(
                sample["provenance"]["controller_target"] == target(peer) for sample in samples
            )
            assert not connector.commands
        finally:
            await service.close()


@pytest.mark.parametrize("failure", ["device", "object", "connector"])
async def test_bound_poll_never_commits_precheck_values_after_context_changes(tmp_path, failure):
    async with link(tmp_path, True) as (peer, connector):
        peer.fail_device_after = 2 if failure == "device" else None
        peer.fail_object_after = 2 if failure == "object" else None
        service = FieldTrends(connector, tmp_path, min_request_gap=0)
        if failure == "connector":
            peer.hold_property = "present-value"
        try:
            started = await service.start(**trend_body(peer, connector))
            if failure == "connector":
                await asyncio.wait_for(peer.entered.wait(), 1)
                connector.config["instance"] += 1
                peer.release.set()
            result = await wait_for_job(service, started["id"])
            assert result["state"] == "fault" and result["samples"] == 0, result
            assert service.store.trends() == [] and not connector.commands
            assert not connector.lock.locked()
        finally:
            await service.close()


@pytest.mark.parametrize("kind", ["history", "poll"])
async def test_stale_context_and_unpaired_requests_refuse_without_wire_reads(tmp_path, kind):
    async with link(tmp_path, True) as (peer, connector):
        request = (
            history_body(peer, connector) if kind == "history" else trend_body(peer, connector)
        )
        request["expected_connector_config"]["instance"] += 1
        service = (
            BacnetHistory(connector, connector.store)
            if kind == "history"
            else FieldTrends(connector, tmp_path)
        )
        with pytest.raises(ValueError, match="interface changed"):
            await (service.read(**request) if kind == "history" else service.start(**request))
        assert not peer.requests
        request.pop("expected_connector_config")
        model = BacnetHistoryRequest if kind == "history" else FieldTrendStart
        with pytest.raises(ValueError, match="both target"):
            model(**request)
        if kind == "poll":
            await service.close()


async def test_bound_history_post_page_identity_failure_does_not_verify_wrong_controller(tmp_path):
    async with link(tmp_path, True) as (peer, connector):
        peer.fail_device_after = 3
        service = BacnetHistory(connector, connector.store, timeout=0.2, operation_timeout=3)
        result = await service.read(**history_body(peer, connector))
        assert not result["identity_verified"] and not result["complete"]
        assert len(result["records"]) == 2 and result["truncated"] and result["errors"]
        assert result["controller_target"] == target(peer)
        assert not connector.lock.locked() and not connector.commands


def test_unbound_shapes_and_existing_multiple_history_required_identity_remain_unchanged():
    legacy = BacnetHistoryRequest(
        address="127.0.0.1", object_id="trend-log,1", device_timezone="UTC"
    )
    assert "controller_target" not in legacy.model_dump()
    assert "expected_connector_config" not in legacy.model_dump()
    trend = FieldTrendStart(
        points=[{"signal": "s", "address": "127.0.0.1", "object_id": "analog-input,1"}]
    )
    assert "controller_target" not in trend.model_dump()
    with pytest.raises(ValueError):
        MultipleHistoryRequest(
            address="127.0.0.1", object_id="trend-log-multiple,1", operation_id="test-operation"
        )


@pytest.mark.parametrize("kind", ["history", "poll"])
async def test_routed_context_rejects_other_next_hop_values(tmp_path, kind):
    async with link(tmp_path, True) as (peer, connector):
        rogue, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
        )
        peer.rogue = rogue
        service = (
            BacnetHistory(connector, connector.store, timeout=0.2, operation_timeout=3)
            if kind == "history"
            else FieldTrends(connector, tmp_path, min_request_gap=0)
        )
        try:
            if kind == "history":
                result = await service.read(**history_body(peer, connector))
                assert result["identity_verified"] and result["complete"]
                assert [r["value"] for r in result["records"]] == [-0.0, 1.25, 2.25]
            else:
                started = await service.start(**trend_body(peer, connector))
                result = await wait_for_job(service, started["id"])
                assert result["samples"] == 1 and result["latest"]["sensor"]["value"] == -0.0
        finally:
            if kind == "poll":
                await service.close()
            rogue.close()


@pytest.mark.parametrize("kind", ["history", "poll"])
async def test_interface_change_while_waiting_for_owned_path_stops_before_any_reads(tmp_path, kind):
    async with link(tmp_path, True) as (peer, connector):
        await connector.lock.acquire()
        service = (
            BacnetHistory(connector, connector.store, timeout=0.2, operation_timeout=3)
            if kind == "history"
            else FieldTrends(connector, tmp_path, min_request_gap=0)
        )
        request = (
            history_body(peer, connector) if kind == "history" else trend_body(peer, connector)
        )
        try:
            if kind == "history":
                task = asyncio.create_task(service.read(**request))
                await asyncio.sleep(0)
                connector.config["instance"] += 1
                connector.lock.release()
                with pytest.raises(ValueError, match="interface changed"):
                    await task
            else:
                started = await service.start(**request)
                await asyncio.sleep(0)
                connector.config["instance"] += 1
                connector.lock.release()
                result = await wait_for_job(service, started["id"])
                assert result["state"] == "fault" and result["samples"] == 0
            assert not peer.requests
        finally:
            if connector.lock.locked():
                connector.lock.release()
            if kind == "poll":
                await service.close()


@pytest.mark.parametrize("kind", ["history", "poll"])
async def test_cancelling_selected_acquisition_retires_owned_requests_without_samples(
    tmp_path, kind
):
    async with link(tmp_path, True) as (peer, connector):
        peer.hold_property = "log-buffer" if kind == "history" else "present-value"
        service = (
            BacnetHistory(connector, connector.store, timeout=0.2, operation_timeout=3)
            if kind == "history"
            else FieldTrends(connector, tmp_path, min_request_gap=0)
        )
        try:
            if kind == "history":
                task = asyncio.create_task(service.read(**history_body(peer, connector)))
                await asyncio.wait_for(peer.entered.wait(), 1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert service.captures() == []
            else:
                started = await service.start(**trend_body(peer, connector))
                await asyncio.wait_for(peer.entered.wait(), 1)
                stopped = await service.stop(started["id"])
                assert not stopped["running"] and stopped["samples"] == 0
                assert service.store.trends() == []
            assert not connector.app._requests and not connector.app.asap.clientTransactions
            assert not connector.lock.locked()
            assert "process_npdu" not in connector.app.nsap.__dict__
            assert "indication" not in connector.app.nsap.__dict__
        finally:
            if kind == "poll":
                await service.close()


@pytest.mark.parametrize("kind", ["history", "poll"])
async def test_bound_serial_and_address_mismatch_are_explicit_refusals(tmp_path, kind):
    async with link(tmp_path, False) as (peer, connector):
        request = (
            history_body(peer, connector) if kind == "history" else trend_body(peer, connector)
        )
        changed = copy.deepcopy(request)
        if kind == "history":
            changed["address"] = f"127.0.0.1:{free_udp()}"
        else:
            changed["points"][0]["address"] = f"127.0.0.1:{free_udp()}"
        model = BacnetHistoryRequest if kind == "history" else FieldTrendStart
        with pytest.raises(ValueError, match="address differs"):
            model(**changed)
        connector.config["transport"] = "mstp"
        request["expected_connector_config"] = copy.deepcopy(connector.config)
        service = (
            BacnetHistory(connector, connector.store)
            if kind == "history"
            else FieldTrends(connector, tmp_path)
        )
        try:
            with pytest.raises(ValueError, match="explicit direct-MS/TP target"):
                await (service.read(**request) if kind == "history" else service.start(**request))
            assert not peer.requests
        finally:
            if kind == "poll":
                await service.close()


@pytest.mark.parametrize("routed", [False, True])
async def test_bound_http_history_and_poll_preserve_source_without_controller_writes(
    tmp_path, routed
):
    peer = await make_peer(routed)
    app = create_app(tmp_path)
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                headers = {"X-Studio-Token": (await client.get("/api/session")).json()["token"]}
                opened = await client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                )
                assert opened.status_code == 200, opened.text
                connector = app.state.bacnet
                response = await client.post(
                    "/api/bacnet/history/read", headers=headers, json=history_body(peer, connector)
                )
                assert response.status_code == 200, response.text
                report = response.json()
                assert report["identity_verified"] and report["target"]["device"] == "device,42"
                saved = await client.post(
                    "/api/bacnet/history/save", headers=headers, json={"id": report["id"]}
                )
                assert saved.status_code == 200, saved.text
                response = await client.post(
                    "/api/field-trends/start", headers=headers, json=trend_body(peer, connector)
                )
                assert response.status_code == 200, response.text
                job = await wait_for_job(app.state.field_trends, response.json()["id"])
                assert job["samples"] == 1, job
                stopped = await client.post(
                    "/api/field-trends/stop", headers=headers, json={"id": job["id"]}
                )
                assert stopped.status_code == 200
                assert not (await client.get("/api/bacnet/status")).json()["commands"]
    finally:
        peer.close()
        await asyncio.sleep(0.02)
        assert not peer.errors
