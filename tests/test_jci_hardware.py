"""Authored native hardware examples and optional public manufacturer XML evidence."""

from pathlib import Path

import pytest
from bms_tool.jci_hardware import NS, JciHardwareDefinition, plan_hardware_migration


def definition(*, revision=0, instance=0, unit=64, maximum=100, default=70, alias=True):
    extra = (
        '<Input id="alternate" name="ALT" class="0" instance="0"><Value><Float min="0" max="100" default="50" units="64"/></Value></Input>'
        if alias
        else ""
    )
    return f'''<Interface xmlns="{NS}" name="ExampleSensor" revision="{revision}" schemaVersion="1.0" description="Authored schema example">
    <Device><Vendor number="5" name="Manufacturer"/><Communication><SensorActuatorBus><BACnetMSTP minAddress="199" maxAddress="206"/></SensorActuatorBus></Communication></Device>
    <Definitions><EnumerationSet id="modes"><Entry value="0">Off</Entry><Entry value="1">On</Entry></EnumerationSet><Attribute id="offset" name="Offset" type="configurable" property="956" linked="true"><Float min="-20" max="20"/></Attribute></Definitions>
    <Points defaultPrefix="EX-" updateRate="5"><Input id="temperature" name="T" description="Temperature" class="0" instance="{instance}"><Value><Float><Measurement system="imperial" min="0" max="{maximum}" default="{default}" units="{unit}"/><Measurement system="metric" min="0" max="40" default="20" units="62"/></Float></Value><Attribute ref="offset"><Float min="-10" max="10" default="0"/></Attribute></Input>{extra}
    <Output id="display" name="MODE" class="19" instance="1"><Value writeStrategy="outOfService"><Enum set="modes" default="1"/></Value></Output><Input id="request" name="REQ" class="5" instance="0"><Value><Boolean set="MSEA:set649" default="false"/></Value></Input></Points>
    <Applications><Preset id="temperatureOnly" name="Temperature"><Point ref="temperature"/></Preset></Applications>
    </Interface>'''.encode()


def test_native_profiles_resolve_measurements_attributes_local_and_external_enums():
    raw = definition()
    hardware = JciHardwareDefinition(raw)
    assert hardware.export() == raw
    assert hardware.point("temperature")["value"]["parameters"] == {
        "min": 0,
        "max": 100,
        "default": 70,
        "units": 64,
    }
    assert hardware.point("temperature", "metric")["value"]["parameters"]["units"] == 62
    attribute = hardware.point("temperature")["attributes"][0]
    assert attribute["property_id"] == 956 and attribute["linked"] is True
    assert attribute["value"]["parameters"] == {"min": -10, "max": 10, "default": 0}
    assert hardware.point("display")["value"]["enum_entries"] == {0: "Off", 1: "On"}
    assert hardware.point("display")["write_strategy"] == "outOfService"
    assert hardware.point("request")["value"]["enum_resolution"] == "external-unresolved"
    assert hardware.point("request")["value"]["parameters"]["default"] is False
    assert hardware.preset("temperatureOnly")["points"][0]["id"] == "temperature"
    assert hardware.selection(["temperature", "display"])["can_apply"] is False


def test_selection_rejects_native_aliases_duplicate_ids_missing_points_and_guessed_systems():
    hardware = JciHardwareDefinition(definition())
    assert hardware.summary()["alias_groups"] == [
        {"object_type": 0, "instance": 0, "point_ids": ["temperature", "alternate"]}
    ]
    with pytest.raises(ValueError, match="alias the same BACnet object"):
        hardware.selection(["temperature", "alternate"])
    for ids, message in [
        ([], "Select"),
        (["temperature"] * 2, "Duplicate"),
        (["missing"], "not found"),
    ]:
        with pytest.raises(ValueError, match=message):
            hardware.selection(ids)
    with pytest.raises(ValueError, match="imperial or metric"):
        hardware.summary("guess")


@pytest.mark.parametrize(
    "replacement,message",
    [
        ((b'max="100"', b'max="NaN"'), "finite"),
        ((b'min="-10" max="10"', b'min="20" max="10"'), "minimum exceeds"),
        ((b'default="70"', b'default="101"'), "outside its declared range"),
        ((b'property="956"', b'property="-1"'), "unsigned integer"),
        ((b'ref="offset"', b'ref="missing"'), "reference is missing"),
        ((b'<Enum set="modes" default="1"', b'<Enum set="modes" default="3"'), "enum default"),
        ((b'linked="true"', b'linked="maybe"'), "Boolean value"),
        (
            (b'<Input id="temperature"', b'<Input customSetting="1" id="temperature"'),
            "point attributes",
        ),
        ((b"<Value><Float>", b'<Value unknown="1"><Float>'), "Value attributes"),
    ],
)
def test_unknown_or_invalid_native_point_configuration_is_reported_not_guessed(
    replacement, message
):
    raw = definition().replace(*replacement, 1)
    hardware = JciHardwareDefinition(raw)
    assert any(message in error["error"] for error in hardware.summary()["point_errors"])
    assert hardware.export() == raw
    with pytest.raises(ValueError, match=message):
        if message == "enum default":
            hardware.selection(["display"])
        else:
            hardware.selection(["temperature"])


def test_native_xml_entities_duplicate_ids_depth_and_schema_are_rejected():
    with pytest.raises(ValueError, match="unsafe"):
        JciHardwareDefinition(
            b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><Interface>&x;</Interface>'
        )
    with pytest.raises(ValueError, match="schemaVersion"):
        JciHardwareDefinition(definition().replace(b'schemaVersion="1.0"', b'schemaVersion="2.0"'))
    with pytest.raises(ValueError, match="Duplicate native hardware point"):
        JciHardwareDefinition(definition().replace(b'id="alternate"', b'id="temperature"'))
    with pytest.raises(ValueError, match="address range"):
        JciHardwareDefinition(definition().replace(b'minAddress="199"', b'minAddress="207"'))
    with pytest.raises(ValueError, match="depth"):
        JciHardwareDefinition(
            definition().replace(
                b"</Interface>", b"<Unknown>" * 40 + b"</Unknown>" * 40 + b"</Interface>"
            )
        )


def test_unknown_native_records_preserve_bytes_and_remain_visible():
    raw = definition().replace(b"</Interface>", b'<FutureMetadata anything="opaque"/></Interface>')
    hardware = JciHardwareDefinition(raw)
    assert hardware.summary()["unknown_records"]
    assert hardware.export() == raw


def test_native_migration_reports_binding_and_program_changes_without_applying():
    before = JciHardwareDefinition(definition(alias=False))
    after = JciHardwareDefinition(
        definition(revision=1, instance=4, maximum=120, default=75, alias=False)
    )
    plan = plan_hardware_migration(before, after, ["temperature", "display"])
    assert plan["can_apply"] is False and not plan["blocking"]
    assert plan["changes"][0]["requires_rebinding"]
    assert plan["changes"][0]["requires_program_review"]
    assert plan["changes"][0]["fields"]["instance"] == {"old": 0, "new": 4}
    assert before.point("temperature")["instance"] == 0
    assert not plan_hardware_migration(before, before, ["temperature"])["requires_review"]


def test_native_migration_blocks_removed_type_changed_or_newly_aliasing_points():
    before = JciHardwareDefinition(definition(alias=False))
    removed = JciHardwareDefinition(
        definition(alias=False)
        .replace(b'id="temperature"', b'id="renamed"')
        .replace(b'ref="temperature"', b'ref="renamed"')
    )
    assert (
        "no rename"
        in plan_hardware_migration(before, removed, ["temperature"])["blocking"][0]["reason"]
    )
    changed = JciHardwareDefinition(
        definition(alias=False).replace(
            b'<Enum set="modes" default="1"/>', b'<Boolean set="modes" default="1"/>'
        )
    )
    assert (
        "value type changed"
        in plan_hardware_migration(before, changed, ["display"])["blocking"][0]["reason"]
    )
    different = JciHardwareDefinition(
        definition(alias=False).replace(b'name="ExampleSensor"', b'name="DifferentSensor"')
    )
    with pytest.raises(ValueError, match="same interface"):
        plan_hardware_migration(before, different, ["temperature"])
    before_alias = JciHardwareDefinition(definition(instance=1))
    after_alias = JciHardwareDefinition(definition(instance=0))
    alias_plan = plan_hardware_migration(before_alias, after_alias, ["temperature", "alternate"])
    assert "alias the same BACnet object" in alias_plan["blocking"][0]["reason"]


def test_native_definition_inspection_does_not_mutate_cached_metadata_or_original_bytes():
    hardware = JciHardwareDefinition(definition())
    inspected = hardware.summary()
    inspected["vendor"]["number"] = 99
    inspected["buses"][0]["min_address"] = 1
    inspected["presets"]["temperatureOnly"]["points"].clear()
    assert hardware.vendor["number"] == 5
    assert hardware.buses[0]["min_address"] == 199
    assert hardware.preset("temperatureOnly")["points"]
    assert hardware.export() == definition()


def test_native_migration_reports_bus_prefix_and_revision_changes_even_with_identical_points():
    before = JciHardwareDefinition(definition(alias=False))
    after = JciHardwareDefinition(
        definition(revision=1, alias=False)
        .replace(b'minAddress="199"', b'minAddress="200"')
        .replace(b'defaultPrefix="EX-"', b'defaultPrefix="NEW-"')
    )
    plan = plan_hardware_migration(before, after, ["temperature"])
    assert not plan["changes"] and not plan["blocking"]
    assert plan["requires_review"] is True
    assert plan["interface_changes"]["default_prefix"] == {"old": "EX-", "new": "NEW-"}
    assert plan["interface_changes"]["buses"]["new"][0]["min_address"] == 200
    assert plan["interface_changes"]["revision"] == {"old": 0, "new": 1}
    assert plan["can_apply"] is False


def test_public_manufacturer_ns8000_metadata_without_redistributing_fixture():
    source = (
        Path(__file__).resolve().parents[2]
        / "Reference_Sources/thecontrolscompany--oct/hardware/ns8000_device-info.xml"
    )
    if not source.is_file():
        pytest.skip("Optional pinned public manufacturer hardware definition is not present.")
    original = source.read_bytes()
    hardware = JciHardwareDefinition(original)
    assert hardware.name == "NS8000"
    assert len(hardware.summary()["points"]) == 25
    assert not hardware.summary()["point_errors"]
    assert not hardware.summary("metric")["point_errors"]
    assert hardware.point("temperature")["value"]["parameters"]["default"] == 72
    assert hardware.point("temperature", "metric")["value"]["parameters"]["default"] == 22
    with pytest.raises(ValueError, match="alias the same BACnet object"):
        hardware.selection(["setpoint", "warmercooler"])
    assert hardware.preset("zoneTemp")["points"][0]["id"] == "temperature"
    assert hardware.export() == original and source.read_bytes() == original
