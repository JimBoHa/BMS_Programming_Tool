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
from .test_schedule_inventory import oid, text, unsigned


def workspace_device(port, *, model="Unlisted controller", vendor=999, modules=5, instance=4190090):
    app = details_device(port, programs=1, instance=instance)
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
        assert [row["phase"] for row in profile["identity_checks"]] == ["before", "after"]
        assert all(row["identity_verified"] for row in profile["identity_checks"])
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


@pytest.mark.parametrize("operation", ["profile", "inventory", "properties"])
@pytest.mark.parametrize("failure", ["timeout", "wrong_identity", "native_error", "trailing"])
async def test_failed_workspace_identity_retains_property_and_transport_evidence(
    tmp_path, operation, failure
):
    peer = await make_point_peer(routed=True, behavior=failure)
    peer.corrupt_property = "object-identifier"
    if failure == "wrong_identity":
        original = peer.value

        def wrong_identity(obj, prop, index):
            return (
                b"\xc4" + oid(8, 99) if prop == "object-identifier" else original(obj, prop, index)
            )

        peer.value = wrong_identity
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = ControllerWorkspace(client, client.store, timeout=0.1, operation_timeout=3)
    arguments = dict(address="3001:7", device="device,42", router=peer.endpoint, dnet=3001)
    if operation == "properties":
        arguments.update(object_ids=["analog-input,1"], properties=["present-value"])
    try:
        report = await getattr(service, operation)(**arguments)
        assert not report["identity_verified"] and not report["complete"], report
        (check,) = report["identity_checks"]
        assert check["phase"] == "before" and not check["identity_verified"]
        evidence = check["property_evidence"]
        assert evidence["object"] == "device,42" and evidence["property"] == "object-identifier"
        assert evidence["request_diagnostics"]["request_timeout_seconds"] == 0.1
        assert report["read_budget"]["requests"] == len(peer.requests) == 1
        assert all("identity was not verified" in error for error in report["errors"])
        if failure == "timeout":
            assert evidence["status"] == "timeout" and "timeout:" in report["errors"][0]
            assert "transport_evidence" not in evidence
        else:
            assert evidence["transport_evidence"]["next_hop"] == peer.endpoint
            if failure == "wrong_identity":
                assert evidence["value"]["value"] == "device,99"
                assert "expected device,42" in report["errors"][0]
                assert "device,99" in report["errors"][0]
            else:
                assert evidence["status"] == (
                    "native_error" if failure == "native_error" else "decode_error"
                )
                assert evidence["status"] in report["errors"][0]
        assert not client.app._requests and not client.app.asap.clientTransactions
        assert not peer.errors
    finally:
        client.close()
        peer.close()
        await asyncio.sleep(0.03)


@pytest.mark.parametrize("operation", ["profile", "inventory", "properties"])
async def test_final_identity_failure_retains_before_and_after_without_verifying_report(
    tmp_path, operation
):
    peer = await make_point_peer()
    original = peer.value
    identities = 0

    def values(obj, prop, index):
        nonlocal identities
        if int(obj[0]) == 8 and prop == "object-identifier":
            identities += 1
            return b"\xc4" + oid(8, 42 if identities == 1 else 99)
        if prop == "object-list":
            entries = [(8, 42), (0, 1)]
            return (
                unsigned(len(entries))
                if index == 0
                else b"".join(b"\xc4" + oid(*entry) for entry in entries)
                if index is None
                else b"\xc4" + oid(*entries[index - 1])
            )
        if prop in ("vendor-identifier", "protocol-revision", "max-apdu-length-accepted"):
            return unsigned(1)
        if prop in ("protocol-services-supported", "protocol-object-types-supported"):
            return b"\x82\x07\x00"
        if prop in (
            "vendor-name",
            "model-name",
            "firmware-revision",
            "application-software-version",
        ):
            return text("Authored peer")
        return original(obj, prop, index)

    peer.value = values
    client = Bacnet(Store(tmp_path))
    await client.connect(f"127.0.0.1:{free_udp()}")
    service = ControllerWorkspace(client, client.store, timeout=0.2, operation_timeout=5)
    arguments = dict(address=peer.endpoint, device="device,42")
    if operation == "properties":
        arguments.update(object_ids=["analog-input,1"], properties=["present-value"])
    try:
        report = await getattr(service, operation)(**arguments)
        assert not report["identity_verified"] and not report["complete"], report
        assert [row["phase"] for row in report["identity_checks"]] == ["before", "after"]
        assert [row["identity_verified"] for row in report["identity_checks"]] == [True, False]
        assert report["identity_checks"][1]["property_evidence"]["value"]["value"] == "device,99"
        assert not report.get("native_application_readers")
        assert not client.app._requests and not client.app.asap.clientTransactions
    finally:
        client.close()
        peer.close()
        await asyncio.sleep(0.03)


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
