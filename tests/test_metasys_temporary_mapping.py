"""Independent literal UDP and authored HTTP configuration peers."""

import asyncio
import copy
import json
import struct
from urllib.parse import parse_qs

import httpx
import pytest
from bacpypes3.apdu import APDU, APCISequence, ReadPropertyRequest
from bacpypes3.pdu import PDU
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerWorkspace
from bms_tool.metasys_configuration_api import MONITOR_TYPES, MetasysConfigurationApi
from bms_tool.metasys_temporary_mapping import MetasysTemporaryMapping, nodes, temporary_payload
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_point_status import PointPeer
from .test_schedule_inventory import text, unsigned

BASE = "https://configuration.example"
ENGINE = "11111111-1111-4111-8111-111111111111"
PARENT = "22222222-2222-4222-8222-222222222222"
CREATED = "33333333-3333-4333-8333-333333333333"
REFERENCE = "Example:Engine"
DEVICE_CLASS = "objectTypeEnumSet.bacnetDeviceClass"


def schema(kind=DEVICE_CLASS):
    fields = {
        key: {}
        for key in [
            "name",
            "description",
            "objectCategory",
            "objectIdentifier",
            "userNameIsBacnetObjName",
            "instanceNumber",
        ]
    }
    fields["objectIdentifier"]["default"] = {"instance": 0, "bacnetObjectType": MONITOR_TYPES[kind]}
    fields["description"]["maxLength"] = 64
    if kind == DEVICE_CLASS:
        fields.update(manTimeSyncType={}, disableAutoAlarm={})
    else:
        fields.update(intrinsicAlarmingDefined={}, useRemoteAlarming={})
        if kind.endswith("AiClass"):
            fields["displayPrecision"] = {"default": "displayPrecisionEnumSet.displayPrecisionPt1"}
        else:
            fields["statesText"] = {"default": "twostateEnumSet.binarypvEnumSet"}
            fields["userSelectedStatesText"] = {"default": False}
    return {"properties": fields, "required": [key for key in fields if key != "description"]}


class EnginePeer(PointPeer):
    def __init__(self):
        super().__init__()
        self.firmware = "11.authored"
        self.engine_reference = REFERENCE
        self.vendor = 5
        self.busy = False
        self.occupied = False
        self.local_error = 31
        self.drop_local = False

    def value(self, obj, prop, index):
        if prop == "vendor-identifier":
            return unsigned(self.vendor)
        if prop == "model-name":
            return text("Authored supervisory engine")
        if prop == "firmware-revision":
            return text(self.firmware)
        if prop == "32527":
            return text(self.engine_reference)
        if prop in ("system-status", "backup-and-restore-state"):
            return b"\x91\x01" if self.busy else b"\x91\x00"
        return super().value(obj, prop, index)

    async def reply(self, data, source):
        request = APCISequence.decode(APDU.decode(PDU(data[6:])))
        assert isinstance(request, ReadPropertyRequest), "No native field mutation admitted."
        if int(request.objectIdentifier[0]) != 8 and not self.occupied:
            self.requests.append(
                (str(request.objectIdentifier), str(request.propertyIdentifier), None)
            )
            if self.drop_local:
                return
            payload = b"\x01\x00" + bytes(
                [0x50, request.apduInvokeID, 12, 0x91, 1, 0x91, self.local_error]
            )
            self.transport.sendto(
                b"\x81\x0a" + struct.pack(">H", len(payload) + 4) + payload, source
            )
        else:
            await super().reply(data, source)


class ConfigurationPeer:
    def __init__(self):
        self.posts = []
        self.requests = []
        self.engine_ref = REFERENCE
        self.parent_ref = REFERENCE + "/Bus"
        self.parent_class = "objectTypeEnumSet.bacnetIntegrationClass"
        self.create_schema = schema()
        self.permission = True
        self.nonce_conflict = None
        self.mode = "normal"
        self.created = None

    def parent(self):
        return {
            "id": PARENT,
            "itemReference": self.parent_ref,
            "objectType": self.parent_class,
            "parentUrl": BASE + "/api/v6/objects/" + ENGINE,
            "items": [],
        }

    async def handle(self, request):
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/GetPreLoginState"):
            return httpx.Response(200, json={})
        if path.endswith("/LogIn"):
            return httpx.Response(
                200,
                json={
                    "IsAuthenticated": True,
                    "IsTermsAndConditionsAccepted": True,
                    "access_token": "authored-token",
                },
            )
        assert request.headers["Authorization"] == "Bearer authored-token"
        if "/networkDevices/" in path:
            return httpx.Response(
                200,
                json={
                    "id": ENGINE,
                    "itemReference": self.engine_ref,
                    "objectType": "objectTypeEnumSet.n50Class",
                },
            )
        if path.endswith("/enums/objectCategoryEnumSet"):
            assert parse_qs(request.url.query.decode())["permission"] == ["modifyConfigItems"]
            return httpx.Response(
                200,
                json={
                    "oneOf": [{"const": "objectCategoryEnumSet.generalCategory"}]
                    if self.permission
                    else []
                },
            )
        if path.endswith("/enums/timeSyncChoiceEnumSet"):
            return httpx.Response(
                200, json={"oneOf": [{"const": "timeSyncChoiceEnumSet.tscNoTimeBcast"}]}
            )
        if "/schemas/objectTypes/" in path:
            return httpx.Response(200, json={"schema": self.create_schema})
        if request.method == "GET" and path.endswith("/objects") and "pathTo" in str(request.url):
            parent = self.parent()
            if parse_qs(request.url.query.decode())["pathTo"] == [CREATED]:
                parent["items"].append(
                    {
                        "id": CREATED,
                        "itemReference": self.created["item"]["itemReference"],
                        "parentUrl": BASE + "/api/v6/objects/" + PARENT,
                    }
                )
            return httpx.Response(
                200,
                json={
                    "items": [{"id": ENGINE, "itemReference": self.engine_ref, "items": [parent]}]
                },
            )
        if path.endswith("/objects/" + PARENT + "/objects"):
            parent = self.parent()
            if self.created:
                parent["items"].append(
                    {"id": CREATED, "itemReference": self.created["item"]["itemReference"]}
                )
            if self.nonce_conflict:
                parent["items"].append(
                    {"id": CREATED, "itemReference": self.nonce_conflict, "items": []}
                )
            return httpx.Response(200, json={"items": [parent]})
        if request.method == "POST" and path.endswith("/objects"):
            body = json.loads(request.content)
            self.posts.append(body)
            item = {
                **copy.deepcopy(body["item"]),
                "id": CREATED,
                "itemReference": self.parent_ref + "." + body["localUniqueIdentifier"],
            }
            self.created = {
                "item": item,
                "objectType": body["objectType"],
                "parentUrl": BASE + "/api/v6/objects/" + PARENT,
            }
            if self.mode == "timeout":
                raise httpx.ReadTimeout("Authored lost reply")
            if self.mode == "reject":
                return httpx.Response(403, json={"message": "Authored refusal"})
            location = BASE + "/api/private-api/v6/objects/" + CREATED
            if self.mode == "foreign_location":
                location = location.replace("configuration.example", "other.example")
            return httpx.Response(
                200 if self.mode == "ui_proxy_200" else 201, headers={"Location": location}
            )
        if path.endswith("/objects/" + CREATED):
            result = copy.deepcopy(self.created)
            if self.mode == "wrong_created":
                result["item"]["objectIdentifier"]["instance"] += 1
            if self.mode == "ui_proxy_200":
                result["item"].pop("itemReference")
            return httpx.Response(200, json=result)
        if path.endswith("/objects/" + CREATED + "/attributes/instanceNumber"):
            return httpx.Response(
                200,
                json={
                    "item": {
                        "instanceNumber": True
                        if self.mode == "boolean_source"
                        else self.posts[-1]["item"]["instanceNumber"]
                    }
                },
            )
        # A full parent/engine Focus view is deliberately unavailable. Creation
        # uses only the documented, permitted tree and network-device metadata.
        if path.endswith("/objects/" + PARENT) or path.endswith("/objects/" + ENGINE):
            return httpx.Response(403, json={"message": "No full System-object view"})
        raise AssertionError((request.method, str(request.url)))


@pytest.fixture
async def mapping(tmp_path):
    peer = EnginePeer()
    await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: peer, local_addr=("127.0.0.1", 0)
    )
    bacnet = Bacnet(Store(tmp_path / "bacnet"))
    await bacnet.connect(f"127.0.0.1:{free_udp()}")
    workspace = ControllerWorkspace(bacnet, bacnet.store, timeout=0.08, operation_timeout=4)
    remote = ConfigurationPeer()
    http = httpx.AsyncClient(base_url=BASE, transport=httpx.MockTransport(remote.handle))
    api = MetasysConfigurationApi(BASE, http)
    await api.login(username="authored-user", password="authored-password")
    service = MetasysTemporaryMapping(workspace, api, tmp_path / "journal")
    args = dict(
        target={"address": peer.endpoint, "device": "device,42"},
        engine_id=ENGINE,
        parent_id=PARENT,
        object_type=DEVICE_CLASS,
        local_instance=501,
        source_instance=77,
    )
    try:
        yield service, args, peer, remote, api
    finally:
        await api.close()
        bacnet.close()
        peer.close()
        await asyncio.sleep(0.03)


async def test_one_reviewed_create_uses_permitted_metadata_and_preserves_an_immutable_intent(
    mapping,
):
    service, args, peer, remote, _ = mapping
    review = await service.prepare(**args)
    assert not remote.posts and review["source_edit_qualified"] is False
    # Caller edits cannot replace the retained request or direct a value command.
    review["payload"]["item"]["instanceNumber"] = 999
    result = await service.create(
        **{k: review[k] for k in ["operation_id", "token", "review_sha256"]}
    )
    assert result["status"] == "created_configuration_verified"
    assert len(remote.posts) == 1 and remote.posts[0]["item"]["instanceNumber"] == 77
    assert remote.posts[0]["item"]["manTimeSyncType"] == "timeSyncChoiceEnumSet.tscNoTimeBcast"
    assert remote.posts[0]["item"]["disableAutoAlarm"] is True
    assert "presentValue" not in json.dumps(remote.posts)
    records = service.records(review["operation_id"])
    intent = json.dumps(records["intent"])
    assert records["intent"]["status"] == "outcome_uncertain"
    assert "authored-password" not in intent and "authored-token" not in intent
    assert records["result"]["native_activation_verified"] is False
    assert not peer.errors and not service.workspace.bacnet.status()["commands"]
    with pytest.raises(ValueError, match="consumed"):
        await service.create(**{k: review[k] for k in ["operation_id", "token", "review_sha256"]})
    assert len(remote.posts) == 1


@pytest.mark.parametrize(
    "change",
    [
        "firmware",
        "engine_ref",
        "vendor",
        "busy",
        "occupied",
        "no_absence",
        "wrong_absence",
        "parent",
        "schema",
        "permission",
        "session",
        "token",
        "hash",
        "expired",
        "nonce",
    ],
)
async def test_stale_wrong_or_unverified_preconditions_do_not_dispatch(mapping, change):
    service, args, peer, remote, api = mapping
    review = await service.prepare(**args)
    values = {k: review[k] for k in ["operation_id", "token", "review_sha256"]}
    if change == "firmware":
        peer.firmware = "changed"
    elif change == "engine_ref":
        peer.engine_reference = "Other:Engine"
    elif change == "vendor":
        peer.vendor = 999
    elif change == "busy":
        peer.busy = True
    elif change == "occupied":
        peer.occupied = True
    elif change == "no_absence":
        peer.drop_local = True
    elif change == "wrong_absence":
        peer.local_error = 32
    elif change == "parent":
        remote.parent_ref += "-changed"
    elif change == "schema":
        remote.create_schema["properties"]["changed"] = {}
    elif change == "permission":
        remote.permission = False
    elif change == "session":
        await api.login(username="authored-user", password="authored-password")
    elif change == "token":
        values["token"] = "wrong"
    elif change == "hash":
        values["review_sha256"] = "0" * 64
    elif change == "expired":
        original = service._plans[review["operation_id"]]
        service._plans[review["operation_id"]] = (*original[:2], original[2] - 100, original[3])
    else:
        remote.nonce_conflict = review["expected_reference"]
    with pytest.raises(ValueError):
        await service.create(**values)
    assert not remote.posts and not service.records(review["operation_id"])


@pytest.mark.parametrize("mode", ["timeout", "reject", "foreign_location", "wrong_created"])
async def test_uncertain_or_rejected_create_is_never_replayed_or_called_verified(mapping, mode):
    service, args, _, remote, _ = mapping
    remote.mode = mode
    review = await service.prepare(**args)
    values = {k: review[k] for k in ["operation_id", "token", "review_sha256"]}
    with pytest.raises((ValueError, httpx.HTTPError)):
        await service.create(**values)
    records = service.records(review["operation_id"])
    assert len(remote.posts) == 1 and "intent" in records and "result" not in records
    with pytest.raises(ValueError, match="consumed"):
        await service.create(**values)
    assert len(remote.posts) == 1


async def test_lost_reply_can_be_reconciled_read_only_after_restart(mapping):
    service, args, _, remote, api = mapping
    remote.mode = "timeout"
    review = await service.prepare(**args)
    with pytest.raises(httpx.ReadTimeout):
        await service.create(**{k: review[k] for k in ["operation_id", "token", "review_sha256"]})
    restarted = MetasysTemporaryMapping(service.workspace, api, service.directory)
    result = await restarted.reconcile(review["operation_id"])
    assert result["status"] == "created_configuration_verified"
    assert result["native_activation_verified"] is False
    assert len(remote.posts) == 1
    assert "result" in restarted.records(review["operation_id"])


async def test_unresolved_creation_blocks_another_dispatch_on_same_engine(mapping):
    service, args, _, remote, api = mapping
    remote.mode = "timeout"
    review = await service.prepare(**args)
    with pytest.raises(httpx.ReadTimeout):
        await service.create(**{k: review[k] for k in ["operation_id", "token", "review_sha256"]})
    remote.created = None  # Navigation absence is not evidence of rejection.
    restarted = MetasysTemporaryMapping(service.workspace, api, service.directory)
    result = await restarted.reconcile(review["operation_id"])
    assert result["status"] == "outcome_uncertain"
    second = await restarted.prepare(**args)
    with pytest.raises(ValueError, match="reconciliation"):
        await restarted.create(**{k: second[k] for k in ["operation_id", "token", "review_sha256"]})
    assert len(remote.posts) == 1


async def test_boolean_source_echo_is_not_an_instance_number(mapping):
    service, args, _, remote, _ = mapping
    remote.mode = "boolean_source"
    args["source_instance"] = 1
    review = await service.prepare(**args)
    with pytest.raises(ValueError, match="source"):
        await service.create(**{k: review[k] for k in ["operation_id", "token", "review_sha256"]})
    assert "result" not in service.records(review["operation_id"])


async def test_ui_proxy_200_location_and_navigation_reference_are_independently_verified(mapping):
    service, args, _, remote, _ = mapping
    remote.mode = "ui_proxy_200"
    review = await service.prepare(**args)
    result = await service.create(
        **{k: review[k] for k in ["operation_id", "token", "review_sha256"]}
    )
    assert result["status"] == "created_configuration_verified"
    assert "itemReference" not in result["created"]["item"]
    assert result["created_context"]["itemReference"] == review["expected_reference"]


@pytest.mark.parametrize("kind", list(MONITOR_TYPES))
def test_creation_payloads_keep_local_and_remote_identity_distinct_without_commands(kind):
    payload = temporary_payload(
        schema(kind),
        parent_id=PARENT,
        object_type=kind,
        local_instance=501,
        source_instance=77,
        operation_id="a" * 32,
    )
    assert payload["item"]["objectIdentifier"]["instance"] == 501
    assert payload["item"]["instanceNumber"] == 77
    assert len(payload["localUniqueIdentifier"]) <= 32
    assert not any(
        key in payload["item"]
        for key in ["presentValue", "priority", "autoRestore", "weeklySchedule"]
    )
    if kind != DEVICE_CLASS:
        assert payload["item"]["intrinsicAlarmingDefined"] is False
        assert payload["item"]["useRemoteAlarming"] is False


def test_schema_and_tree_ambiguities_are_refused():
    value = schema()
    value["properties"]["instanceNumber"]["readOnly"] = True
    with pytest.raises(ValueError, match="schema"):
        temporary_payload(
            value,
            parent_id=PARENT,
            object_type=DEVICE_CLASS,
            local_instance=501,
            source_instance=77,
            operation_id="a" * 32,
        )
    with pytest.raises(ValueError, match="Duplicate"):
        nodes({"items": [{"id": ENGINE}, {"id": ENGINE}]})
