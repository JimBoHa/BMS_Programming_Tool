from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from bacpypes3.apdu import (
    Error,
    ReadPropertyACK,
    ReadPropertyRequest,
    SimpleAckPDU,
)
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Real
from bms_tool.native_vav_configuration import NativeVavConfiguration, canonical

TARGET = {
    "address": "100:7",
    "device": "device,321",
    "router": "192.0.2.1",
    "dnet": 100,
    "balancer": "631,42",
}


@pytest.fixture
def service(tmp_path, monkeypatch):
    from bms_tool.property_evidence import PropertyEvidence

    monkeypatch.setattr(PropertyEvidence, "pin", lambda session, router: None)
    bacnet = SimpleNamespace(config={"router": TARGET["router"], "dnet": 100})
    obj = NativeVavConfiguration(bacnet, SimpleNamespace(directory=tmp_path))
    identity = {
        "object-identifier": ObjectIdentifier("device,321"),
        "object-name": "Example VAV",
        "vendor-identifier": 5,
        "model-name": "M4-CVM03050-0",
        "firmware-revision": "10.0",
        "application-software-version": "10.5",
        "system-status": 0,
    }
    values = {3887: 0.5, 3891: 1000.0, 3889: 100.0, 3893: 2000.0}
    writes = []
    behavior = {"timeout": False, "native_name": "Example VAV", "owner_lags": False}

    @asynccontextmanager
    async def path(target):
        yield {"config": dict(bacnet.config)}

    async def read(session, device, prop):
        return identity[prop]

    async def exchange(session, request, expected, before_send=None):
        if isinstance(request, ReadPropertyRequest):
            pid = int(request.propertyIdentifier)
            oid = str(request.objectIdentifier)
            instance = request.objectIdentifier[1]
            ids = {9: 3887, 10: 3891, 11: 3889, 12: 3893}
            if pid == 87:
                raise ValueError("authored native rejection") from Error(
                    service_choice=ReadPropertyRequest.service_choice,
                    errorClass="property",
                    errorCode="unknown-property",
                )
            if pid == 3365:
                value = Enumerated(ids[instance])
            elif pid == 2390:
                value = CharacterString(behavior["native_name"])
            elif pid == 32527:
                value = CharacterString(
                    "8-1/575_1.631_42"
                    + (f".2_{instance}" if oid.startswith("analog-value") else "")
                    if oid != "device,321"
                    else "8-1"
                )
            elif pid == 77 and oid.startswith("characterstring-value"):
                value = CharacterString("8-1/Preloaded App Loader.Device Name")
            elif pid == 85:
                value = (
                    CharacterString(behavior["native_name"])
                    if oid.startswith("characterstring-value")
                    else Real(values[ids[instance]])
                )
            else:
                value = CharacterString(identity["object-name"]) if pid == 77 else Real(values[pid])
            session["last_application_wire"] = {"property": pid}
            return ReadPropertyACK(
                objectIdentifier=request.objectIdentifier,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=Any(value),
            )
        if before_send:
            before_send(request)
        writes.append(request)
        assert request.priority is None and int(request.propertyIdentifier) == 85
        behavior["native_name"] = str(request.propertyValue.cast_out(CharacterString))
        if not behavior["owner_lags"]:
            identity["object-name"] = behavior["native_name"]
        if behavior["timeout"]:
            raise TimeoutError("authored lost acknowledgement")
        return SimpleAckPDU()

    obj.path = SimpleNamespace(_path=path, _read=read)
    obj.wire = SimpleNamespace(exchange=exchange)
    return obj, identity, values, writes, behavior


async def preview(obj, **kwargs):
    field = kwargs.get("field", "name")
    point = "characterstring-value,1" if field == "name" else "analog-value,10"
    return await obj.preview(
        {
            **TARGET,
            "field": "name",
            "expected": "Example VAV",
            "value": "Example VAV Two",
            "point": point,
            **kwargs,
        }
    )


async def apply(obj, plan):
    return await obj.apply(
        {
            "token": plan["token"],
            "review_sha256": plan["review_sha256"],
            "configuration_change_confirmed": True,
        }
    )


async def test_one_typed_configuration_write_is_not_a_present_value_override(service):
    obj, _, _, writes, behavior = service
    plan = await preview(obj)
    result = await apply(obj, plan)
    assert result["status"] == "verified" and behavior["native_name"] == "Example VAV Two"
    assert len(writes) == 1 and int(writes[0].propertyIdentifier) == 85
    assert str(writes[0].objectIdentifier) == "characterstring-value,1"
    assert result["readback_wire"] == {"property": 85}
    with pytest.raises(ValueError, match="already used"):
        await apply(obj, plan)
    assert len(writes) == 1


async def test_changed_firmware_or_other_settings_invalidates_review_before_dispatch(service):
    obj, identity, _, writes, _ = service
    plan = await preview(obj)
    identity["firmware-revision"] = "11.0"
    with pytest.raises(ValueError, match="changed after review"):
        await apply(obj, plan)
    assert not writes


async def test_lost_write_reply_blocks_retry_until_explicit_read_only_reconciliation(service):
    obj, _, _, writes, behavior = service
    plan = await preview(obj)
    behavior["timeout"] = True
    with pytest.raises(TimeoutError):
        await apply(obj, plan)
    with pytest.raises(ValueError, match="Reconcile"):
        await preview(obj, expected="Example VAV Two", value="Example VAV Three")
    result = await obj.reconcile(TARGET, plan["id"])
    assert result["status"] == "verified_by_readback"
    assert result["write_acknowledgement_inferred"] is False
    assert len(writes) == 1


async def test_name_change_preserves_the_existing_vav_settings(service):
    obj, identity, values, writes, _ = service
    plan = await preview(obj, field="name", expected="Example VAV", value="Example VAV Two")
    result = await apply(obj, plan)
    assert identity["object-name"] == "Example VAV Two" and result["status"] == "verified"
    assert values == {3887: 0.5, 3891: 1000.0, 3889: 100.0, 3893: 2000.0}
    assert int(writes[0].propertyIdentifier) == 85


async def test_native_name_readback_is_separate_from_standard_object_name(service):
    obj, identity, _, writes, behavior = service
    behavior["owner_lags"] = True
    plan = await preview(obj, field="name", expected="Example VAV", value="Example VAV Two")
    result = await apply(obj, plan)
    assert identity["object-name"] == "Example VAV"
    assert behavior["native_name"] == "Example VAV Two"
    assert result["status"] == "verified" and len(writes) == 1
    result = await obj.reconcile(TARGET, plan["id"])
    assert result["status"] == "verified_by_readback"


async def test_unqualified_flow_and_instance_edits_cannot_dispatch(service):
    obj, _, _, writes, _ = service
    with pytest.raises(ValueError, match="separately qualified native balancing"):
        await preview(obj, field="cool_max", expected=1000, value=50)
    with pytest.raises(ValueError, match="identity commissioning"):
        await preview(obj, field="instance", expected=321, value=322)
    assert not writes


@pytest.mark.parametrize(
    "field,value",
    [
        ("area", float("nan")),
        ("area", -1),
        ("name", "bad\nname"),
        ("unknown", 1),
        ("cool_max", True),
    ],
)
def test_invalid_native_fields_and_values_cannot_become_write_requests(field, value):
    with pytest.raises(ValueError):
        canonical(field, value)
