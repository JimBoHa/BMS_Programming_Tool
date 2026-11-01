"""Source qualification never promotes retained bytes into a prepared field write."""

import gzip
import hashlib
import struct
import types

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_signal_compiler import SignalCompilerService
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_moi_parameters import parameters_source
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained, signal_files

BASE = "/api/bacnet/controller/native-application/inspection/capabilities"


def source(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage, files, **metadata)
    request = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    return storage, NativeBackupRecords(storage), request


def operations(report):
    return {row["id"]: row for row in report["operations"]}


@pytest.mark.parametrize(
    "case,expected",
    [
        ("plain", "preflight-required"),
        ("serial", "transport-unavailable"),
        ("missing-interface", "transport-unavailable"),
        ("unknown-saved", "unsupported-source"),
        ("unverified", "source-mismatch"),
        ("wrong-vendor", "source-mismatch"),
        ("no-boolean", "unsupported-source"),
    ],
)
def test_boolean_transfer_qualification_is_independent_of_real_fields(tmp_path, case, expected):
    from .test_native_boolean_copies import boolean_files

    files = boolean_files(real_signals=False)
    metadata = {"connector_config": {"local_address": "127.0.0.1:47818"}}
    if case == "serial":
        metadata["connector_config"] = {"transport": "mstp", "serial_port": "/dev/authored"}
    elif case == "missing-interface":
        metadata["connector_config"] = {}
    elif case == "unknown-saved":
        files[11], files[12] = b"Unknown directory", b"Opaque saved values"
    elif case == "unverified":
        metadata["source_identity_matches"] = False
    elif case == "wrong-vendor":
        metadata["identity"] = {
            "vendor-identifier": 99,
            "object-name": "Authored controller",
            "model-name": "UNLISTED-MODEL",
        }
    elif case == "no-boolean":
        files = dict(zip((3, 11, 12), parameters_source(), strict=True))
    storage, service, request = source(tmp_path, files, **metadata)
    report = service.capabilities(request)
    rows = operations(report)
    assert rows["boolean-default-transfer"]["status"] == expected
    assert report["qualification"]["effective_real_default_count"] == 0
    assert rows["default-transfer"]["status"] != "preflight-required"
    assert report["read_only"] and not report["field_actions"] and not report["can_apply"]
    assert storage.load(request["capture_id"])[1] == files and not storage.receipts()


@pytest.mark.parametrize(
    "config,target,plain",
    [
        ({"local_address": "127.0.0.1:47818"}, {}, True),
        (
            {"local_address": "127.0.0.1:47818"},
            {"address": "10", "router": "127.0.0.1:47819", "dnet": 200},
            True,
        ),
        ({"transport": "mstp", "serial_port": "/dev/authored-only"}, {}, False),
        ({"bbmd_address": "127.0.0.1:47999"}, {}, False),
        ({}, {}, False),
    ],
)
def test_actual_saved_merge_and_compiler_are_distinct_from_captured_transport(
    tmp_path, config, target, plain
):
    metadata = {"connector_config": config}
    if target:
        metadata["target"] = target
    storage, service, request = source(tmp_path, **metadata)
    folder = storage.directory / request["capture_id"]
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    report = service.capabilities(request)
    rows, qualification = operations(report), report["qualification"]
    assert report["capability_profile"] == "native-backup-operation-capabilities/7"
    assert len(rows) == len(report["operations"]) == 18
    assert report["read_only"] and not report["can_apply"] and not report["field_actions"]
    assert not report["controller_queries"] and not report["current_identity_verified"]
    assert qualification["recorded_identity_verified"]
    assert qualification["captured_plain_ipv4"] is plain
    assert (
        qualification["archive_real_default_count"]
        == qualification["effective_real_default_count"]
        == 2
    )
    assert qualification["parameter_merge"]["changed_parameters"]
    for key in (
        "archive-read",
        "saved-settings",
        "effective-default-compile",
        "identity-compile",
        "name-compile",
        "signal-default-copy",
    ):
        assert rows[key]["status"] == "source-qualified"
    for key in ("identity-transfer", "default-transfer"):
        assert rows[key]["status"] == ("preflight-required" if plain else "transport-unavailable")
    assert rows["general-logic"]["status"] == "unavailable"
    assert rows["release-packages"]["status"] == "not-evaluated"
    assert rows["physical-acceptance"]["status"] == "not-inferred"
    assert len(SignalCompilerService(storage).source(request["capture_id"])["fields"]) == 2
    assert before == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
    assert not storage.receipts()


@pytest.mark.parametrize("fault", ["unknown-saved", "bad-crc", "saved-name", "no-real-defaults"])
def test_readability_and_narrow_compiler_qualification_do_not_share_a_success_flag(tmp_path, fault):
    from .test_native_signal_compiler import inline

    files = signal_files()
    if fault == "unknown-saved":
        files[11], files[12] = b"Unknown directory", b"Opaque settings"
    elif fault == "bad-crc":
        files[12] = bytes([files[12][0] ^ 1]) + files[12][1:]
    elif fault == "saved-name":
        files[11] += inline((8 << 22) | 5136, 470, 2390, "Another name")
    else:
        files = dict(zip((3, 11, 12), parameters_source(), strict=True))
    storage, service, request = source(tmp_path, files)
    report = service.capabilities(request)
    rows, qualification = operations(report), report["qualification"]
    assert rows["archive-read"]["status"] == "source-qualified"
    assert rows["effective-default-compile"]["status"] == "unsupported-source"
    assert rows["default-transfer"]["status"] == "unsupported-source"
    if fault in ("unknown-saved", "bad-crc"):
        assert rows["saved-settings"]["status"] == "unsupported-source"
        assert qualification["parameter_merge_error"]
    else:
        assert rows["saved-settings"]["status"] == "source-qualified"
    if fault == "no-real-defaults":
        assert qualification["archive_real_default_count"] == 0
        assert qualification["effective_real_default_count"] == 0
        assert rows["signal-default-copy"]["status"] == "unsupported-source"
    else:
        assert qualification["effective_compiler_error"]
    assert service.records(request)["records"] and not storage.receipts()


@pytest.mark.parametrize("fault", ["unverified", "device", "name", "model", "vendor"])
def test_historical_identity_is_recomputed_and_never_verifies_current_connection(tmp_path, fault):
    metadata = {}
    if fault == "unverified":
        metadata = {"source_identity_matches": False, "source_identity_error": "Authored mismatch"}
    elif fault == "device":
        metadata = {"device": "device,5137"}
    else:
        metadata = {
            "identity": {
                "object-name": "Wrong" if fault == "name" else "Authored controller",
                "model-name": "Wrong" if fault == "model" else "UNLISTED-MODEL",
                "vendor-identifier": 99 if fault == "vendor" else 5,
            }
        }
    storage, service, request = source(tmp_path, **metadata)
    report = service.capabilities(request)
    rows = operations(report)
    assert not report["qualification"]["recorded_identity_verified"]
    assert not report["current_identity_verified"]
    assert rows["archive-read"]["status"] == rows["saved-settings"]["status"] == "source-qualified"
    assert rows["effective-default-compile"]["status"] == "unsupported-source"
    assert (
        rows["default-transfer"]["status"]
        == rows["identity-transfer"]["status"]
        == "source-mismatch"
    )
    with pytest.raises(ValueError):
        SignalCompilerService(storage).source(request["capture_id"])


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_any_substituted_file_blocks_analysis(tmp_path, file_id):
    storage, service, request = source(tmp_path)
    (storage.directory / request["capture_id"] / f"file-{file_id}.bin").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="integrity"):
        service.capabilities(request)


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"connector_config": {"transport": "mstp", "serial_port": "/dev/authored-only"}},
        {"source_identity_matches": False},
    ],
)
def test_archive_wire_copy_qualification_is_independent_of_saved_schema_and_current_transport(
    tmp_path, metadata
):
    from .test_moi_wire_sources import source as graph_source

    files = {3: graph_source(), 11: b"Unknown selectors", 12: b"Opaque saved values"}
    storage, service, request = source(tmp_path, files, **metadata)
    report = service.capabilities(request)
    rows = operations(report)
    assert rows["wire-source-copy"]["status"] == "source-qualified"
    assert report["qualification"]["archive_wire_source_copy"]["candidate_count"] == 1
    assert rows["general-logic"]["status"] == "unavailable"
    assert rows["saved-settings"]["status"] == "unsupported-source"
    assert (
        not report["can_apply"] and not report["field_actions"] and not report["controller_queries"]
    )
    assert storage.load(request["capture_id"])[1] == files and not storage.receipts()


def test_readable_native_graph_without_a_compatible_wire_source_has_no_copy_qualification(tmp_path):
    from .test_moi_wire_sources import source as graph_source

    files = {3: graph_source(config=True), 11: b"Unknown selectors", 12: b"Opaque saved values"}
    _, service, request = source(tmp_path, files)
    rows = operations(service.capabilities(request))
    assert rows["diagram-read"]["status"] == "source-qualified"
    assert rows["wire-source-copy"]["status"] == "unsupported-source"


def test_source_seal_and_local_http_contract_are_strict(tmp_path):
    app = create_app(tmp_path)
    snapshot = retained(app.state.native_applications.storage)
    body = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=body).status_code == 403
        report = client.post(BASE, json=body, headers=headers)
        assert report.status_code == 200, report.text
        assert not report.json()["can_apply"]
        assert (
            client.post(BASE, json=body | {"address": "127.0.0.1:1"}, headers=headers).status_code
            == 422
        )
        assert (
            client.post(
                BASE, json=body | {"snapshot_sha256": "0" * 64}, headers=headers
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]


def test_missing_root_name_does_not_qualify_name_compilation(tmp_path):
    files = signal_files()
    expanded = gzip.decompress(files[3])
    # Replace only the property identifier, retaining every frame/typed value.
    files[3] = gzip.compress(expanded.replace(b"\x0a\x09\x56\x2e", b"\x0a\xfd\xe8\x2e", 1), mtime=0)
    _, service, request = source(tmp_path, files)
    report = service.capabilities(request)
    rows = operations(report)
    assert report["qualification"]["native_identity"]["name"] is None
    assert rows["identity-compile"]["status"] == "source-qualified"
    assert rows["name-compile"]["status"] == "unsupported-source"


def test_readable_diagram_without_qualified_root_has_no_typed_compiler(tmp_path):
    from .test_controller_application import authored_application

    files = signal_files()
    files[3] = authored_application()
    _, service, request = source(tmp_path, files)
    rows = operations(service.capabilities(request))
    assert rows["archive-read"]["status"] == rows["diagram-read"]["status"] == "source-qualified"
    assert (
        rows["identity-compile"]["status"] == rows["name-compile"]["status"] == "unsupported-source"
    )
    assert rows["effective-default-compile"]["status"] == "unsupported-source"


def test_an_object_identifier_string_is_not_a_typed_controller_name(tmp_path):
    from bacpypes3.primitivedata import CharacterString, ObjectIdentifier

    from .test_controller_application import encoded, native_record

    record = native_record(
        470,
        5136,
        [
            (32527, encoded(CharacterString("controller"))),
            (75, encoded(ObjectIdentifier((8, 5136)))),
            (2390, encoded(ObjectIdentifier((2, 10)))),
        ],
    )
    files = signal_files()
    files[3] = (
        struct.pack("<6sHHI", b"\x02\x00MOI\x00", 470, 1, 1)
        + struct.pack("<H", len(record) + 2)
        + record
    )
    _, service, request = source(tmp_path, files)
    report = service.capabilities(request)
    assert report["qualification"]["native_identity"]["name"] == "analog-value,10"
    assert operations(report)["name-compile"]["status"] == "unsupported-source"


async def test_actual_native_capture_then_disconnected_capabilities_do_not_query_peer(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = signal_files()
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    capture = await native.capture(**target, operation_id="capture-for-local-capabilities")
    snapshot, _ = native.storage.load(capture["id"])
    await bacnet.disconnect()
    before = list(seen)
    report = NativeBackupRecords(native.storage).capabilities(
        {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    )
    assert operations(report)["default-transfer"]["status"] == "preflight-required"
    assert "ReinitializeDeviceRequest" in before and "AtomicReadFileRequest" in before
    assert seen == before and not native.storage.receipts()
