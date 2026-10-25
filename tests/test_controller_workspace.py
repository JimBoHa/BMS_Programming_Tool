"""Model-independent controller reads against actual authored BACnet peers."""

import asyncio
import copy

import pytest
from bacpypes3.basetypes import DeviceObjectReference
from bacpypes3.object import AnalogInputObject, StructuredViewObject
from bacpypes3.primitivedata import ObjectIdentifier
from bms_tool.bacnet_read import close_application
from bms_tool.connections import Bacnet
from bms_tool.controller_workspace import ControllerWorkspace
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_device_details import details_device
from .test_device_details import routed_details as routed_details
from .test_point_status import make_point_peer
from .test_schedule_inventory import text, unsigned


def workspace_device(port, *, model="Unlisted controller", vendor=999, modules=5):
    app = details_device(port, programs=1)
    app.device_object.modelName = model
    app.device_object.vendorIdentifier = vendor
    for number in range(1, modules + 2):
        app.add_object(
            AnalogInputObject(
                objectIdentifier=("analog-input", number),
                objectName=f"Actual input {number}",
                description=f"Configured sensor {number}",
                presentValue=20.0 + number,
                units="degrees-celsius",
                statusFlags=[0, 0, 0, 0],
                reliability="no-fault-detected",
                outOfService=False,
            )
        )
    for number in range(1, modules + 1):
        app.add_object(
            StructuredViewObject(
                objectIdentifier=("structured-view", number),
                objectName=f"Exposed I/O module {number}",
                nodeType="device",
                subordinateList=[DeviceObjectReference(objectIdentifier=("analog-input", number))],
            )
        )
    return app


@pytest.mark.parametrize(
    "vendor,model,modules",
    [
        (5, "Family A", 0),
        (343, "Family B", 1),
        (999, "Never registered model", 5),
        (42, "Different family", 7),
    ],
)
async def test_capability_inventory_and_live_properties_do_not_depend_on_model(
    tmp_path, vendor, model, modules
):
    port = free_udp()
    server = workspace_device(port, vendor=vendor, model=model, modules=modules)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = ControllerWorkspace(client, client.store, timeout=0.5, operation_timeout=15)
    target = {"address": f"127.0.0.1:{port}", "device": "device,4190090"}
    try:
        profile = await service.profile(**target)
        assert profile["identity_verified"], profile
        assert profile["properties"]["model-name"]["value"] == model
        assert profile["properties"]["vendor-identifier"]["value"] == vendor
        assert profile["adapter"] == "bacnet-standard" and not profile["native_logic"]["available"]
        inventory = await service.inventory(**target)
        assert inventory["identity_verified"] and inventory["complete"], inventory
        assert len(inventory["objects"]) == len(server.objectIdentifier)
        assert len([row for row in inventory["objects"] if row["structured_group"]]) == modules
        values = await service.properties(
            **target,
            object_ids=["analog-input,1"],
            properties=["object-name", "present-value", "units"],
        )
        assert values["identity_verified"] and values["complete"], values
        assert values["objects"][0]["properties"]["present-value"]["value"] == 21
        server.get_object_id(ObjectIdentifier(("analog-input", 1))).presentValue = 37.25
        changed = await service.properties(
            **target, object_ids=["analog-input,1"], properties=["present-value"]
        )
        assert changed["objects"][0]["properties"]["present-value"]["value"] == 37.25
        if modules:
            grouped = await service.properties(
                **target,
                object_ids=["structured-view,1"],
                properties=["object-name", "subordinate-list"],
            )
            assert (
                grouped["identity_verified"]
                and grouped["objects"][0]["properties"]["subordinate-list"]["status"] == "ok"
            )
        assert not client.app._requests and not client.app.asap.clientTransactions
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


async def test_inventory_paging_keeps_source_and_exact_object_membership(tmp_path):
    port = free_udp()
    server = workspace_device(port, modules=7)
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = ControllerWorkspace(client, client.store)
    target = {"address": f"127.0.0.1:{port}", "device": "device,4190090"}
    try:
        first = await service.inventory(**target, limit=4)
        second = await service.inventory(**target, offset=first["next_offset"], limit=4)
        assert first["identity_verified"] and second["identity_verified"]
        assert not set(row["object"] for row in first["objects"]) & set(
            row["object"] for row in second["objects"]
        )
        assert first["target"] == second["target"]
    finally:
        client.close()
        close_application(server)
        await asyncio.sleep(0.02)


async def test_pinned_route_preserves_interface_and_rejects_foreign_peer(routed_details):
    _, client, _, router, rogue = routed_details
    router.rogue = rogue
    before = copy.deepcopy(client.config)
    service = ControllerWorkspace(client, client.store)
    result = await service.inventory(
        address="3001:7", device="device,4190090", router=router.endpoint, dnet=3001
    )
    assert result["identity_verified"] and result["complete"], result
    assert result["read_budget"]["ignored_transport_candidates"] > 0 and client.config == before
    assert not client.app._requests and not client.app.asap.clientTransactions


async def test_unknown_vendor_primitive_and_noncanonical_quality_remain_distinct(tmp_path):
    peer = await make_point_peer(routed=True)
    original = peer.value

    def values(obj, prop, index):
        if prop == "vendor-identifier":
            return unsigned(999)
        if prop == "512":
            return text("Actual vendor setting")
        if prop == "status-flags":
            return b"\x82\x06\x00"
        if prop == "out-of-service":
            return b"\x12"
        return original(obj, prop, index)

    peer.value = values
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    try:
        service = ControllerWorkspace(client, client.store)
        report = await service.properties(
            address="3001:7",
            device="device,42",
            router=peer.endpoint,
            dnet=3001,
            object_ids=["analog-input,1"],
            properties=["512", "status-flags", "out-of-service"],
        )
        assert report["identity_verified"], report
        props = report["objects"][0]["properties"]
        assert props["512"]["status"] == "ok" and props["512"]["value"] == "Actual vendor setting"
        assert "wire tag" in props["512"]["decoding"]
        for prop in ("status-flags", "out-of-service"):
            assert props[prop]["status"] == "invalid_native_value" and "value" not in props[prop]
        assert not client.app._requests and not client.app.asap.clientTransactions
    finally:
        client.close()
        peer.close()
        await asyncio.sleep(0.03)
