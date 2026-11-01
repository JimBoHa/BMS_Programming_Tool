"""Verified before/after images qualify a local previous-instance proposal."""

import gzip
import secrets
import struct

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_applications import NativeApplications
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_instance_recovery import NativeInstanceRecovery, normalized_directory
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_default_recovery import set_saved
from .test_native_default_transfer import real_slot
from .test_native_signal_compiler import FIRST, SECOND, retained, signal_files


def rekey(directory, previous, after):
    # Independently author the fixture's known class-470 root-selector bytes.
    data = bytearray(directory)
    offset = 0
    while offset < len(data):
        size = int.from_bytes(data[offset : offset + 2], "big")
        oid = int.from_bytes(data[offset + 2 : offset + 6], "big")
        cid = int.from_bytes(data[offset + 10 : offset + 12], "big")
        if cid == 470 and oid % (1 << 22) == previous:
            data[offset + 2 : offset + 6] = (oid // (1 << 22) * (1 << 22) + after).to_bytes(
                4, "big"
            )
        offset += size
    return bytes(data)


def setup(
    path,
    *,
    previous=5136,
    after=5336,
    compressed=True,
    extended=False,
    rekey_post=True,
    outcome="verified",
    dispatched=True,
    changes=None,
):
    storage = ApplicationStore(Store(path))
    files = signal_files(compressed=compressed, extended=extended)
    if previous != 5136:
        payload, _ = NativeApplications.compile(files, previous)
        files = files | {3: payload, 11: rekey(files[11], 5136, previous)}
    before = retained(storage, files, device=f"device,{previous}")
    output, compilation = NativeApplications.compile(files, after)
    post_files = files | {3: output}
    if rekey_post:
        post_files[11] = rekey(files[11], previous, after)
    post = retained(storage, post_files, device=f"device,{after}")
    parent_id = secrets.token_hex(16)
    intent = storage.intent(
        {
            "id": parent_id,
            "target": before["target"],
            "identity": before["identity"],
            "old_instance": previous,
            "new_instance": after,
            "change_kind": "instance",
            "old_name": before["identity"]["object-name"],
            "new_name": before["identity"]["object-name"],
            "allocation_confirmed": True,
            "application_transfer_confirmed": True,
            "backup_id": before["id"],
            "compilation": compilation,
            "payload_sha256": sha(output),
            "native_payload_sha256": sha(MoiIdentity(output).data),
            **(changes or {}),
        }
    )
    if outcome != "intent-only":
        storage.finish(
            parent_id,
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": outcome,
                "may_have_applied": dispatched,
                "verification_capture_id": post["id"],
            },
        )
    current = retained(storage, post_files, device=f"device,{after}")
    request = {
        "receipt_id": parent_id,
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeInstanceRecovery(NativeBackupRecords(storage), NativeApplications.compile),
        request,
        before,
        post,
        post_files,
    )


def current_source(storage, request, files, **metadata):
    current, _ = storage.load(request["capture_id"])
    metadata.setdefault("device", current["device"])
    metadata.setdefault("identity", current["identity"])
    snapshot = retained(storage, files, **metadata)
    return request | {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("rekey_post", [False, True])
def test_local_proposal_uses_actual_verified_after_directory_and_preserves_fresh_settings(
    tmp_path, compressed, extended, rekey_post
):
    storage, service, request, before, post, files = setup(
        tmp_path, compressed=compressed, extended=extended, rekey_post=rekey_post
    )
    parent = storage.receipt(request["receipt_id"])
    files = set_saved(files, 17.5, second=True)
    request = current_source(storage, request, files)
    report = service.prepare(request)
    assert report["previous_instance"] == 5136 and report["current_instance"] == 5336
    assert report["unchanged_name"] == "Authored controller"
    assert report["origin"]["verified_after_capture_id"] == post["id"]
    assert report["origin"]["verified_after_snapshot_sha256"] == post["evidence_sha256"]
    assert report["origin"]["verified_after_static_sha256"] == sha(files[11])
    assert report["origin_sha256"] == seal(report["origin"])
    assert report["proposal"] == {
        "capture_id": request["capture_id"],
        "snapshot_sha256": request["snapshot_sha256"],
        "new_instance": 5136,
        "recovery_parent_receipt": request["receipt_id"],
    }
    assert report["read_only"] and report["new_review_required"]
    assert not any(
        report[k] for k in ("controller_queries", "field_actions", "can_apply", "already_recorded")
    )
    output, compilation = NativeApplications.compile(files, 5136)
    parsed = MoiIdentity(output)
    assert parsed.instance == 5136 and parsed.summary()["name"] == "Authored controller"
    assert parsed.reader.scalar(parsed.reader.records[FIRST], 3113) == 42.0
    assert parsed.reader.scalar(parsed.reader.records[SECOND], 3113) == 17.5
    assert len(compilation["identity_edit"]["edits"]) == 2
    assert storage.receipt(request["receipt_id"]) == parent and len(storage.receipts()) == 1
    assert storage.load(before["id"])[1] == signal_files(compressed=compressed, extended=extended)


@pytest.mark.parametrize("previous,after", [(0, 4194302), (4194302, 0), (5136, 5137)])
def test_exact_previous_unsigned22_device_boundaries(tmp_path, previous, after):
    _, service, request, _, _, files = setup(tmp_path, previous=previous, after=after)
    report = service.prepare(request)
    assert report["proposal"]["new_instance"] == previous
    assert MoiIdentity(NativeApplications.compile(files, previous)[0]).instance == previous


def test_already_recorded_old_number_normalizes_only_typed_root_directory_aliases(tmp_path):
    storage, service, request, _, _, files = setup(tmp_path)
    output, _ = NativeApplications.compile(files, 5136)
    restored = files | {3: output, 11: rekey(files[11], 5336, 5136)}
    request = current_source(storage, request, restored, device="device,5136")
    report = service.prepare(request)
    assert report["already_recorded"] and report["proposal"] is None
    assert report["origin"]["normalized_root_selectors"] > 0
    assert report["origin"]["normalized_static_sha256"] == sha(files[11])
    assert not report["new_review_required"] and not report["can_apply"]


@pytest.mark.parametrize("rekey_post", [False, True])
def test_destination_cannot_silently_activate_an_unmatched_saved_root_value(tmp_path, rekey_post):
    storage, service, request, _, _, files = setup(tmp_path, rekey_post=rekey_post)
    real_slot(files, 4, struct.pack(">f", 9.25))
    request = current_source(storage, request, files)
    if not rekey_post:
        with pytest.raises(ValueError, match="saved|parameter|setting"):
            service.prepare(request)
    else:
        report = service.prepare(request)
        output, _, preservation = service.qualified_inverse(
            files, report["proposal"]["new_instance"]
        )
        parsed = MoiIdentity(output)
        assert parsed.reader.scalar(parsed.root, 900) == 9.25
        assert preservation["application_identical_except_instance"]


@pytest.mark.parametrize(
    "change",
    ["route", "name", "device", "vendor", "unqualified", "directory", "application", "snapshot"],
)
def test_changed_current_source_refuses_without_network(tmp_path, change):
    storage, service, request, _, _, files = setup(tmp_path)
    metadata = {}
    identity = storage.load(request["capture_id"])[0]["identity"]
    if change == "route":
        metadata["target"] = {"address": "3001:7", "router": "127.0.0.1:47820", "dnet": 3001}
    elif change == "name":
        metadata["identity"] = identity | {"object-name": "A different name"}
    elif change == "device":
        metadata["device"] = "device,5337"
    elif change == "vendor":
        metadata["identity"] = identity | {"vendor-identifier": 99}
    elif change == "unqualified":
        metadata["source_identity_matches"] = False
    elif change == "directory":
        files = files | {11: files[11].replace(b"\x56\x78", b"\x56\x79")}
    elif change == "application":
        files = files | {
            3: gzip.compress(
                MoiIdentity(files[3]).data.replace(b"Authored signal", b"Modified signal"), mtime=0
            )
        }
    request = current_source(storage, request, files, **metadata)
    if change == "snapshot":
        request["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize(
    "changes",
    [
        {"change_kind": "name"},
        {"old_instance": True},
        {"new_instance": 4194303},
        {"allocation_confirmed": 1},
        {"application_transfer_confirmed": False},
        {"new_name": "Another name"},
        {"payload_sha256": "0" * 64},
        {"compilation": {}},
    ],
)
def test_malformed_parent_or_different_operation_cannot_allocate_a_number(tmp_path, changes):
    _, service, request, _, _, _ = setup(tmp_path, changes=changes)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("kind", ["before", "verified-after"])
def test_missing_original_or_verified_after_files_refuses_a_new_proposal(tmp_path, kind):
    storage, service, request, before, post, _ = setup(tmp_path)
    snapshot = before if kind == "before" else post
    (storage.directory / snapshot["id"] / "file-3.bin").unlink()
    with pytest.raises(ValueError):
        service.prepare(request)


def test_static_normalization_preserves_unknown_bytes_and_nonroot_selectors(tmp_path):
    _, _, _, _, _, files = setup(tmp_path)
    old = rekey(files[11], 5336, 5136)
    actual, count = normalized_directory(
        old, root_class=470, current_instance=5136, recorded_instance=5336
    )
    assert actual == files[11] and count > 0
    assert len(actual) == len(old)
    with pytest.raises(ValueError):
        normalized_directory(
            old + b"\x00", root_class=470, current_instance=5136, recorded_instance=5336
        )


def test_source_and_prepare_http_are_local_authenticated_and_strict(tmp_path):
    _, service, request, _, _, _ = setup(tmp_path)
    source_request = {key: request[key] for key in ("capture_id", "snapshot_sha256")}
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        base = "/api/bacnet/controller/native-application"
        for kind, body, expected in [
            ("source", source_request, service.source(source_request)),
            ("prepare", request, service.prepare(request)),
        ]:
            route = base + "/instance/recovery/" + kind
            assert client.post(route, json=body).status_code == 403
            response = client.post(route, json=body, headers=headers)
            assert response.status_code == 200 and response.json() == expected
            for extra in ({"apply": True}, {"new_name": "Injected"}):
                assert client.post(route, json=body | extra, headers=headers).status_code == 422
        report = service.prepare(request)
        proposal = report["proposal"] | {
            "address": "127.0.0.1:47819",
            "device": "device,5336",
            "operation_id": "local-strict-instance-preview",
            "recovery_origin_sha256": report["origin_sha256"],
        }
        assert client.post(base + "/preview", json=proposal, headers=headers).status_code == 422
        assert (
            client.post(
                base + "/instance/recovery/preview",
                json=proposal | {"new_name": "Injected"},
                headers=headers,
            ).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
