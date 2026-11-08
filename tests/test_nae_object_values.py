"""Authored native responses; no site capture, credential or vendor runtime."""

import hashlib

import pytest
from bms_tool.nae_https import INTEGRATION_NS, NAV_NS
from bms_tool.nae_object_values import CORE, engineering_outcome, object_values, view_definitions

REFERENCE = "Example:Engine/Device.Point"
CLASS = 4242
VERSION = "1.0"
NS = CORE[1:-1]


def response(method, content, namespace=NAV_NS):
    return (
        f'<{method}Response xmlns="{namespace}"><{method}Result>'
        f"{content}</{method}Result></{method}Response>"
    ).encode()


def prop(identity, data, attributes=""):
    return f'<property id="{identity}" {attributes}><data>{data}</data></property>'


def values(content=None, *, reference=REFERENCE, klass=CLASS, version=VERSION, view=None):
    if content is None:
        content = (
            prop(2390, '<uniqueProp category="32"/><string>Authored point</string>', 'w="1"')
            + prop(32589, "<uniqueProp><numericProp/></uniqueProp><unsignedLong>407</unsignedLong>")
            + prop(75, '<BACoid id="0">1337</BACoid>')
        )
    obj = f'<object xmlns="{NS}" ref="{reference}" classid="{klass}" classVersion="{version}">'
    if view is not None:
        return response(
            "GetView",
            f'<viewData xmlns="{NS}">{obj}<view id="{view}">'
            f'<group id="1"><subgroup id="2">{content}</subgroup></group>'
            "</view></object></viewData>",
        )
    return response("ReadPropertyMultiple", f"<items><item>{obj}{content}</object></item></items>")


def decode(raw, properties=None, **kwargs):
    return object_values(
        raw,
        reference=REFERENCE,
        class_id=CLASS,
        class_version=VERSION,
        properties=[2390, 32589, 75] if properties is None else properties,
        **kwargs,
    )


def test_current_native_values_keep_local_identity_and_source_distinct_without_write_authority():
    raw = values()
    result = decode(raw)
    by_id = {r["property_id"]: r for r in result["properties"]}
    assert by_id[75]["value"] == {"object_type": 0, "instance": 1337}
    assert by_id[32589]["value"] == 407 and not by_id[32589]["writable_advertised"]
    assert by_id[2390]["writable_advertised"] and not by_id[2390]["write_available"]
    assert result["decoded_all_values"] and not result["native_image_backup"]
    assert not result["write_available"]
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"reference": "Example:Other/Device.Point"},
        {"klass": CLASS + 1},
        {"version": "2.0"},
    ],
)
def test_native_response_identity_cannot_be_replaced_by_requested_identity(kwargs):
    with pytest.raises(ValueError, match="identity/class/version"):
        decode(values(**kwargs))


def test_creation_definition_cannot_be_used_as_current_value_or_preservation_evidence():
    raw = values().replace(b"ReadPropertyMultiple", b"GetConfigView")
    with pytest.raises(ValueError, match="current-value operation"):
        decode(raw)


def test_current_view_must_match_discovered_id_and_retains_unknown_metadata():
    content = prop(
        32589,
        '<uniqueProp><futureMetadata flag="retained"/></uniqueProp>'
        "<unsignedLong>407</unsignedLong>",
    )
    raw = values(content, view=33)
    result = object_values(
        raw, reference=REFERENCE, class_id=CLASS, class_version=VERSION, view_id=33
    )
    assert result["properties"][0]["value"] == 407
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="view differs"):
        object_values(raw, reference=REFERENCE, class_id=CLASS, class_version=VERSION, view_id=23)


@pytest.mark.parametrize(
    "content",
    [
        prop(32589, "<unsignedLong>407</unsignedLong>"),
        prop(75, '<BACoid id="0">1337</BACoid>') + prop(75, '<BACoid id="0">1338</BACoid>'),
    ],
)
def test_omitted_or_duplicate_native_values_cannot_be_complete_readback(content):
    with pytest.raises(ValueError):
        decode(values(content))


def test_native_property_failure_remains_partial_and_never_echoes_server_text():
    content = prop(2390, "<string>Authored point</string>")
    content += '<property id="32589"><error code="410">authored-sensitive-value</error></property>'
    result = decode(values(content), [2390, 32589])
    assert result["properties"][1]["status"] == "native_error"
    assert result["properties"][1]["error_codes"] == [410]
    assert "authored-sensitive-value" not in str(result)
    assert not result["decoded_all_values"]


@pytest.mark.parametrize(
    "kind,text",
    [
        ("unsignedLong", "-1"),
        ("unsignedLong", "4294967296"),
        ("float", "NaN"),
        ("float", "1_000"),
        ("float", " 1.0 "),
        ("boolean", "TRUE"),
    ],
)
def test_invalid_native_scalar_does_not_become_a_usable_value(kind, text):
    result = decode(values(prop(32589, f"<{kind}>{text}</{kind}>")), [32589])
    assert result["properties"][0]["status"] == "invalid_native_value"
    assert "value" not in result["properties"][0]


def test_structured_unknown_values_are_retained_without_fabricated_scalar():
    result = decode(
        values(prop(32589, "<futureType><opaque>retained</opaque></futureType>")), [32589]
    )
    assert result["properties"][0]["status"] == "unsupported_value"
    assert not result["decoded_all_values"] and not result["write_available"]


def test_two_alarms_with_the_same_view_type_keep_their_distinct_extension_references():
    raw = response(
        "GetViewList",
        f'<viewList xmlns="{NS}"><viewDefns>'
        '<viewDefn id="23" default="1" active="1"/>'
        f'<viewDefn id="31" reference="{REFERENCE}.Alarm1" active="1"/>'
        f'<viewDefn id="31" reference="{REFERENCE}.Alarm2" active="1"/>'
        "</viewDefns></viewList>",
    )
    rows = view_definitions(raw, reference=REFERENCE)
    assert len(rows) == 3
    assert rows[1]["view_id"] == rows[2]["view_id"] == 31
    assert rows[1]["reference"] != rows[2]["reference"]


def test_native_engineering_error_in_http_200_is_not_success_or_a_write_capability():
    raw = response(
        "GetEngView",
        f'<engViewData xmlns="{NS}"><error code="410">'
        "authored-sensitive-value</error></engViewData>",
        INTEGRATION_NS,
    )
    result = engineering_outcome(raw)
    assert result == {
        "status": "rejected",
        "row_count": 0,
        "error_codes": [410],
        "write_available": False,
    }


def test_unrelated_failed_item_cannot_be_ignored_in_an_otherwise_complete_response():
    raw = values().replace(
        b"</items>", b'<item><error xmlns="' + NS.encode() + b'" code="410"/></item></items>'
    )
    with pytest.raises(ValueError, match="object count"):
        decode(raw)


def test_global_engineering_failure_cannot_be_hidden_by_an_otherwise_returned_table():
    raw = response(
        "GetEngView",
        f'<error xmlns="{NS}" code="410">authored-sensitive-value</error>'
        f'<engViewData xmlns="{NS}"><row/></engViewData>',
        INTEGRATION_NS,
    )
    result = engineering_outcome(raw)
    assert result["status"] == "rejected" and result["row_count"] == 1
    assert result["error_codes"] == [410]
    assert "authored-sensitive-value" not in str(result)


def test_extension_view_from_a_different_object_is_rejected():
    raw = response(
        "GetViewList",
        f'<viewList xmlns="{NS}"><viewDefns>'
        '<viewDefn id="31" reference="Example:Other.Point.Alarm" active="1"/>'
        "</viewDefns></viewList>",
    )
    with pytest.raises(ValueError, match="outside"):
        view_definitions(raw, reference=REFERENCE)


def test_xml_entities_and_namespace_spoofs_cannot_supply_native_values():
    with pytest.raises(ValueError, match="Invalid native read artifact"):
        decode(b'<!DOCTYPE x [<!ENTITY x "authored">]><x>&x;</x>')
    with pytest.raises(ValueError):
        decode(values().replace(NS.encode(), b"urn:authored-wrong-core"))
