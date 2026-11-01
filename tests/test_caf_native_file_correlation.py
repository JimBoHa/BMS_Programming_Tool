"""Published File captures stay separate from native backup/settings evidence."""

import hashlib
import json
import secrets
import zipfile

import pytest
from bms_tool.app import create_app
from bms_tool.bacnet_files import BacnetFiles
from bms_tool.caf_native_file_correlation import NativeFileCorrelation, file_source
from bms_tool.moi_identity import seal
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_bacnet_files import link as link  # noqa: F401
from .test_caf_native_correlation import caf_source
from .test_native_signal_compiler import signal_files


def retained_file(
    files, data=None, *, format_hint=".moi", target=None, config=None, identity=None, reuse=False
):
    data = signal_files()[3] if data is None else data
    target = {"address": "127.0.0.1:47918", "device": "device,5136", "object_id": "file,31"} | (
        target or {}
    )
    config = {"local_address": "127.0.0.1:47818", "router": None, "dnet": None} | (config or {})
    identity = {
        "object-identifier": "device,5136",
        "object-name": "Authored controller",
        "vendor-identifier": 5,
        "model-name": "UNLISTED-MODEL",
        "firmware-revision": "authored-1",
        "max-apdu-length-accepted": 128,
    } | (identity or {})
    metadata = {
        "object_id": target["object_id"],
        "object_identifier": target["object_id"],
        "object_name": "Authored retained native file",
        "description": "Authored software fixture",
        "file_size": len(data),
        "file_access_method": "stream-access",
        "file_type": format_hint,
        "read_only": True,
        "read_supported": True,
        "read_reason": "Authored",
        "record_count": None,
        "modification_date": "2026-01-05 12:00:00",
    }
    metadata["metadata_sha256"] = seal(metadata)
    if reuse:
        for row in files.captures():
            prior, _ = files.capture_data(row["id"])
            if (
                prior["sha256"] == hashlib.sha256(data).hexdigest()
                and prior["target"] == target
                and prior["connector_config"] == config
                and prior["device_identity"] == identity
                and prior["metadata"] == metadata
            ):
                return prior
    report = {
        "profile": "bacnet-opaque-file/1",
        "id": secrets.token_hex(16),
        "scope": "Authored retained File fixture; no physical capture is claimed.",
        "source_kind": "device-file",
        "target": target,
        "connector_config": config,
        "device_identity": identity,
        "metadata": metadata,
        "complete": True,
        "native_caf": False,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "access_method": "stream-access",
        "record_boundaries": [],
        "read_at": "2026-01-05T12:00:00+00:00",
        "received_at": "2026-01-05T12:00:01+00:00",
        "consistency": "Metadata stable before/after; no backup session started, not an atomic snapshot.",
        "configuration_files": [target["object_id"]],
        "advertised_files": [target["object_id"]],
        "discovery_source": "configuration-files",
        "object_list_count": None,
        "object_list_sha256": None,
        "pages": [{"start": 0, "count": len(data), "eof": True}],
    }
    files._save(report, data)
    return report


def setup(tmp_path, **kwargs):
    files = BacnetFiles(None, Store(tmp_path))
    receipt = retained_file(files, **kwargs)
    source = file_source(receipt)
    caf = caf_source()
    body = {
        "source_sha256": caf.hash,
        "capture_id": receipt["id"],
        "receipt_sha256": source["receipt_sha256"],
        "file_sha256": source["sha256"],
    }
    return files, NativeFileCorrelation(files), caf, receipt, body


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("hint", [".moi", ".MoZ", ".bin"])
def test_actual_bytes_decide_readability_and_file_evidence_is_never_a_saved_settings_backup(
    tmp_path, compressed, hint
):
    data = signal_files(compressed=compressed)[3]
    files, service, caf, receipt, body = setup(tmp_path, data=data, format_hint=hint)
    report = service.compare(caf, body)
    assert report["profile"] == "caf-native-file-source-correlation/1"
    assert report["classification"] == "recorded-identities-equal"
    assert report["recorded_device_identity_agrees"]
    assert "native_backup" not in report and "recorded_acquisition_identity_verified" not in report
    source = report["native_file"]
    assert source["sha256"] == receipt["sha256"] == hashlib.sha256(data).hexdigest()
    assert source["receipt_sha256"] == seal(receipt)
    assert not source["full_native_backup"] and not source["saved_settings_available"]
    assert report["coverage"]["record_status_counts"] == {"same-record-identity": 8}
    assert report["read_only"] and not any(
        report[k]
        for k in (
            "controller_queries",
            "field_actions",
            "can_apply",
            "application_association_granted",
            "full_program_match_verified",
            "compiler_compatibility_verified",
        )
    )
    digest = report.pop("report_sha256")
    assert digest == seal(report)
    assert files.capture_data(receipt["id"]) == (receipt, data)


@pytest.mark.parametrize(
    "config,target",
    [
        ({"router": "127.0.0.1:47919", "dnet": 3001}, {"address": "3001:7"}),
        ({"transport": "mstp", "serial_port": "/dev/authored-only"}, {"address": "7"}),
        ({}, {"address": "legacy-recorded-address"}),
    ],
)
def test_offline_format_comparison_keeps_recorded_route_without_current_transport_gate(
    tmp_path, config, target
):
    _, service, caf, _, body = setup(tmp_path, config=config, target=target)
    report = service.compare(caf, body)
    source = report["native_file"]
    assert source["target"]["address"] == target["address"]
    assert source["target"]["router"] == config.get("router")
    assert source["target"]["dnet"] == config.get("dnet")
    assert report["classification"] == "recorded-identities-equal"


@pytest.mark.parametrize("fault", ["target-device", "device-property", "vendor", "name", "model"])
def test_recorded_file_device_disagreement_is_not_a_verified_backup_acquisition(tmp_path, fault):
    kwargs = {}
    if fault == "target-device":
        kwargs["target"] = {"device": "device,5137"}
    else:
        key = {
            "device-property": "object-identifier",
            "vendor": "vendor-identifier",
            "name": "object-name",
            "model": "model-name",
        }[fault]
        kwargs["identity"] = {
            key: 99
            if fault == "vendor"
            else "device,5137"
            if fault == "device-property"
            else "Another"
        }
    _, service, caf, _, body = setup(tmp_path, **kwargs)
    report = service.compare(caf, body)
    assert not report["recorded_device_identity_agrees"]
    assert report["classification"] == "identity-incomplete"
    assert report["native_file"]["identity_verified"] is False


@pytest.mark.parametrize("field", ["source_sha256", "receipt_sha256", "file_sha256"])
def test_each_selected_source_digest_is_required_before_comparison(tmp_path, field):
    _, service, caf, _, body = setup(tmp_path)
    with pytest.raises(ValueError):
        service.compare(caf, body | {field: "0" * 64})


@pytest.mark.parametrize("data", [b"Opaque .moz bytes", b"Not an archive"])
def test_extension_hints_cannot_supply_an_application_or_root_identity(tmp_path, data):
    _, service, caf, _, body = setup(tmp_path, data=data, format_hint=".moz")
    assert service.sources()["sources"]
    with pytest.raises(ValueError):
        service.compare(caf, body)


@pytest.mark.parametrize("fault", ["payload", "receipt", "metadata", "symlink"])
def test_existing_capture_integrity_loader_admits_every_compare_request(tmp_path, fault):
    files, service, caf, receipt, body = setup(tmp_path)
    path = files.directory / (receipt["id"] + ".capture")
    with zipfile.ZipFile(path) as archive:
        raw_receipt = archive.read("receipt.json")
        data = archive.read("data.bin")
        comment = archive.comment
    if fault == "symlink":
        actual = tmp_path / "moved.capture"
        path.rename(actual)
        path.symlink_to(actual)
    else:
        if fault == "payload":
            data = b"Changed"
        elif fault == "receipt":
            raw_receipt = raw_receipt.replace(b"Authored controller", b"Changed controller")
        else:
            altered = json.loads(raw_receipt)
            altered["metadata"]["file_type"] = ".changed"
            raw_receipt = json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()
            comment = hashlib.sha256(raw_receipt).hexdigest().encode()
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.comment = comment
            archive.writestr("receipt.json", raw_receipt)
            archive.writestr("data.bin", data)
    with pytest.raises(ValueError):
        service.compare(caf, body)


def test_record_access_capture_keeps_boundaries_without_claiming_a_coherent_backup(tmp_path):
    files, service, caf, receipt, _ = setup(tmp_path)
    data = signal_files()[3]
    report = json.loads(json.dumps(receipt))
    report["access_method"] = "record-access"
    report["metadata"]["file_access_method"] = "record-access"
    report["metadata"]["record_count"] = 2
    report["metadata"].pop("metadata_sha256")
    report["metadata"]["metadata_sha256"] = seal(report["metadata"])
    cut = len(data) // 2
    report["record_boundaries"] = [
        {"record": 0, "offset": 0, "length": cut},
        {"record": 1, "offset": cut, "length": len(data) - cut},
    ]
    raw = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    path = files.directory / (receipt["id"] + ".capture")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = hashlib.sha256(raw).hexdigest().encode()
        archive.writestr("receipt.json", raw)
        archive.writestr("data.bin", data)
    result = service.compare(
        caf,
        {
            "source_sha256": caf.hash,
            "capture_id": receipt["id"],
            "receipt_sha256": seal(report),
            "file_sha256": receipt["sha256"],
        },
    )
    assert result["native_file"]["metadata"]["file_access_method"] == "record-access"
    assert result["native_file"]["metadata"]["record_count"] == 2
    assert result["classification"] == "recorded-identities-equal"
    assert not result["native_file"]["full_native_backup"]


def test_receipt_change_after_catalog_is_rejected_even_when_payload_is_unchanged(tmp_path):
    files, service, caf, receipt, body = setup(tmp_path)
    prior = service.sources()["sources"][0]
    path = files.directory / (receipt["id"] + ".capture")
    changed = dict(receipt)
    changed["received_at"] = "2026-01-06T12:00:00+00:00"
    raw = json.dumps(changed, sort_keys=True, separators=(",", ":")).encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.comment = hashlib.sha256(raw).hexdigest().encode()
        archive.writestr("receipt.json", raw)
        archive.writestr("data.bin", signal_files()[3])
    assert service.sources()["sources"][0]["receipt_sha256"] != prior["receipt_sha256"]
    with pytest.raises(ValueError, match="receipt or payload changed"):
        service.compare(caf, body)


def test_token_strict_file_contract_and_exact_bytes_never_create_native_backup_or_network_access(
    tmp_path,
):
    app = create_app(tmp_path)
    caf = caf_source()
    receipt = retained_file(app.state.bacnet_files)
    source = file_source(receipt)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        client.post("/api/caf", headers=headers, files={"file": ("authored.caf", caf.original)})
        catalog = client.get("/api/caf/native-file-sources")
        assert catalog.status_code == 200, catalog.text
        assert catalog.json()["sources"][0]["receipt_sha256"] == source["receipt_sha256"]
        path = "/api/caf/" + caf.hash + "/native-file-correlation"
        body = {
            "source_sha256": caf.hash,
            "capture_id": receipt["id"],
            "receipt_sha256": source["receipt_sha256"],
            "file_sha256": source["sha256"],
        }
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert (
            hashlib.sha256(response.content).hexdigest()
            == response.headers["X-Studio-Artifact-Sha256"]
        )
        for change in [
            {"snapshot_sha256": "a" * 64},
            {"router": "127.0.0.1:1"},
            {"offset": True},
            {"file_sha256": "0" * 64},
        ]:
            assert client.post(path, json=body | change, headers=headers).status_code == 422
        assert (
            client.post(
                "/api/caf/" + caf.hash + "/native-correlation", json=body, headers=headers
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
        assert not app.state.native_applications.storage.captures()
        assert not app.state.native_applications.storage.receipts()


async def test_actual_file_read_then_disconnected_comparison_sends_no_new_protocol_requests(link):
    from .test_bacnet_files import inspect

    server, connector, files, _ = link
    server.payload = signal_files()[3]
    server.stream.fileSize = len(server.payload)
    server.stream.fileType = ".MoZ"
    _, _, _, _, request = await inspect(link)
    receipt = await files.read_raw_file(**request)
    await connector.disconnect()
    before = list(server.all_requests)
    source = file_source(receipt)
    caf = caf_source()
    report = NativeFileCorrelation(files).compare(
        caf,
        {
            "source_sha256": caf.hash,
            "capture_id": receipt["id"],
            "receipt_sha256": source["receipt_sha256"],
            "file_sha256": source["sha256"],
        },
    )
    assert server.all_requests == before
    assert set(before) == {"ReadPropertyRequest", "AtomicReadFileRequest"}
    assert not report["recorded_device_identity_agrees"]
    assert report["native_file"]["target"]["device"] == "device,4190150"
