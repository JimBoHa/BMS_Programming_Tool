"""Typed analog capability witnesses use actual source bytes and preserve predecessor evidence."""

import copy
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_encoded_analog_capabilities import PROFILE, ROW, encoded_analog_capabilities
from bms_tool.native_encoded_terminal_input import EncodedAnalogTerminalCompiler
from bms_tool.native_inputs import NativeInputCompiler
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed
from .test_moi_terminal_output_namespace import with_output
from .test_native_connection_copies import filesystem
from .test_native_encoded_terminal_input import nonlinear, replaced
from .test_native_signal_compiler import slot as parameter_slot
from .test_native_terminal_capabilities import source
from .test_native_terminal_labels import observed_shape


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("absent", [False, True])
def test_actual_typed_witness_preserves_complete_predecessor_and_has_no_authority(
    tmp_path, encoding, compressed, absent
):
    files = observed_shape(binary=False, encoding=encoding, compressed=compressed)
    if absent:
        files = nonlinear(files)
    storage, records, files, request = source(tmp_path, files=files)
    before = filesystem(storage.directory)
    old = records.capabilities(
        request | {"capability_profile": "native-backup-operation-capabilities/17"}
    )
    result = records.capabilities(request | {"capability_profile": PROFILE})
    projection = copy.deepcopy(result)
    projection["capability_profile"] = old["capability_profile"]
    projection["operations"] = [r for r in projection["operations"] if r["id"] != ROW]
    for key in ("encoded_analog_terminal", "encoded_analog_terminal_error"):
        del projection["qualification"][key]
    assert projection == old and len(result["operations"]) == 34
    witness = result["qualification"]["encoded_analog_terminal"]
    assert result["qualification"]["encoded_analog_terminal_error"] is None
    compiler = EncodedAnalogTerminalCompiler(NativeInputCompiler(files))
    output, compiled = compiler.compile(
        {
            "action": "encoded-terminal",
            "object_instance": 101,
            "slot": witness["destination_slot"],
            "configuration_sha256": witness["configuration_sha256"],
        }
    )
    proof = compiled["terminal_compilation"]
    assert witness["output_sha256"] == sha(output)
    assert witness["output_native_sha256"] == sha(MoiIdentity(output).data)
    assert witness["compilation_sha256"] == proof["compilation_sha256"]
    assert witness["stored_configuration"] == compiled["stored_configuration"]
    assert witness["configuration_storage"] == compiled["configuration_storage"]
    assert witness["configuration_storage"]["linear_output_endpoints_present"] is not absent
    if absent:
        assert witness["stored_configuration"]["output_low"] is None
        assert witness["stored_configuration"]["output_high"] is None
    assert witness["parameter_merge"] == compiled["parameter_merge"]
    assert witness["effective_sha256"] == compiler.app.source_sha256
    assert witness["device_type_character_encoding"] == encoding
    assert witness["device_type_encoding_preserved"] is True
    assert witness["saved_settings_merged"] is True
    assert (
        not witness["field_transfer_enabled"]
        and not witness["physical_terminal_or_wiring_verified"]
    )
    assert witness["destination_slot"] in witness["free_slots"]
    assert witness["old_slot"] not in witness["free_slots"]
    assert next(r for r in result["operations"] if r["id"] == ROW)["status"] == "preflight-required"
    assert records.capabilities(request)["capability_profile"].endswith("/12")
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize(
    "case",
    [
        "unknown-saved",
        "saved-binding",
        "unverified",
        "serial",
        "output",
        "binary-only",
        "type",
        "endpoints",
        "nonfinite",
        "charset",
        "sa",
        "no-free",
    ],
)
def test_actual_configuration_occupancy_identity_and_transport_determine_support(tmp_path, case):
    files = nonlinear(observed_shape(binary=False))
    metadata = {}
    if case == "unknown-saved":
        files[11], files[12] = b"Unknown saved directory", b"Opaque values"
    elif case == "saved-binding":
        payload = (1).to_bytes(4, "big")
        files = {
            3: files[3],
            11: files[11] + parameter_slot(101, 240, 519, 2, len(files[12])),
            12: files[12] + payload + bytes([header_crc(payload) ^ 255]),
        }
    elif case == "unverified":
        metadata["source_identity_matches"] = False
    elif case == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "owned-unopened"}
    elif case == "output":
        files = with_output(files)
    elif case == "binary-only":
        files = observed_shape()
    elif case == "type":
        files = replaced(files, {518: encoded(Unsigned(1))})
    elif case == "endpoints":
        files = replaced(files, {1295: encoded(Real(0))})
    elif case == "nonfinite":
        files = replaced(files, {1293: encoded(Real(float("nan")))})
    elif case == "charset":
        files = nonlinear(observed_shape(binary=False, encoding=0))
        files[3] = files[3].replace(b"\x75\x07\x00UI IN1", b"\x75\x07\x05UI IN1")
    elif case in ("sa", "no-free"):
        raw = MoiIdentity(files[3]).data
        rows = frames(raw)
        if case == "sa":
            rows.append(
                (
                    2,
                    native_record(
                        598, 500, [(32527, encoded(CharacterString("controller/module")))]
                    ),
                )
            )
        else:
            # Two extra local inputs occupy the remaining universal terminals.
            for slot in (2, 3):
                rows.append(
                    (
                        2,
                        native_record(
                            240,
                            100 + slot,
                            [
                                (32527, encoded(CharacterString(f"controller/0_{100 + slot}"))),
                                (75, encoded(ObjectIdentifier((0, 100 + slot)))),
                                (31, encoded(CharacterString(f"UI IN{slot}"))),
                                (519, encoded(Unsigned(slot))),
                            ],
                        ),
                    )
                )
        header = bytearray(raw[:14])
        struct.pack_into("<I", header, 10, len(rows))
        files[3] = packed(bytes(header), rows)
    storage, records, _, request = source(tmp_path, files=files, **metadata)
    before = filesystem(storage.directory)
    result = records.capabilities(request | {"capability_profile": PROFILE})
    witness = result["qualification"]["encoded_analog_terminal"]
    row = next(r for r in result["operations"] if r["id"] == ROW)
    if case in ("serial", "output"):
        assert witness is not None
        assert row["status"] == (
            "transport-unavailable" if case == "serial" else "preflight-required"
        )
    else:
        assert witness is None and result["qualification"]["encoded_analog_terminal_error"]
        assert row["status"] == (
            "source-mismatch" if case == "unverified" else "unsupported-source"
        )
    assert (
        not result["can_apply"] and not result["controller_queries"] and not result["field_actions"]
    )
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_explicit_api_profile_remains_disconnected_and_refuses_foreign_version(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)
    _, records, _, request = source(tmp_path, files=nonlinear(observed_shape(binary=False)))

    def forbidden(*a, **k):
        pytest.fail("Typed analog capability analysis attempted a field or mutation path")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(records.storage.directory)
    with TestClient(app) as client:
        path = "/api/bacnet/controller/native-application/inspection/capabilities"
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(path, json=request | {"capability_profile": PROFILE}).status_code == 403
        response = client.post(
            path, json=request | {"capability_profile": PROFILE}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["capability_profile"] == PROFILE
        assert (
            client.post(
                path,
                json=request | {"capability_profile": "native-backup-operation-capabilities/21"},
                headers=headers,
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    assert (
        filesystem(records.storage.directory) == before and not app.state.native_applications.plans
    )
    snapshot, files = records.storage.load(request["capture_id"])
    with pytest.raises(ValueError, match="explicit typed analog"):
        encoded_analog_capabilities(
            snapshot, files, {}, capability_profile="native-backup-operation-capabilities/17"
        )
