"""Observed binary schema, configuration guards, literal copies and local API boundaries."""

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_binary_terminal import PROFILE, BinaryTerminalCompiler
from bms_tool.native_inputs import (
    InputEdit,
    NativeInputCompiler,
    archive,
    replace_properties,
    verify_input_preservation,
)
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import slot
from .test_native_terminal_copies import setup
from .test_native_terminal_labels import literal, literal_effective, observed_shape


def compiler(files=None):
    return BinaryTerminalCompiler(NativeInputCompiler(files or observed_shape()))


def edit(c, **changes):
    row = c.source()["inputs"][0]
    return {
        "action": "binary-terminal",
        "object_instance": 101,
        "slot": 3,
        "configuration_sha256": row["configuration_sha256"],
        **changes,
    }


def replaced(files, changes):
    app = MoiIdentity(files[3])
    selected = next(r for r in app.records if app.reader.scalar(r, 32527) == "controller/3_101")
    rows = [
        replace_properties(app, r, changes)
        if r is selected
        else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    output = archive(app, rows)
    assert MoiIdentity(output).data != app.data
    return {**files, 3: output}


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
def test_binary_move_uses_observed_configuration_and_literal_whole_saved_image(
    encoding, compressed
):
    files = observed_shape(encoding=encoding, compressed=compressed)
    c = compiler(files)
    request = edit(c)
    output, report = NativeInputCompiler(files).compile(request)
    assert report["profile"] == PROFILE and report["object_id"] == "binary-input,101"
    assert report["stored_configuration"] == {
        "active_text": "Closed",
        "inactive_text": "Open",
        "states_text_index": 14,
        "polarity": 1,
    }
    assert report["captured_counter_values"] == {"15": 77, "33": 90000}
    assert MoiIdentity(output).data == literal(
        literal_effective(MoiIdentity(files[3]).data), encoding=encoding
    )
    assert report["terminal_compilation"]["device_type_character_encoding"] == encoding
    assert not report["wires_changed"] and report["allocated_record_hex"] is None
    assert c.source()["counter_values_are_live"] is False
    after = {**files, 3: output}
    assert verify_input_preservation(files, after, request)["other_configuration_preserved"]
    row = compiler(after).source()["inputs"][0]
    assert row["slot"] == 3


@pytest.mark.parametrize("property,value", [(15, Unsigned(256)), (33, Unsigned(999999))])
def test_runtime_counter_changes_preserve_configuration_guard_and_current_values(property, value):
    files = observed_shape()
    before = compiler(files)
    fresh = replaced(files, {property: encoded(value)})
    current = compiler(fresh)
    request = edit(before)
    assert edit(current)["configuration_sha256"] == request["configuration_sha256"]
    output, proof = current.compile(request)
    assert proof["captured_counter_values"][str(property)] == int(value)
    assert MoiIdentity(output).reader.scalar(
        MoiIdentity(output).reader.records["controller/3_101"], property
    ) == int(value)


@pytest.mark.parametrize(
    "property,value",
    [
        (4, CharacterString("On")),
        (46, CharacterString("Off")),
        (931, Enumerated(15)),
        (84, Enumerated(0)),
        (2390, CharacterString("Changed name")),
    ],
    ids=["active", "inactive", "states", "polarity", "name"],
)
def test_fresh_binary_configuration_changes_retire_the_review_guard(property, value):
    files = observed_shape()
    request = edit(compiler(files))
    current = compiler(replaced(files, {property: encoded(value)}))
    with pytest.raises(ValueError, match="configuration or terminal changed"):
        current.compile(request)


@pytest.mark.parametrize(
    "property,value",
    [
        (518, Enumerated(1)),
        (65000, Unsigned(1)),
        (84, Real(1)),
        (84, Enumerated(3)),
        (15, Real(2)),
        (931, CharacterString("Unqualified")),
    ],
    ids=[
        "analog-field",
        "unknown",
        "polarity-type",
        "polarity-value",
        "counter-type",
        "states-type",
    ],
)
def test_unqualified_binary_configuration_has_no_guard_or_compile_authority(property, value):
    c = compiler(replaced(observed_shape(), {property: encoded(value)}))
    row = c.source()["inputs"][0]
    assert row["configuration_error"] and "configuration_sha256" not in row
    with pytest.raises(ValueError):
        c.compile(
            {
                "action": "binary-terminal",
                "object_instance": 101,
                "slot": 3,
                "configuration_sha256": "0" * 64,
            }
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"slot": True},
        {"slot": 3.0},
        {"name": "Wrong"},
        {"configuration": {}},
        {"allocation_receipt": "a" * 32},
        {"configuration_sha256": None},
    ],
)
def test_binary_action_requires_only_strict_existing_guard_and_destination(changes):
    with pytest.raises(ValueError):
        InputEdit.model_validate(edit(compiler(), **changes))


def test_binary_source_and_sealed_local_copy_do_not_query_controller_or_create_intents(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)
    _, old, files, query = setup(tmp_path, files=observed_shape())
    service = app.state.native_applications
    request = {k: query[k] for k in ("capture_id", "snapshot_sha256")}

    def forbidden(*a, **k):
        pytest.fail("Local binary source/copy entered a field path")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(service.storage, "intent", forbidden)
    before = filesystem(service.storage.directory)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        route = "/api/bacnet/controller/native-application/input/binary-terminal/source"
        assert client.post(route, json=request).status_code == 403
        response = client.post(route, json=request, headers=headers)
        assert response.status_code == 200, response.text
        source = response.json()
        assert source["profile"] == PROFILE and not source["field_transfer_enabled"]
        body = {**request, "edit": edit(compiler(files))}
        response = client.post(
            "/api/bacnet/controller/native-application/input/copy/preview",
            json=body,
            headers=headers,
        )
        assert response.status_code == 200, response.text
        review = response.json()
        assert review["profile"] == PROFILE
        output = client.post(
            "/api/bacnet/controller/native-application/input/copy/export",
            json=body | {"expected_review_sha256": review["review_sha256"]},
            headers=headers,
        )
        assert output.status_code == 200 and sha(output.content) == review["output_sha256"]
        assert client.get("/api/session").json()["field_network_open"] is False
    assert (
        filesystem(service.storage.directory) == before
        and not service.storage.receipts()
        and not service.plans
    )


def test_missing_states_text_stays_readable_without_a_binary_configuration_guard():
    files = observed_shape()
    app = MoiIdentity(files[3])
    selected = next(r for r in app.records if r["class_id"] == 242)
    raw = native_record(
        242,
        101,
        [
            (pid, app.data[p["value_start_offset"] : p["value_end_offset"] - 1])
            for pid, p in selected["properties"].items()
            if pid != 931
        ],
    )
    records = [
        raw if r is selected else app.data[r["offset"] : r["end_offset"]] for r in app.records
    ]
    c = compiler({**files, 3: archive(app, records)})
    assert c.source()["inputs"][0]["configuration_error"]
    with pytest.raises(ValueError, match="closed observed configuration"):
        c.compile(
            {
                "action": "binary-terminal",
                "object_instance": 101,
                "slot": 3,
                "configuration_sha256": "0" * 64,
            }
        )


def test_saved_readback_counter_cannot_change_from_unsigned_to_real():
    files = observed_shape()
    c = compiler(files)
    request = edit(c)
    output, _ = c.compile(request)
    payload = b"\x3f\x80\x00\x00"
    dynamic = files[12] + payload + bytes([header_crc(payload) ^ 255])
    after = {
        3: output,
        11: files[11] + slot((3 << 22) | 101, 242, 15, 4, len(files[12])),
        12: dynamic,
    }
    with pytest.raises(ValueError):
        verify_input_preservation(files, after, request)


@pytest.mark.parametrize("fault", ["vendor", "name"])
def test_binary_source_requires_the_exact_captured_vendor_and_root_identity(tmp_path, fault):
    metadata = {
        "identity": {
            "object-name": "Changed" if fault == "name" else "Authored controller",
            "model-name": "M4-CVM03050-0",
            "vendor-identifier": 99 if fault == "vendor" else 5,
        }
    }
    _, _, _, query = setup(tmp_path, files=observed_shape(), **metadata)
    service = create_app(tmp_path).state.native_applications
    with pytest.raises(ValueError, match="captured controller identity disagree"):
        service.binary_input_source(**{k: query[k] for k in ("capture_id", "snapshot_sha256")})
