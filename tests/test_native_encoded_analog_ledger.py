"""Immutable recorded analog movement admits evidence without field/source authority."""

import copy
from contextlib import aclosing

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_encoded_analog_ledger import PROFILE, encoded_analog_terminal_reference
from bms_tool.native_inputs import NativeInputCompiler

from .test_change_ledger import application as application
from .test_change_ledger import native, query
from .test_native_applications import native_link
from .test_native_encoded_terminal_input import edit, nonlinear
from .test_native_encoded_terminal_transfer import peer_for
from .test_native_input_transfer import apply, preview
from .test_native_terminal_labels import observed_shape


def encoded_analog_body(*, linear=False):
    files = observed_shape(binary=False)
    c = NativeInputCompiler(files if linear else nonlinear(files))
    output, compiled = c.compile(edit(c))
    name = "Authored controller"
    return {
        "change_kind": "input",
        "operation_profile": compiled["profile"],
        "input_edit": compiled["input_edit"],
        "compilation": compiled,
        "native_payload_sha256": sha(MoiIdentity(output).data),
        "payload_sha256": sha(output),
        "identity": {
            "device": "device,5136",
            "object-name": name,
            "model-name": "M4-CVM03050-0",
            "vendor-identifier": 5,
        },
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": name,
        "new_name": name,
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
    }


async def seed_encoded_analog_records(directory):
    with pytest.MonkeyPatch.context() as patch:
        async with aclosing(native_link.__wrapped__(directory, patch)) as generator:
            link = await anext(generator)
            peer, service = peer_for(link, True)
            _, plan = await preview(
                link, edit(NativeInputCompiler(peer.files)), "encoded-analog-ledger"
            )
            result = await service.apply_input(**apply(plan, "encoded-analog-ledger"))
            assert result["result"]["status"] == "verified", result
            return result


@pytest.mark.parametrize("linear", [False, True])
def test_recorded_analog_move_has_typed_configuration_presence_encoding_and_no_authority(linear):
    body = encoded_analog_body(linear=linear)
    original = copy.deepcopy(body)
    result = encoded_analog_terminal_reference(body)
    value = result["native_encoded_analog_terminal"]
    assert (
        result["object"] == "analog-input,101"
        and value["state"] == "recorded"
        and value["profile"] == PROFILE
    )
    assert (
        value["old_slot"] == 1
        and value["slot"] == 3
        and value["device_type_character_encoding"] == 4
    )
    assert value["configuration_storage"]["linear_output_endpoints_present"] is linear
    if not linear:
        assert value["stored_configuration"]["output_low"] is None
    assert value["stored_configuration"] == body["compilation"]["stored_configuration"]
    assert (
        value["confirmations_recorded"]
        and not value["transfer_authority"]
        and "current value" in value["scope"]
    )
    value["stored_configuration"]["input_high"] = 999
    assert body == original


@pytest.mark.parametrize(
    "fault",
    [
        "profile",
        "action",
        "compiler",
        "seal",
        "source",
        "payload",
        "native-payload",
        "configuration",
        "storage",
        "real32",
        "presence",
        "confirm",
        "identity",
        "instance-bool",
        "reference",
        "slot-bool",
        "charset-bool",
        "label",
        "overlap",
        "allocation",
        "count",
        "changes",
    ],
)
def test_malformed_analog_record_keeps_original_without_structured_authority(fault):
    b = encoded_analog_body()
    c = b["compilation"]
    p = c["terminal_compilation"]
    if fault == "profile":
        b["operation_profile"] = "native-local-universal-input-transfer/2"
    if fault == "action":
        b["input_edit"]["action"] = "terminal"
    if fault == "compiler":
        c["profile"] = "unsupported/3"
    if fault == "seal":
        p["compilation_sha256"] = "0" * 64
    if fault == "source":
        c["parameter_merge"]["output_sha256"] = "0" * 64
    if fault == "payload":
        p["payloads"][0]["after"] = "02"
    if fault == "native-payload":
        b["native_payload_sha256"] = "0" * 64
    if fault == "configuration":
        c["stored_configuration"]["setup"] = True
    if fault == "storage":
        c["configuration_storage"]["linear_output_endpoints_present"] = True
    if fault == "real32":
        c["stored_configuration"]["input_low"] = 0.1
    if fault == "presence":
        c["configuration_storage"]["present_properties"] = [True]
    if fault == "confirm":
        b["physical_wiring_confirmed"] = 1
    if fault == "identity":
        b["identity"]["vendor-identifier"] = 99
    if fault == "instance-bool":
        b["old_instance"] = True
    if fault == "reference":
        c["record_ref"] = "controller/module/0_101"
        p["ref"] = c["record_ref"]
    if fault == "slot-bool":
        p["old_slot"] = True
    if fault == "charset-bool":
        p["device_type_character_encoding"] = False
    if fault == "label":
        p["payloads"][1]["after"] = "00554920494e33"
    if fault == "overlap":
        p["payloads"][1]["offset"] = p["payloads"][0]["offset"]
    if fault == "allocation":
        c["allocated_record_hex"] = "00"
    if fault == "count":
        c["original_native_record_count"] = True
    if fault == "changes":
        c["changes"][1]["after"] = 3.0
    if fault != "seal":
        p["compilation_sha256"] = seal({k: v for k, v in p.items() if k != "compilation_sha256"})
    original = copy.deepcopy(b)
    assert (
        encoded_analog_terminal_reference(b)["native_encoded_analog_terminal"]["state"]
        == "unavailable"
    )
    assert b == original


async def test_analog_record_does_not_promote_an_uncertain_attempt(application):
    intent = native(application, **encoded_analog_body())
    result = await query(application, source="native")
    row = next(r for r in result["rows"] if r["id"] == intent["id"])
    assert (
        row["native_encoded_analog_terminal"]["state"] == "recorded"
        and row["outcome"] == "attention"
        and row["state"] != "verified"
    )
    assert (
        "native_input" not in row
        and "native_terminal" not in row
        and "native_recovery" not in row
        and "native_binary_terminal" not in row
    )
    assert result["field_requests"] == 0


async def test_restarted_recorded_projection_has_no_source_compiler_or_controller_access(
    tmp_path, monkeypatch
):
    receipt = await seed_encoded_analog_records(tmp_path)
    app = create_app(tmp_path)

    def forbidden(*a, **k):
        pytest.fail("Recorded analog metadata opened a field/source/compiler path")

    from bms_tool.native_encoded_terminal_input import EncodedAnalogTerminalCompiler

    monkeypatch.setattr(EncodedAnalogTerminalCompiler, "__init__", forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "load", forbidden)
    for name in ("require", "connect", "_read", "release", "disconnect"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    result = await query(app, source="native")
    row = next(r for r in result["rows"] if r["id"] == receipt["intent"]["id"])
    assert (
        row["native_encoded_analog_terminal"]["state"] == "recorded"
        and row["state"] == "verified"
        and result["field_requests"] == 0
    )
