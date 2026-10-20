"""Actual BACpypes datatypes, wire round trips and bounded JSON evidence."""

import asyncio
import base64
import hashlib
import json
from datetime import datetime

import pytest
from bacpypes3.basetypes import (
    DateTime,
    DeviceAddress,
    ObjectPropertyReference,
    PriorityValue,
    Recipient,
)
from bacpypes3.constructeddata import Any
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    Double,
    Null,
    OctetString,
    Real,
    Unsigned,
)
from bms_tool.app import create_app
from bms_tool.bacnet_values import MAX_BYTES, MAX_ITEMS, json_value
from bms_tool.connections import Bacnet
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from tests.test_connections import application, free_udp, point


def strict_roundtrip(value):
    return json.loads(json.dumps(json_value(value), allow_nan=False))


def test_actual_protocol_boolean_numeric_and_priority_choice_shapes_are_native_json():
    assert type(json_value(Boolean(True))) is bool
    assert type(json_value(Boolean(False))) is bool
    assert strict_roundtrip([Real(12.5), Unsigned(7), Boolean(False)]) == [12.5, 7, False]
    assert strict_roundtrip(PriorityValue(boolean=Boolean(True))) == {
        "type": "boolean",
        "value": True,
    }
    assert strict_roundtrip(PriorityValue(null=Null(()))) == {"type": "null", "value": None}


@pytest.mark.parametrize(
    "value,text", [(float("nan"), "NaN"), (float("inf"), "Infinity"), (-float("inf"), "-Infinity")]
)
def test_nonfinite_device_values_remain_explicit_typed_evidence(value, text):
    assert strict_roundtrip(Real(value)) == {"type": "nonfinite-number", "value": text}
    assert strict_roundtrip(Double(value)) == {"type": "nonfinite-number", "value": text}


def test_schema_backed_sequences_retain_fields_and_raw_bacnet_clock_without_object_repr():
    reference = ObjectPropertyReference(
        objectIdentifier="analog-input,1", propertyIdentifier="present-value"
    )
    result = strict_roundtrip(reference)
    assert result == {"objectIdentifier": [0, 1], "propertyIdentifier": 85}
    assert "object at" not in json.dumps(result)
    stamp = strict_roundtrip(DateTime(datetime(2026, 10, 19, 12, 30)))
    assert stamp == {"date": [126, 10, 19, 1], "time": [12, 30, 0, 0]}


def test_octet_strings_and_unknown_any_tags_preserve_exact_encoded_identity():
    raw = b"\x00\xff\x00native"
    assert strict_roundtrip(OctetString(raw)) == {
        "type": "octet-string",
        "encoding": "base64",
        "value": base64.b64encode(raw).decode(),
    }
    opaque = Any(CharacterString("unknown proprietary value"))
    encoded = bytes(opaque.tagList.encode().pduData)
    result = strict_roundtrip(opaque)
    assert result["type"] == "bacnet-opaque"
    assert result["sha256"] == hashlib.sha256(encoded).hexdigest()
    assert result["encoded_bytes"] == len(encoded)
    assert base64.b64decode(result["base64"]) == encoded
    assert not result["truncated"]
    large = Any(OctetString(bytes(range(256)) * 8))
    result = strict_roundtrip(large)
    assert result["truncated"] and len(base64.b64decode(result["base64"])) == 1024
    assert result["sha256"] == hashlib.sha256(bytes(large.tagList.encode().pduData)).hexdigest()


def test_large_integers_are_never_rounded_into_javascript_numbers():
    for value in [2**53, -(2**53), 2**80 + 1]:
        assert strict_roundtrip(value) == {
            "type": "integer",
            "encoding": "decimal",
            "value": str(value),
        }


def test_recursive_and_excessive_values_fail_explicitly_instead_of_partial_serialization():
    recursive = []
    recursive.append(recursive)
    with pytest.raises(ValueError, match="recursive"):
        json_value(recursive)
    nested = 1
    for _ in range(18):
        nested = [nested]
    for value, message in [
        (nested, "depth"),
        ([0] * MAX_ITEMS, "item"),
        ("x" * (MAX_BYTES + 1), "KiB"),
        (object(), "Unsupported"),
        (2**5000, "integer"),
    ]:
        with pytest.raises(ValueError, match=message):
            json_value(value)


@pytest.mark.asyncio
async def test_actual_udp_read_back_bacnet_boolean_and_nan_without_json_serialization_failure(
    tmp_path,
):
    server_port = free_udp()
    server = application(server_port, 4190030)
    analog = point()
    analog.presentValue = float("nan")
    server.add_object(analog)
    client = Bacnet(Store(tmp_path))
    try:
        await client.connect(f"127.0.0.1:{free_udp()}")
        target = f"127.0.0.1:{server_port}"
        out_of_service = await client.app.read_property(target, "analog-value,1", "out-of-service")
        value = await client.app.read_property(target, "analog-value,1", "present-value")
        assert type(out_of_service) is Boolean
        assert strict_roundtrip(out_of_service) is False
        assert strict_roundtrip(value) == {"type": "nonfinite-number", "value": "NaN"}
        assert (await client.read(target, "analog-value,1", "out-of-service"))["value"] is False
        assert (await client.read(target, "analog-value,1"))["value"] == {
            "type": "nonfinite-number",
            "value": "NaN",
        }
    finally:
        await client.disconnect()
        server.close()
        await asyncio.sleep(0.05)


def test_production_http_preserves_actual_wire_boolean_nonfinite_and_constructed_values(tmp_path):
    port = free_udp()
    target = f"127.0.0.1:{port}"
    with TestClient(create_app(tmp_path)) as client:
        server = client.portal.call(application, port, 4190031)

        def configure():
            analog = point()
            analog.presentValue = float("nan")
            server.add_object(analog)
            server.device_object.timeSynchronizationRecipients = [
                Recipient(address=DeviceAddress(networkNumber=2105, macAddress=b"\x4f"))
            ]

        client.portal.call(configure)
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        try:
            assert (
                client.post(
                    "/api/bacnet/connect",
                    headers=headers,
                    json={"local_address": f"127.0.0.1:{free_udp()}"},
                ).status_code
                == 200
            )
            results = {}
            for obj, prop in [
                ("analog-value,1", "out-of-service"),
                ("analog-value,1", "present-value"),
                ("device,4190031", "time-synchronization-recipients"),
            ]:
                response = client.post(
                    "/api/bacnet/read",
                    headers=headers,
                    json={"address": target, "object_id": obj, "property_id": prop},
                )
                assert response.status_code == 200, response.text
                results[prop] = response.json()["value"]
            assert results["out-of-service"] is False
            assert results["present-value"] == {"type": "nonfinite-number", "value": "NaN"}
            assert results["time-synchronization-recipients"] == [
                {
                    "type": "address",
                    "value": {
                        "networkNumber": 2105,
                        "macAddress": {
                            "type": "octet-string",
                            "encoding": "base64",
                            "value": "Tw==",
                        },
                    },
                }
            ]
        finally:
            client.post("/api/bacnet/disconnect", headers=headers, json={})
            client.portal.call(server.close)
