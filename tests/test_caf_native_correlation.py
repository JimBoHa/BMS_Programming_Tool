"""Independent literal CAF/native identities; no site programs or inferred equivalence."""

import hashlib
import io
import types
import zipfile
from xml.sax.saxutils import escape

import pytest
from bms_tool.app import create_app
from bms_tool.application_store import ApplicationStore
from bms_tool.caf import NS, CafArchive
from bms_tool.caf_native_correlation import CafNativeCorrelationRequest, correlate
from bms_tool.moi_identity import seal
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.storage import Store
from fastapi.testclient import TestClient

from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_signal_compiler import retained, signal_files

UNICODE_ROOT = "🙂" * 260


def unicode_files():
    import gzip
    import struct

    from bacpypes3.primitivedata import CharacterString
    from bms_tool.moi_framing import native_frames
    from bms_tool.moi_identity import MoiIdentity

    from .test_controller_application import encoded, native_record

    files = signal_files()
    native = MoiIdentity(files[3])
    frames = {
        start: (cid, int.from_bytes(oid, "big") & 0x3FFFFF)
        for start, cid, oid, _ in native_frames(native.data, required=True)
    }
    rebuilt = []
    for record in native.records:
        cid, oid = frames[record["offset"]]
        props = []
        for pid, prop in record["properties"].items():
            value = native.data[prop["value_start_offset"] : prop["value_end_offset"] - 1]
            if pid == 32527:
                value = encoded(
                    CharacterString(prop["scalar"]["value"].replace("controller", UNICODE_ROOT, 1))
                )
            props.append((pid, value))
        raw = native_record(cid, oid, props)
        rebuilt.append(struct.pack("<H", len(raw) + 2) + raw)
    files[3] = gzip.compress(native.data[:14] + b"".join(rebuilt), mtime=0)
    return files


def test_unicode_engineering_references_use_character_limits_and_literal_identity(tmp_path):
    _, service, body = setup(tmp_path, unicode_files())
    report = compare(caf_source(root=UNICODE_ROOT), service, body)
    assert report["classification"] == "recorded-identities-equal"
    assert report["coverage"]["record_status_counts"] == {"same-record-identity": 8}
    assert any(row["ref"] == UNICODE_ROOT + "/signal-10" for row in report["records"])


def test_duplicate_native_ids_are_ambiguous_even_with_distinct_engineering_references(tmp_path):
    import gzip
    import struct

    from bacpypes3.primitivedata import CharacterString

    from .test_controller_application import encoded, native_record

    files = signal_files()
    data = gzip.decompress(files[3])
    record = native_record(
        527, 11, [(32527, encoded(CharacterString("controller/native-duplicate")))]
    )
    data = data[:10] + struct.pack("<I", int.from_bytes(data[10:14], "little") + 1) + data[14:]
    files[3] = gzip.compress(data + struct.pack("<H", len(record) + 2) + record, mtime=0)
    _, service, body = setup(tmp_path, files)
    report = compare(caf_source(), service, body)
    assert (
        next(row for row in report["records"] if row["ref"] == "controller/signal-11")["status"]
        == "ambiguous-identity"
    )
    assert report["coverage"]["record_status_counts"]["native-only"] == 1
    assert not report["full_program_match_verified"]


ROWS = (
    [("controller", 470, 5136)]
    + [(f"controller/module-{i}", 200 + i, 40 + i) for i in range(5)]
    + [("controller/signal-10", 526, 10), ("controller/signal-11", 527, 11)]
)


def caf_source(
    *,
    rows=None,
    instance=5136,
    name="Authored controller",
    model="UNLISTED-MODEL",
    root="controller",
    root_class=470,
    extra="",
):
    rows = list(ROWS if rows is None else rows)
    nodes = []
    for ref, cid, oid in rows:
        if ref == "controller":
            cid, oid = root_class, instance
            props = (
                f'<property id="75"><data><BACoid id="8">{instance}</BACoid></data></property>'
                f'<property id="2390"><data><string>{escape(name)}</string></data></property>'
                f'<property id="70"><data><string>{escape(model)}</string></data></property>'
                '<property id="12"><data><string>Authored release</string></data></property>'
            )
        else:
            props = '<property id="3113"><data><float>123.25</float></data></property>'
        ref = ref.replace("controller", root, 1)
        nodes.append(
            f'<object ref="{escape(ref)}" classid="{cid}" objectid="{oid}" classVersion="1.0">'
            f'<property id="32527"><data><string>{escape(ref)}</string></data></property>'
            f"{props}</object>"
        )
    xml = f'<objects xmlns="{NS}">{"".join(nodes)}{extra}<jobInfo><opaque>Preserved</opaque></jobInfo></objects>'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("authored.xml", (2020, 1, 2, 3, 4, 6))
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, xml)
    return CafArchive(stream.getvalue())


def setup(tmp_path, files=None, **metadata):
    storage = ApplicationStore(Store(tmp_path))
    snapshot = retained(storage, files, **metadata)
    body = {"capture_id": snapshot["id"], "snapshot_sha256": snapshot["evidence_sha256"]}
    return storage, NativeBackupRecords(storage), body


def compare(caf, service, body, **updates):
    return correlate(caf, service, body | {"source_sha256": caf.hash} | updates)


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("extended", [False, True])
def test_literal_identifiers_and_metadata_coverage_never_grant_full_program_match(
    tmp_path, compressed, extended
):
    files = signal_files(compressed=compressed, extended=extended)
    storage, service, body = setup(tmp_path, files)
    caf = caf_source()
    report = compare(caf, service, body)
    assert report["classification"] == "recorded-identities-equal"
    assert report["recorded_acquisition_identity_verified"]
    assert [(r["ref"], r["caf_class"], r["caf_object_id"]) for r in report["records"]] == sorted(
        ROWS
    )
    assert all(r["status"] == "same-record-identity" for r in report["records"])
    assert all(row["status"] == "equal" for row in report["device_checks"])
    assert report["coverage"]["native_metadata_records"] == 1
    assert (
        report["coverage"]["caf_objects"] == report["coverage"]["native_engineering_records"] == 8
    )
    assert report["coverage"]["record_status_counts"] == {"same-record-identity": 8}
    assert report["read_only"] and not any(
        report[k]
        for k in (
            "controller_queries",
            "field_actions",
            "can_apply",
            "full_program_match_verified",
            "compiler_compatibility_verified",
            "application_association_granted",
        )
    )
    digest = report.pop("report_sha256")
    assert digest == seal(report)
    # CAF defaults deliberately differ from native defaults; they are NOT compared.
    assert b"123.25" in caf.xml
    assert storage.load(body["capture_id"])[1] == files and not storage.receipts()


@pytest.mark.parametrize(
    "kwargs,field",
    [
        ({"instance": 5137}, "instance"),
        ({"name": "Another controller"}, "name"),
        ({"model": "Another model"}, "model"),
        ({"root": "another-root"}, "root_ref"),
        ({"root_class": 471}, "root_class"),
    ],
)
def test_actual_root_differences_are_reported_without_semantic_incompatibility_claim(
    tmp_path, kwargs, field
):
    _, service, body = setup(tmp_path)
    report = compare(caf_source(**kwargs), service, body)
    checks = {row["field"]: row for row in report["device_checks"]}
    assert checks[field]["status"] == "different"
    assert report["classification"] == "recorded-differences"
    assert not report["application_association_granted"]


@pytest.mark.parametrize(
    "case,status",
    [
        ("different", "different-record-identity"),
        ("missing", "native-only"),
        ("added", "caf-only"),
        ("bad-id", "identity-unavailable"),
        ("duplicate-caf-id", "ambiguous-identity"),
    ],
)
def test_membership_id_conflicts_and_unavailable_or_ambiguous_ids_remain_explicit(
    tmp_path, case, status
):
    _, service, body = setup(tmp_path)
    rows = list(ROWS)
    if case == "different":
        rows[-1] = ("controller/signal-11", 527, 15)
    elif case == "missing":
        rows.pop()
    elif case == "added":
        rows.append(("controller/new", 527, 15))
    elif case == "bad-id":
        rows[-1] = ("controller/signal-11", 527, "011")
    else:
        rows.append(("controller/duplicate", 527, 11))
    report = compare(caf_source(rows=rows), service, body)
    ref = "controller/new" if case == "added" else "controller/signal-11"
    assert next(row for row in report["records"] if row["ref"] == ref)["status"] == status
    assert report["classification"] != "recorded-identities-equal"


@pytest.mark.parametrize(
    "metadata",
    [
        {"source_identity_matches": False},
        {"device": "device,5137"},
        {
            "identity": {
                "object-name": "Authored controller",
                "model-name": "UNLISTED-MODEL",
                "vendor-identifier": 99,
            }
        },
        {
            "identity": {
                "object-name": "Another",
                "model-name": "UNLISTED-MODEL",
                "vendor-identifier": 5,
            }
        },
        {
            "identity": {
                "object-name": "Authored controller",
                "model-name": "Another",
                "vendor-identifier": 5,
            }
        },
    ],
)
def test_retained_acquisition_disagreement_cannot_become_current_identity_or_match(
    tmp_path, metadata
):
    _, service, body = setup(tmp_path, **metadata)
    report = compare(caf_source(), service, body)
    assert not report["recorded_acquisition_identity_verified"]
    assert report["classification"] == "identity-incomplete"
    assert report["native_backup"]["identity_verified"] is False


def test_unknown_saved_values_are_preserved_and_do_not_block_original_archive_comparison(tmp_path):
    files = signal_files()
    files[11], files[12] = b"Unknown selectors", b"Unknown saved values"
    storage, service, body = setup(tmp_path, files)
    report = compare(caf_source(extra='<unknown future="yes"/>'), service, body)
    assert report["classification"] == "recorded-identities-equal"
    assert report["caf"]["root_metadata_entries"] == 2
    assert storage.load(body["capture_id"])[1] == files


def test_conflicting_caf_reference_property_is_not_an_equal_record_identity(tmp_path):
    _, service, body = setup(tmp_path)
    caf = caf_source()
    xml = caf.xml.replace(
        b"<string>controller/signal-10</string>", b"<string>controller/signal-11</string>"
    )
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("authored.xml", xml)
    report = compare(CafArchive(stream.getvalue()), service, body)
    assert report["coverage"]["caf_reference_conflicts"] == 1
    assert (
        next(row for row in report["records"] if row["ref"] == "controller/signal-10")["status"]
        == "identity-unavailable"
    )
    assert report["classification"] == "identity-incomplete"


def test_symlinked_retained_folder_cannot_supply_correlation_evidence(tmp_path):
    storage, service, body = setup(tmp_path)
    folder = storage.directory / body["capture_id"]
    actual = tmp_path / "moved-backup"
    folder.rename(actual)
    folder.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="original storage"):
        compare(caf_source(), service, body)


def test_paging_search_and_explicit_routed_source_come_from_actual_evidence(tmp_path):
    _, service, body = setup(
        tmp_path, target={"address": "7", "router": "127.0.0.1:47919", "dnet": 3001}
    )
    caf = caf_source()
    first = compare(caf, service, body, query="signal", limit=1)
    assert first["total_matches"] == 2 and first["next_offset"] == 1
    assert first["records"][0]["ref"] == "controller/signal-10"
    second = compare(caf, service, body, query="SIGNAL", offset=1, limit=1)
    assert second["records"][0]["ref"] == "controller/signal-11" and second["next_offset"] is None
    assert second["native_backup"]["target"] == {
        "address": "7",
        "router": "127.0.0.1:47919",
        "dnet": 3001,
        "device": "device,5136",
    }


@pytest.mark.parametrize("file_id", [3, 11, 12])
def test_all_original_backup_hashes_are_checked_even_when_saved_values_are_not_compared(
    tmp_path, file_id
):
    storage, service, body = setup(tmp_path)
    (storage.directory / body["capture_id"] / f"file-{file_id}.bin").write_bytes(b"Changed")
    with pytest.raises(ValueError, match="integrity"):
        compare(caf_source(), service, body)


def test_source_manifest_folder_and_resource_admission_are_strict(tmp_path, monkeypatch):
    _, service, body = setup(tmp_path)
    caf = caf_source()
    for updates in [{"source_sha256": "0" * 64}, {"snapshot_sha256": "0" * 64}]:
        with pytest.raises(ValueError):
            compare(caf, service, body, **updates)
    with pytest.raises(ValueError, match="512"):
        compare(caf_source(root="x" * 513), service, body)
    import bms_tool.caf_native_correlation as module

    monkeypatch.setattr(module, "MAX_OBJECTS", 2)
    with pytest.raises(ValueError, match="20000"):
        compare(caf, service, body)


@pytest.mark.parametrize(
    "change", [{"offset": True}, {"limit": 129}, {"query": 3}, {"router": "127.0.0.1:1"}]
)
def test_correlation_request_has_no_network_mutation_fields_or_coercion(change):
    with pytest.raises(ValueError):
        CafNativeCorrelationRequest.model_validate(
            {
                "capture_id": "a" * 32,
                "snapshot_sha256": "b" * 64,
                "source_sha256": "c" * 64,
                **change,
            }
        )


def test_http_token_and_exact_response_bytes_bind_both_sources_without_opening_field_network(
    tmp_path,
):
    app = create_app(tmp_path)
    snapshot = retained(app.state.native_applications.storage)
    caf = caf_source()
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        uploaded = client.post(
            "/api/caf", headers=headers, files={"file": ("authored.caf", caf.original)}
        ).json()
        path = "/api/caf/" + uploaded["sha256"] + "/native-correlation"
        body = {
            "source_sha256": caf.hash,
            "capture_id": snapshot["id"],
            "snapshot_sha256": snapshot["evidence_sha256"],
        }
        assert client.post(path, json=body).status_code == 403
        response = client.post(path, json=body, headers=headers)
        assert response.status_code == 200, response.text
        assert (
            hashlib.sha256(response.content).hexdigest()
            == response.headers["X-Studio-Artifact-Sha256"]
        )
        assert response.json()["request"] == body | {"query": "", "offset": 0, "limit": 64}
        for change in [{"source_sha256": "0" * 64}, {"target": {}}, {"capture_id": "../source"}]:
            assert client.post(path, json=body | change, headers=headers).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
        assert not app.state.native_applications.storage.receipts()


async def test_captured_then_disconnected_comparison_has_no_further_peer_requests(native_link):
    peer, bacnet, _, native, target = native_link
    peer.files = signal_files()
    seen = []
    original = peer.indication

    async def watch(self, apdu):
        seen.append(type(apdu).__name__)
        await original(apdu)

    peer.indication = types.MethodType(watch, peer)
    captured = await native.capture(**target, operation_id="capture-for-caf-correlation")
    await bacnet.disconnect()
    before = list(seen)
    with pytest.raises(ValueError, match="evidence changed"):
        compare(
            caf_source(),
            NativeBackupRecords(native.storage),
            {"capture_id": captured["id"], "snapshot_sha256": captured["evidence_sha256"]},
        )
    report = compare(
        caf_source(),
        NativeBackupRecords(native.storage),
        {"capture_id": captured["id"], "snapshot_sha256": captured["snapshot_evidence_sha256"]},
    )
    assert report["classification"] == "recorded-identities-equal"
    assert "ReinitializeDeviceRequest" in seen and seen == before
    assert not native.storage.receipts()
