"""Independent native analog-terminal profile and exact legacy-operation contracts."""

import pytest
from bacpypes3.primitivedata import CharacterString, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inputs import (
    InputEdit,
    NativeInputCompiler,
    input_operation_profile,
    verify_input_preservation,
)

from .test_controller_application import encoded
from .test_moi_terminal_copies import authored, literal_move, selected_edit
from .test_native_inputs import config, source
from .test_native_terminal_copies import literal_effective


def terminal_edit(compiler, slot=3):
    point = next(p for p in compiler.source()["inputs"] if p["object_id"] == "analog-input,101")
    return {
        "action": "terminal",
        "object_instance": 101,
        "slot": slot,
        "configuration_sha256": point["configuration_sha256"],
    }


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("slot_width", [1, 2, 3, 4])
def test_independent_saved_values_and_literal_binding_bytes_qualify_complete_readback(
    compressed, wide, slot_width
):
    files = authored(compressed=compressed, wide=wide, slot_width=slot_width)
    compiler = NativeInputCompiler(files)
    edit = terminal_edit(compiler)
    output, report = compiler.compile(edit)
    actual = MoiIdentity(output)
    assert actual.data == literal_move(
        literal_effective(MoiIdentity(files[3]).data), slot_width=slot_width
    )
    assert (
        report["profile"]
        == input_operation_profile(edit)
        == "native-local-universal-input-transfer/2"
    )
    assert report["stored_configuration"] == compiler.source()["inputs"][0]["configuration"]
    assert report["native_record_count"] == report["original_native_record_count"]
    assert (
        report["other_records_preserved"]
        and not report["wires_changed"]
        and report["allocated_record_hex"] is None
    )
    assert report["changes"] == [
        {"property": 31, "before": "UI IN1", "after": "UI IN3"},
        {"property": 519, "before": 1, "after": 3},
    ]
    assert report["terminal_compilation"]["other_expanded_bytes_preserved"]
    preservation = verify_input_preservation(files, {**files, 3: output}, edit)
    assert preservation["other_configuration_preserved"]
    assert preservation["saved_application_parameters_verified"] == 7
    with pytest.raises(ValueError):
        verify_input_preservation(files, files, edit)


@pytest.mark.parametrize(
    "field,value",
    [
        ("slot", 1),
        ("slot", 4),
        ("slot", True),
        ("slot", 3.0),
        ("object_instance", 1094),
        ("object_instance", 999),
        ("configuration_sha256", "0" * 64),
        ("configuration", config()),
        ("name", "Changed"),
        ("allocation_receipt", "a" * 32),
    ],
)
def test_noop_fixed_input_stale_guard_or_extra_edit_authority_refuses(field, value):
    compiler = NativeInputCompiler(source(existing=True))
    with pytest.raises(ValueError):
        compiler.compile(terminal_edit(compiler) | {field: value})


@pytest.mark.parametrize(
    "pid,value",
    [
        (2577, encoded(Unsigned(0))),
        (3645, encoded(Unsigned(0))),
        (32527, encoded(CharacterString("controller/module/0_101"))),
    ],
)
def test_explicit_host_or_parent_bindings_cannot_enter_the_transfer_profile(pid, value):
    files = authored()
    files[3] = selected_edit(files[3], pid, value)
    with pytest.raises(ValueError):
        compiler = NativeInputCompiler(files)
        compiler.compile(terminal_edit(compiler))


def test_binary_input_does_not_gain_analog_field_authority():
    compiler = NativeInputCompiler(source(binary=True))
    with pytest.raises(ValueError):
        compiler.compile(
            {
                "action": "terminal",
                "object_instance": 101,
                "slot": 3,
                "configuration_sha256": "0" * 64,
            }
        )


@pytest.mark.parametrize("action", ["allocate", "mode", "remove-allocated"])
def test_legacy_action_serialized_shape_and_profile_remain_version_one(action):
    edit = {"action": action, "object_instance": 101, "slot": 1}
    if action == "allocate":
        edit.update(name="Authored new input", configuration=config())
    else:
        edit["configuration_sha256"] = "a" * 64
        if action == "mode":
            edit["configuration"] = config()
        else:
            edit["allocation_receipt"] = "b" * 32
    parsed = InputEdit.model_validate(edit)
    assert set(parsed.model_dump()) == {
        "action",
        "object_instance",
        "slot",
        "configuration_sha256",
        "name",
        "configuration",
        "allocation_receipt",
    }
    assert (
        input_operation_profile(parsed)
        == input_operation_profile(edit)
        == "native-local-universal-input-transfer/1"
    )
