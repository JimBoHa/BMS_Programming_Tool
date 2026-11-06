"""Closed binary source witnesses preserve complete predecessor reports and local state."""

import copy
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.mstp import header_crc
from bms_tool.native_binary_terminal import BinaryTerminalCompiler
from bms_tool.native_binary_terminal_capabilities import PROFILE, ROW, binary_terminal_capabilities
from bms_tool.native_inputs import NativeInputCompiler
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed
from .test_moi_terminal_output_namespace import with_output
from .test_native_binary_terminal import replaced
from .test_native_connection_copies import filesystem
from .test_native_signal_compiler import slot as parameter_slot
from .test_native_terminal_capabilities import source
from .test_native_terminal_labels import observed_shape


def analyze(records, request):
    return records.capabilities(request | {"capability_profile": PROFILE})


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
def test_complete_old_report_exact_and_binary_witness_is_actual_compilation(
    tmp_path, encoding, compressed
):
    storage, records, files, request = source(
        tmp_path, files=observed_shape(encoding=encoding, compressed=compressed)
    )
    before = filesystem(storage.directory)
    old = records.capabilities(
        request | {"capability_profile": "native-backup-operation-capabilities/16"}
    )
    result = analyze(records, request)
    projection = copy.deepcopy(result)
    projection["capability_profile"] = old["capability_profile"]
    projection["operations"] = [r for r in projection["operations"] if r["id"] != ROW]
    for k in ("binary_terminal", "binary_terminal_error"):
        del projection["qualification"][k]
    assert projection == old and len(result["operations"]) == 33
    w = result["qualification"]["binary_terminal"]
    assert result["qualification"]["binary_terminal_error"] is None
    c = BinaryTerminalCompiler(NativeInputCompiler(files))
    output, compiled = c.compile(
        {
            "action": "binary-terminal",
            "object_instance": 101,
            "slot": w["destination_slot"],
            "configuration_sha256": w["configuration_sha256"],
        }
    )
    proof = compiled["terminal_compilation"]
    assert (
        w["output_sha256"] == sha(output) and w["compilation_sha256"] == proof["compilation_sha256"]
    )
    assert w["output_native_sha256"] == sha(MoiIdentity(output).data)
    assert w["stored_configuration"] == compiled["stored_configuration"] and w[
        "captured_counter_values"
    ] == {"15": 77, "33": 90000}
    assert (
        w["parameter_merge"] == compiled["parameter_merge"]
        and w["effective_sha256"] == c.app.source_sha256
    )
    assert (
        w["device_type_character_encoding"] == encoding
        and w["device_type_encoding_preserved"] is True
    )
    assert w["destination_slot"] in w["free_slots"] and w["destination_slot"] != w["old_slot"]
    assert (
        w["saved_settings_merged"] is True
        and not w["counter_values_are_live"]
        and not w["field_transfer_enabled"]
        and not w["physical_terminal_or_wiring_verified"]
    )
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
        "analog-only",
        "unknown-configuration",
        "counter-type",
        "unknown-charset",
        "sa",
        "no-free",
    ],
)
def test_witness_uses_actual_schema_identity_transport_and_occupancy(tmp_path, case):
    files = observed_shape()
    metadata = {}
    if case == "unknown-saved":
        files[11], files[12] = b"Unknown saved directory", b"Opaque values"
    if case == "saved-binding":
        payload = (1).to_bytes(4, "big")
        files = {
            3: files[3],
            11: files[11] + parameter_slot((3 << 22) | 101, 242, 519, 2, len(files[12])),
            12: files[12] + payload + bytes([header_crc(payload) ^ 255]),
        }
    if case == "unverified":
        metadata["source_identity_matches"] = False
    if case == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "owned-unopened"}
    if case == "output":
        files = with_output(files)
    if case == "analog-only":
        files = observed_shape(binary=False)
    if case == "unknown-configuration":
        files = replaced(files, {518: encoded(Enumerated(1))})
    if case == "counter-type":
        files = replaced(files, {15: encoded(CharacterString("unqualified"))})
    if case == "unknown-charset":
        files = observed_shape(encoding=0)
        files[3] = files[3].replace(b"\x75\x07\x00UI IN1", b"\x75\x07\x05UI IN1")
    if case in ("sa", "no-free"):
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
            for slot in (2, 3):
                rows.append(
                    (
                        2,
                        native_record(
                            242,
                            100 + slot,
                            [
                                (32527, encoded(CharacterString(f"controller/3_{100 + slot}"))),
                                (75, encoded(ObjectIdentifier((3, 100 + slot)))),
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
    r = analyze(records, request)
    w = r["qualification"]["binary_terminal"]
    row = next(x for x in r["operations"] if x["id"] == ROW)
    if case in ("serial", "output"):
        assert w is not None
        assert row["status"] == (
            "transport-unavailable" if case == "serial" else "preflight-required"
        )
    else:
        assert w is None and r["qualification"]["binary_terminal_error"]
        assert row["status"] == (
            "source-mismatch" if case == "unverified" else "unsupported-source"
        )
    assert not r["can_apply"] and not r["controller_queries"] and not r["field_actions"]
    assert filesystem(storage.directory) == before and not storage.receipts()


def test_explicit_api_profile_stays_disconnected_and_foreign_version_is_refused(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)
    _, records, _, request = source(tmp_path)

    def forbidden(*a, **k):
        pytest.fail("Binary capability analysis attempted a field or mutation path")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(records.storage.directory)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert (
            client.post(
                "/api/bacnet/controller/native-application/inspection/capabilities",
                json=request | {"capability_profile": PROFILE},
            ).status_code
            == 403
        )
        r = client.post(
            "/api/bacnet/controller/native-application/inspection/capabilities",
            json=request | {"capability_profile": PROFILE},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["capability_profile"] == PROFILE
        assert (
            client.post(
                "/api/bacnet/controller/native-application/inspection/capabilities",
                json=request | {"capability_profile": "native-backup-operation-capabilities/20"},
                headers=headers,
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
    assert (
        filesystem(records.storage.directory) == before and not app.state.native_applications.plans
    )
    snapshot, files = records.storage.load(request["capture_id"])
    with pytest.raises(ValueError, match="explicit binary"):
        binary_terminal_capabilities(
            snapshot, files, {}, capability_profile="native-backup-operation-capabilities/16"
        )
