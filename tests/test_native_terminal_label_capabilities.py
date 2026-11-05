"""Explicit encoded witnesses qualify by compiling this source, never by model inventory."""

import copy
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, sha
from bms_tool.moi_terminal_labels import EncodedEffectiveTerminalCopies, EncodedTerminalCopies
from bms_tool.native_terminal_label_capabilities import PROFILE, ROWS, terminal_label_capabilities
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_moi_connection_copies import frames, packed
from .test_moi_terminal_output_namespace import with_output
from .test_native_connection_copies import filesystem
from .test_native_terminal_capabilities import source
from .test_native_terminal_labels import observed_shape


def analyze(records, request):
    return records.capabilities(request | {"capability_profile": PROFILE})


@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("compressed", [False, True])
def test_exact_old_report_and_actual_original_effective_compilation_witnesses(
    tmp_path, encoding, binary, compressed
):
    storage, records, files, request = source(
        tmp_path, files=observed_shape(encoding=encoding, binary=binary, compressed=compressed)
    )
    before = filesystem(storage.directory)
    previous = records.capabilities(
        request | {"capability_profile": "native-backup-operation-capabilities/15"}
    )
    current = analyze(records, request)
    projected = copy.deepcopy(current)
    projected["capability_profile"] = previous["capability_profile"]
    projected["operations"] = [r for r in projected["operations"] if r["id"] not in ROWS]
    for basis in ("archive", "effective"):
        del projected["qualification"]["encoded_" + basis + "_terminal"]
        del projected["qualification"]["encoded_" + basis + "_terminal_error"]
    assert projected == previous and len(current["operations"]) == 32
    assert records.capabilities(request)["capability_profile"].endswith("/12")
    snapshot, _ = storage.load(request["capture_id"])
    for basis in ("archive", "effective"):
        w = current["qualification"]["encoded_" + basis + "_terminal"]
        c = (
            EncodedTerminalCopies(files[3])
            if basis == "archive"
            else EncodedEffectiveTerminalCopies(snapshot, files).effective
        )
        output, proof = c.compile(
            **{
                k: w[k]
                for k in (
                    "source_sha256",
                    "ref",
                    "record_sha256",
                    "slot_property_sha256",
                    "device_type_property_sha256",
                    "old_slot",
                    "destination_slot",
                )
            }
        )
        assert (
            proof["compilation_sha256"] == w["compilation_sha256"]
            and sha(output) == w["output_sha256"]
        )
        assert (
            proof["device_type_encoding_preserved"] == w["device_type_encoding_preserved"] is True
        )
        assert (
            proof["device_type_character_encoding"]
            == w["device_type_character_encoding"]
            == encoding
        )
        assert w["saved_settings_merged"] is (basis == "effective")
        assert not w["field_transfer_enabled"] and not w["physical_terminal_or_wiring_verified"]
    if encoding == 4:
        assert current["qualification"]["archive_terminal"] is None
        assert current["qualification"]["analog_terminal"] is None
    assert filesystem(storage.directory) == before and not storage.receipts()


@pytest.mark.parametrize(
    "case", ["unknown-saved", "unverified", "serial", "output", "unknown-charset", "sa", "no-free"]
)
def test_local_encoded_support_does_not_promote_identity_transport_host_or_occupancy(
    tmp_path, case
):
    files = observed_shape()
    metadata = {}
    if case == "unknown-saved":
        files[11], files[12] = b"Unknown directory", b"Opaque values"
    if case == "unverified":
        metadata["source_identity_matches"] = False
    if case == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "owned-unopened"}
    if case == "output":
        files = with_output(files)
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
    report = analyze(records, request)
    q = report["qualification"]
    statuses = [r["status"] for r in report["operations"] if r["id"] in ROWS]
    if case in ("unknown-saved", "unverified"):
        assert statuses == ["source-qualified", "unsupported-source"]
    elif case in ("serial", "output"):
        assert statuses == ["source-qualified"] * 2
    else:
        assert statuses == ["unsupported-source"] * 2
    assert report["can_apply"] is False and report["current_identity_verified"] is False
    assert not report["controller_queries"] and not report["field_actions"]
    assert filesystem(storage.directory) == before and not storage.receipts()
    for basis in ("archive", "effective"):
        w = q["encoded_" + basis + "_terminal"]
        assert (w is None) == (q["encoded_" + basis + "_terminal_error"] is not None)


def test_explicit_http_profile_is_source_bound_strict_and_uses_zero_field_paths(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path)
    _, records, _, request = source(tmp_path, files=observed_shape())

    def forbidden(*a, **k):
        pytest.fail("Encoded capability analysis attempted a field/mutation path")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(records.storage.directory)
    route = "/api/bacnet/controller/native-application/inspection/capabilities"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        body = request | {"capability_profile": PROFILE}
        assert client.post(route, json=body).status_code == 403
        response = client.post(route, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == analyze(records, request)
        for change in (
            {"controller_write": True},
            {"capability_profile": "native-backup-operation-capabilities/999"},
            {"snapshot_sha256": "0" * 64},
        ):
            assert client.post(route, json=body | change, headers=headers).status_code == 422
        assert client.get("/api/session").json()["field_network_open"] is False
    assert (
        filesystem(records.storage.directory) == before and not app.state.native_applications.plans
    )
    with pytest.raises(ValueError):
        terminal_label_capabilities({}, {}, {}, capability_profile="unknown")
