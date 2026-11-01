"""Previous names are local, source-bound proposals rather than old-plan replays."""

import gzip
import secrets

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.native_applications import NativeApplications, NativeNameRecoveryPreview
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_name_recovery import NativeNameRecovery
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_default_recovery import set_saved
from .test_native_signal_compiler import FIRST, retained, signal_files


def setup(
    path,
    *,
    name="Renamed controller",
    previous="Authored controller",
    compressed=True,
    extended=False,
    outcome="verified",
    dispatched=True,
    changes=None,
):
    storage = ApplicationStore(Store(path))
    files = signal_files(compressed=compressed, extended=extended)
    if previous != "Authored controller":
        files = files | {3: NativeApplications.compile(files, 5136, previous)[0]}
    before = retained(
        storage,
        files,
        identity={
            "object-name": previous,
            "model-name": "UNLISTED-MODEL",
            "vendor-identifier": 5,
        },
    )
    output, compilation = NativeApplications.compile(files, 5136, name)
    parent_id = secrets.token_hex(16)
    intent = storage.intent(
        {
            "id": parent_id,
            "target": before["target"],
            "identity": before["identity"],
            "old_instance": 5136,
            "new_instance": 5136,
            "change_kind": "name",
            "old_name": previous,
            "new_name": name,
            "name_change_confirmed": True,
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
            },
        )
    current_files = {**files, 3: output}
    current = retained(storage, current_files, identity={**before["identity"], "object-name": name})
    request = {
        "receipt_id": parent_id,
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeNameRecovery(NativeBackupRecords(storage), NativeApplications.compile),
        request,
        before,
        current_files,
    )


def current_source(storage, request, files, **metadata):
    metadata.setdefault("identity", storage.load(request["capture_id"])[0]["identity"])
    snap = retained(storage, files, **metadata)
    return {**request, "capture_id": snap["id"], "snapshot_sha256": snap["evidence_sha256"]}


@pytest.mark.parametrize("previous", ["X", "Contrôleur extérieur", "é" * 64])
def test_actual_previous_utf8_name_is_kept_exactly(tmp_path, previous):
    _, service, request, _, files = setup(tmp_path, previous=previous)
    report = service.prepare(request)
    assert report["proposal"]["new_name"] == previous
    output, _ = NativeApplications.compile(files, 5136, previous)
    assert MoiIdentity(output).summary()["name"] == previous


@pytest.mark.parametrize("field,value", [("root_ref", "another-root"), ("root_class", 471)])
def test_new_review_origin_requires_the_exact_current_native_root(tmp_path, field, value):
    _, service, request, _, files = setup(tmp_path)
    report = service.prepare(request)
    native = object.__new__(NativeApplications)
    native.name_recovery = service
    options = NativeNameRecoveryPreview(
        address="127.0.0.1:47819",
        device="device,5136",
        operation_id="local-name-origin-proof",
        **report["proposal"],
        recovery_origin_sha256=report["origin_sha256"],
    )
    _, compilation = NativeApplications.compile(files, 5136, "Authored controller")
    assert native.name_recovery_origin(options, compilation)["recovery_origin"] == report["origin"]
    compilation["identity_edit"][field] = value
    with pytest.raises(ValueError, match="proposal changed"):
        native.name_recovery_origin(options, compilation)


@pytest.mark.parametrize("problem", ["missing", "tampered", "symlink"])
def test_original_backup_files_remain_required_for_new_name_proposals(tmp_path, problem):
    storage, service, request, before, _ = setup(tmp_path)
    folder = storage.directory / before["id"]
    if problem == "missing":
        (folder / "file-3.bin").unlink()
    elif problem == "tampered":
        (folder / "file-12.bin").write_bytes(b"modified original settings")
    else:
        moved = folder.with_name(folder.name + "-moved")
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("name", ["X", "Longer renamed controller", "Contrôleur extérieur"])
def test_local_previous_name_reframes_only_the_name_and_keeps_fresh_saved_values(
    tmp_path, compressed, extended, name
):
    storage, service, request, before, files = setup(
        tmp_path, name=name, compressed=compressed, extended=extended
    )
    original = storage.receipt(request["receipt_id"])
    fresh = set_saved(files, 17.5, second=True)
    request = current_source(storage, request, fresh)
    report = service.prepare(request)
    assert report["previous_name"] == "Authored controller"
    assert report["current_name"] == report["recorded_after_name"] == name
    assert report["read_only"] and report["new_review_required"]
    assert not any(
        report[key]
        for key in ("controller_queries", "field_actions", "can_apply", "already_recorded")
    )
    assert report["origin_sha256"] == seal(report["origin"])
    assert report["proposal"] == {
        "capture_id": request["capture_id"],
        "snapshot_sha256": request["snapshot_sha256"],
        "new_instance": 5136,
        "new_name": "Authored controller",
        "recovery_parent_receipt": request["receipt_id"],
    }
    output, compilation = NativeApplications.compile(fresh, 5136, report["proposal"]["new_name"])
    parsed = MoiIdentity(output)
    assert parsed.instance == 5136 and parsed.summary()["name"] == "Authored controller"
    assert parsed.reader.scalar(parsed.reader.records[FIRST], 3113) == 42.0
    assert parsed.reader.scalar(parsed.reader.records["controller/signal-11"], 3113) == 17.5
    assert compilation["identity_edit"]["change_kind"] == "name"
    assert len(storage.receipts()) == 1 and storage.receipt(request["receipt_id"]) == original
    assert storage.load(before["id"])[1] == signal_files(compressed=compressed, extended=extended)
    assert storage.load(request["capture_id"])[1] == fresh


def test_already_recorded_old_name_is_not_a_restore_claim(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    output, _ = NativeApplications.compile(files, 5136, "Authored controller")
    request = current_source(
        storage,
        request,
        {**files, 3: output},
        identity={
            **storage.load(request["capture_id"])[0]["identity"],
            "object-name": "Authored controller",
        },
    )
    report = service.prepare(request)
    assert report["already_recorded"] and report["proposal"] is None
    assert not report["can_apply"] and not report["new_review_required"]


@pytest.mark.parametrize(
    "change",
    [
        "route",
        "model",
        "device",
        "vendor",
        "unqualified",
        "directory",
        "application",
        "name",
        "snapshot",
    ],
)
def test_changed_current_source_refuses_locally(tmp_path, change):
    storage, service, request, _, files = setup(tmp_path)
    metadata = {}
    identity = storage.load(request["capture_id"])[0]["identity"]
    if change == "route":
        metadata["target"] = {"address": "3001:8", "router": "127.0.0.1:47820", "dnet": 3001}
    elif change == "model":
        metadata["identity"] = identity | {"model-name": "OTHER"}
    elif change == "device":
        metadata["device"] = "device,5137"
    elif change == "vendor":
        metadata["identity"] = identity | {"vendor-identifier": 99}
    elif change == "unqualified":
        metadata["source_identity_matches"] = False
    elif change == "directory":
        files = files | {11: files[11] + b"changed"}
    elif change == "application":
        files = files | {
            3: gzip.compress(
                MoiIdentity(files[3]).data.replace(b"Authored signal", b"Modified signal"), mtime=0
            )
        }
    elif change == "name":
        files = files | {3: NativeApplications.compile(files, 5136, "An unrelated name")[0]}
        metadata["identity"] = identity | {"object-name": "An unrelated name"}
    request = current_source(storage, request, files, **metadata)
    if change == "snapshot":
        request["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize(
    "changes",
    [
        {"change_kind": "instance"},
        {"old_instance": True},
        {"new_instance": 5137},
        {"name_change_confirmed": 1},
        {"application_transfer_confirmed": False},
        {"old_name": "Different prior name"},
        {"old_name": ""},
        {"new_name": "Authored controller"},
        {"payload_sha256": "0" * 64},
        {"native_payload_sha256": "0" * 64},
        {"compilation": {}},
    ],
)
def test_malformed_or_other_operation_parent_cannot_supply_a_name(tmp_path, changes):
    _, service, request, _, _ = setup(tmp_path, changes=changes)
    with pytest.raises(ValueError):
        service.prepare(request)


@pytest.mark.parametrize(
    "outcome,dispatched",
    [("intent-only", True), ("uncertain", True), ("not_sent", False), ("verified", False)],
)
def test_pending_unverified_or_unsent_original_refuses(tmp_path, outcome, dispatched):
    _, service, request, _, _ = setup(tmp_path, outcome=outcome, dispatched=dispatched)
    with pytest.raises(ValueError):
        service.prepare(request)


def test_verified_readback_event_survives_a_later_observation(tmp_path):
    storage, service, request, _, _ = setup(tmp_path, outcome="uncertain")
    storage.resolve(request["receipt_id"], {"status": "verified"})
    first = storage.verified_readback(request["receipt_id"])
    storage.resolve(request["receipt_id"], {"status": "unverified"})
    report = service.prepare(request)
    assert report["origin"]["verified_proof"]["kind"] == "readback-event"
    assert report["origin"]["verified_proof"]["sha256"] == first["evidence_sha256"]


def test_http_prepare_is_local_authenticated_and_strict(tmp_path):
    _, _, request, _, _ = setup(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        route = "/api/bacnet/controller/native-application/name/recovery/prepare"
        assert client.post(route, json=request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        result = client.post(route, headers=headers, json=request)
        assert result.status_code == 200, result.text
        assert result.json()["previous_name"] == "Authored controller"
        assert not client.get("/api/session").json()["field_network_open"]
        for extra in ({"apply": True}, {"new_name": "Injected"}, {"recovery_origin": {}}):
            assert client.post(route, headers=headers, json=request | extra).status_code == 422


def test_local_name_source_qualifies_actual_root_and_keeps_generic_reader_unchanged(tmp_path):
    storage, service, request, _, files = setup(tmp_path)
    source_request = {key: request[key] for key in ("capture_id", "snapshot_sha256")}
    generic = NativeBackupRecords(storage).source(source_request)
    result = service.source(source_request)
    parsed = MoiIdentity(files[3])
    assert result["profile"] == "native-controller-name-recovery-source/1"
    assert result["application"] == parsed.summary()
    assert result["sha256"] == sha(files[3]) and result["read_only"]
    assert (
        not result["can_apply"] and not result["controller_queries"] and not result["field_actions"]
    )
    assert NativeBackupRecords(storage).source(source_request) == generic
    with TestClient(create_app(tmp_path)) as client:
        route = "/api/bacnet/controller/native-application/name/recovery/source"
        assert client.post(route, json=source_request).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(route, headers=headers, json=source_request)
        assert response.status_code == 200 and response.json() == result
        assert (
            client.post(route, headers=headers, json=source_request | {"apply": True}).status_code
            == 422
        )
        assert not client.get("/api/session").json()["field_network_open"]
