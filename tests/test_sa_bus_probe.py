"""Independent literal UDP peer for the native parent-controller SA diagnostic.

No vendor binary, captured controller archive, site value or live network is used.
The peer rejects every operational write and every packet addressed to the SA
network through the outer router instead of the explicitly selected parent.
"""

import asyncio
import copy
import socket
import time

import pytest
from bms_tool.connections import Bacnet
from bms_tool.sa_bus_probe import ProbeRequest, SaBusProbe
from bms_tool.storage import Store

DEVICE = (8 << 22) | 1234500
BUS = (307 << 22) | 2


def uint(value, tag=2):
    size = max(1, (value.bit_length() + 7) // 8)
    return bytes([(tag << 4) | size]) + value.to_bytes(size, "big")


def text(value):
    data = b"\x00" + value.encode()
    return bytes([0x75, len(data)]) + data


def context(data, at, number, length=None):
    tag = data[at]
    assert tag & 8 and tag >> 4 == number
    size = tag & 7
    assert 1 <= size <= 4 and (length is None or length == size)
    return int.from_bytes(data[at + 1 : at + 1 + size], "big"), at + 1 + size


class SaPeer(asyncio.DatagramProtocol):
    def __init__(self):
        self.identity = {
            75: b"\xc4" + DEVICE.to_bytes(4, "big"),
            120: uint(5),
            77: text("Authored SA diagnostic controller"),
            70: text("Independent peer"),
            44: text("10.0"),
            155: uint(12),
            12: text("1.0"),
            121: text("Authored vendor"),
            139: uint(22),
            62: uint(480),
            107: uint(3, tag=9),
            112: uint(0, tag=9),
            28: text("Independent SA communication-test peer"),
            58: text("Test bench"),
        }
        self.port = {
            2390: text("SA Bus"),
            875: uint(65000),
            2858: uint(0),
            673: b"\x11",
            81: b"\x10",
            2866: uint(1, tag=9),
        }
        self.destination = 0
        self.changed_at = 0
        self.delay = 0.11
        self.results = {199: 432, 200: 0, 201: 77}
        self.frames, self.writes, self.errors = [], [], []
        self.drop_ack, self.reject, self.never_finish, self.drop_status = False, False, False, False
        self.foreign_owner, self.dispatch = None, None
        self.written = asyncio.Event()
        self.rogue = None
        self.supported = True

    def connection_made(self, transport):
        self.transport = transport
        ip, port = transport.get_extra_info("sockname")
        self.endpoint = f"{ip}:{port}"

    def datagram_received(self, data, address):
        try:
            assert data[:2] == b"\x81\x0a" and int.from_bytes(data[2:4], "big") == len(data)
            self.frames.append(data)
            packet = data[4:]
            assert packet[:5] in (bytes.fromhex("0124083901"), bytes.fromhex("0120083901"))
            assert packet[5:7] == bytes([7, 255]), (
                "Every operation must address the selected parent"
            )
            apdu = packet[7:]
            if apdu[:2] == b"\x10\x08":
                payload = (
                    b"\x10\x00\xc4" + DEVICE.to_bytes(4, "big") + b"\x22\x01\xe0\x91\x03\x21\x05"
                )
                self.send(payload, address)
                return
            assert apdu[0] & 0xF0 == 0 and apdu[3] in (12, 15)
            invoke, service, body = apdu[2], apdu[3], apdu[4:]
            oid, cursor = context(body, 0, 0, 4)
            prop, cursor = context(body, cursor, 1)
            if service == 15:
                assert oid == BUS and prop == 1036, "Only transient Comtest Dest may be written"
                assert body[cursor] == 0x3E and body[-1] == 0x3F
                payload = body[cursor + 1 : -1]
                assert payload[0] == 0x21 and len(payload) == 2, (
                    "No priority/index/extra properties"
                )
                value = payload[1]
                self.writes.append(value)
                if self.reject and value:
                    self.send(bytes([0x50, invoke, 15, 0x91, 2, 0x91, 40]), address)
                    return
                if self.dispatch:
                    self.dispatch(value)
                self.destination, self.changed_at = value, time.monotonic()
                self.written.set()
                if self.drop_ack and value:
                    return
                self.send(bytes([0x20, invoke, 15]), address)
                return
            if cursor < len(body):
                index, cursor = context(body, cursor, 2)
                assert prop == 76 and index == 0
            assert cursor == len(body)
            if oid == DEVICE:
                value = uint(0) if prop == 76 else self.identity.get(prop)
            elif oid == BUS and self.supported:
                if prop == 1036:
                    if self.foreign_owner and self.writes:
                        self.destination = self.foreign_owner
                    value = uint(self.destination)
                elif prop == 30033:
                    if self.drop_status and self.writes:
                        return
                    pending = self.destination and (
                        self.never_finish or time.monotonic() - self.changed_at < self.delay
                    )
                    value = uint(65535 if pending else self.results.get(self.destination, 0))
                else:
                    value = self.port.get(prop)
            else:
                value = None
            response = (
                bytes([0x30, invoke, 12]) + body + b"\x3e" + value + b"\x3f"
                if value is not None
                else bytes([0x50, invoke, 12, 0x91, 2, 0x91, 32])
            )
            if self.rogue:
                self.send(response, address, transport=self.rogue)
            self.send(response, address)
        except Exception as exc:
            self.errors.append(repr(exc))

    def send(self, apdu, address, *, transport=None):
        packet = bytes.fromhex("010808390107") + apdu
        (transport or self.transport).sendto(
            b"\x81\x0a" + (len(packet) + 4).to_bytes(2, "big") + packet, address
        )


@pytest.fixture
async def sa_link(tmp_path):
    transport, peer = await asyncio.get_running_loop().create_datagram_endpoint(
        SaPeer, local_addr=("127.0.0.1", 0)
    )
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    store = Store(tmp_path)
    bacnet = Bacnet(store)
    service = SaBusProbe(bacnet, store, poll_seconds=0.01, test_seconds=0.35, settle_seconds=0.04)
    target = {
        "address": "2105:7",
        "device": "device,1234500",
        "router": peer.endpoint,
        "dnet": 2105,
    }
    await bacnet.connect(local_address=f"127.0.0.1/32:{port}", instance=4190201)
    try:
        yield peer, bacnet, service, target
    finally:
        await service.close()
        await bacnet.disconnect()
        transport.close()
        assert not peer.errors, peer.errors


async def start(service, target, **options):
    plan = await service.review(**target, mac_low=199, mac_high=201, **options)
    report = await service.start(
        token=plan["token"], review_sha256=plan["review_sha256"], diagnostic_test_confirmed=True
    )
    return plan, report


async def finished(service, report):
    await asyncio.wait_for(service.tasks[report["id"]], 15)
    return service.report(report["id"])


async def test_exact_sequential_addresses_durable_intent_and_restore(sa_link):
    peer, bacnet, service, target = sa_link
    original = copy.deepcopy(bacnet.config)
    metadata = copy.deepcopy((peer.identity, peer.port))

    def durable(value):
        (summary,) = service.reports()
        saved = service.report(summary["id"])
        assert saved["recovery_required"] and saved["last_owned_destination"] == value

    peer.dispatch = durable
    plan, report = await start(service, target)
    result = await finished(service, report)
    assert plan["port"]["destination"] == 0
    assert result["state"] == "complete" and result["restoration"] == "verified"
    assert not result["recovery_required"] and peer.destination == 0
    assert [(r["mac"], r["status"], r["code"]) for r in result["rows"]] == [
        (199, "diagnostic_error", 432),
        (200, "success_reported", 0),
        (201, "diagnostic_error", 77),
    ]
    assert all(r["observed_pending"] for r in result["rows"])
    assert peer.writes == [199, 200, 201, 0]
    assert (peer.identity, peer.port) == metadata and bacnet.config == original
    assert "process_npdu" not in bacnet.app.nsap.__dict__
    assert not service.status()["read_only"]


async def test_review_is_read_only_and_one_use_and_requires_confirmation(sa_link):
    peer, _, service, target = sa_link
    plan = await service.review(**target)
    assert not peer.writes
    body = {"token": plan["token"], "review_sha256": plan["review_sha256"]}
    with pytest.raises(ValueError, match="Confirm"):
        await service.start(**body)
    report = await service.start(**body, diagnostic_test_confirmed=True)
    await finished(service, report)
    with pytest.raises(ValueError, match="stale|used"):
        await service.start(**body, diagnostic_test_confirmed=True)


@pytest.mark.parametrize("mode", ["identity", "port", "interface", "expired"])
async def test_stale_reviews_send_no_diagnostic_write(sa_link, mode):
    peer, bacnet, service, target = sa_link
    plan = await service.review(**target)
    if mode == "identity":
        peer.identity[155] = uint(13)
    elif mode == "port":
        peer.destination = 17
    elif mode == "interface":
        bacnet.config = {**bacnet.config, "instance": 4190202}
    else:
        service.plans[plan["token"]]["deadline"] = 0
    try:
        report = await service.start(
            token=plan["token"], review_sha256=plan["review_sha256"], diagnostic_test_confirmed=True
        )
    except ValueError:
        pass
    else:
        result = await finished(service, report)
        assert result["state"] == "incomplete" and not result["recovery_required"]
    assert not peer.writes


@pytest.mark.parametrize("mode", ["unsupported", "other_owner", "pending", "wrong_vendor"])
async def test_unqualified_port_or_busy_diagnostic_refuses_review(sa_link, mode):
    peer, _, service, target = sa_link
    if mode == "unsupported":
        peer.supported = False
    elif mode == "other_owner":
        peer.destination = 198
    elif mode == "pending":
        peer.never_finish, peer.destination = True, 199
    else:
        peer.identity[120] = uint(999)
    with pytest.raises(ValueError):
        await service.review(**target)
    assert not peer.writes


async def test_ack_loss_is_one_attempt_no_next_address_and_original_selector_restored(sa_link):
    peer, _, service, target = sa_link
    peer.drop_ack = True
    _, report = await start(service, target)
    result = await finished(service, report)
    assert result["state"] == "incomplete" and result["rows"][0]["status"] == "uncertain"
    assert all(r["status"] == "not_tested" for r in result["rows"][1:])
    assert result["restoration"] == "verified" and not result["recovery_required"]
    assert peer.writes == [199, 0]
    await asyncio.sleep(0.1)
    assert peer.writes == [199, 0], "Cancelled transactions must not retry later"


async def test_rejection_does_not_claim_a_node_answered(sa_link):
    peer, _, service, target = sa_link
    peer.reject = True
    _, report = await start(service, target)
    result = await finished(service, report)
    assert result["state"] == "incomplete"
    assert not any(r["status"] == "success_reported" for r in result["rows"])
    assert not result["recovery_required"] and peer.writes == [199]


async def test_pending_timeout_stops_page_and_restores(sa_link):
    peer, _, service, target = sa_link
    peer.never_finish = True
    _, report = await start(service, target)
    result = await finished(service, report)
    assert result["rows"][0]["status"] == "test_timeout"
    assert peer.writes == [199, 0] and result["restoration"] == "verified"


async def test_cancel_finishes_current_test_then_restores_and_retires_remaining_addresses(sa_link):
    peer, _, service, target = sa_link
    peer.delay = 0.08
    _, report = await start(service, target)
    await asyncio.wait_for(peer.written.wait(), 3)
    service.cancel(report["id"])
    result = await finished(service, report)
    assert result["state"] == "cancelled" and peer.writes == [199, 0]
    assert all(r["status"] == "not_tested" for r in result["rows"][1:])


async def test_foreign_owner_is_not_overwritten_and_recovery_survives_new_service(sa_link):
    peer, bacnet, service, target = sa_link
    peer.foreign_owner = 42
    _, report = await start(service, target)
    result = await finished(service, report)
    assert result["recovery_required"] and peer.destination == 42 and peer.writes == [199]
    assert "destination changed" in result["operation_error"]
    assert "restoration refused" in result["restoration_error"]
    restarted = SaBusProbe(bacnet, service.store)
    with pytest.raises(ValueError, match="retained"):
        await restarted.review(**target)
    with pytest.raises(ValueError, match="restoration refused"):
        await restarted.recover(report["id"], restore_diagnostic_destination_confirmed=True)
    # The other diagnostic owner relinquishes its selector; Studio merely verifies zero.
    peer.foreign_owner, peer.destination = None, 0
    recovered = await restarted.recover(report["id"], restore_diagnostic_destination_confirmed=True)
    assert not recovered["recovery_required"] and peer.writes == [199]


async def test_wrong_udp_next_hop_cannot_supply_a_matching_reply(sa_link):
    peer, _, service, target = sa_link
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
    )
    peer.rogue = transport
    try:
        _, report = await start(service, target)
        result = await finished(service, report)
        assert result["state"] == "complete"
        assert result["budget"]["ignored_transport_candidates"] > 0
        assert all(
            row.get("transport_evidence", {}).get("next_hop", peer.endpoint) == peer.endpoint
            for row in result["evidence"]
        )
    finally:
        transport.close()


def test_api_requires_token_and_offline_does_not_open_a_network(tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    base = "/api/bacnet/controller/sa-bus-probe"
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(base + "/status").json()["read_only"] is False
        body = {"address": "127.0.0.1:47808", "device": "device,1234500"}
        assert client.post(base + "/review", json=body).status_code == 403
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        assert client.post(base + "/review", headers=headers, json=body).status_code == 422
        assert (
            client.post(base + "/review", headers=headers, json={**body, "mac_low": 0}).status_code
            == 422
        )
        assert client.get(base + "/reports").json() == []
        assert not client.get("/api/session").json()["field_network_open"]


async def test_cancellation_before_first_dispatch_needs_no_restore(sa_link):
    peer, _, service, target = sa_link
    _, report = await start(service, target)
    service.cancel(report["id"])
    result = await finished(service, report)
    assert result["state"] == "cancelled" and result["restoration"] == "not_needed"
    assert not result["recovery_required"] and not peer.writes
    assert all(r["status"] == "not_tested" for r in result["rows"])


async def test_status_read_failure_stops_addresses_without_claiming_absence(sa_link):
    peer, _, service, target = sa_link
    peer.drop_status = True
    _, report = await start(service, target)
    result = await finished(service, report)
    assert result["state"] == "incomplete" and result["restoration"] == "verified"
    assert result["rows"][0]["status"] == "uncertain" and peer.writes == [199, 0]
    assert any(r.get("status") == "timeout" for r in result["evidence"])


@pytest.mark.parametrize("value", [1, "true", "yes"])
def test_diagnostic_confirmation_requires_an_actual_boolean(value):
    from bms_tool.sa_bus_probe import ProbeRecovery, ProbeRun

    with pytest.raises(ValueError):
        ProbeRun(token="a" * 32, review_sha256="b" * 64, diagnostic_test_confirmed=value)
    with pytest.raises(ValueError):
        ProbeRecovery(restore_diagnostic_destination_confirmed=value)


async def test_http_job_is_restored_before_application_shutdown_disconnects(sa_link, tmp_path):
    from bms_tool.app import create_app
    from httpx import ASGITransport, AsyncClient

    peer, _, _, target = sa_link
    app = create_app(tmp_path / "separate-app")
    service = app.state.sa_bus_probe
    service.poll_seconds, service.test_seconds, service.settle_seconds = 0.01, 0.35, 0.04
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    async with app.router.lifespan_context(app):
        await app.state.bacnet.connect(local_address=f"127.0.0.1/32:{port}", instance=4190202)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            token = (await client.get("/api/session")).json()["token"]
            headers = {"X-Studio-Token": token}
            base = "/api/bacnet/controller/sa-bus-probe"
            response = await client.post(
                base + "/review", headers=headers, json={**target, "mac_low": 199, "mac_high": 201}
            )
            assert response.status_code == 200, response.text
            plan = response.json()
            response = await client.post(
                base + "/run",
                headers=headers,
                json={
                    "token": plan["token"],
                    "review_sha256": plan["review_sha256"],
                    "diagnostic_test_confirmed": True,
                },
            )
            assert response.status_code == 200, response.text
            id = response.json()["id"]
            await asyncio.wait_for(peer.written.wait(), 3)
    result = service.report(id)
    assert result["state"] == "cancelled" and result["restoration"] == "verified"
    assert not result["recovery_required"] and peer.writes == [199, 0]
    assert not app.state.bacnet.status()["connected"]


@pytest.mark.parametrize(
    "body",
    [
        {"mac_low": 0},
        {"mac_high": 255},
        {"mac_low": True},
        {"mac_low": 1, "mac_high": 17},
        {"mac_low": 206, "mac_high": 199},
        {"device": "device,4194303"},
        {"address": "2105:*"},
        {"diagnostic_object": "307,1"},
        {"property": 2858},
    ],
)
def test_only_exact_parent_and_bounded_address_pages_are_admitted(body):
    with pytest.raises(ValueError):
        ProbeRequest(
            **(
                {
                    "address": "2105:7",
                    "device": "device,1234500",
                    "router": "127.0.0.1:47808",
                    "dnet": 2105,
                }
                | body
            )
        )
