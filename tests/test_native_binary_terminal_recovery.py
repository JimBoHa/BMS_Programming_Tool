"""Previous-terminal drafts bind verified journals and original/current native files."""

import copy
import secrets
import struct

import pytest
from bacpypes3.primitivedata import CharacterString, Enumerated, Real, Unsigned
from bms_tool.app import create_app
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.mstp import header_crc
from bms_tool.native_backup_records import NativeBackupRecords
from bms_tool.native_binary_terminal import BinaryTerminalCompiler
from bms_tool.native_binary_terminal_recovery import PROFILE, NativeBinaryTerminalRecovery
from bms_tool.native_inputs import (
    InputEdit,
    NativeInputCompiler,
    archive,
    verify_input_preservation,
)
from fastapi.testclient import TestClient

from .test_controller_application import encoded, native_record
from .test_native_applications import native_link as native_link  # noqa: F401
from .test_native_binary_terminal import edit as terminal_edit
from .test_native_binary_terminal import replaced
from .test_native_binary_terminal_transfer import binary_peer, tick, with_counter
from .test_native_connection_copies import filesystem
from .test_native_default_transfer import real_slot
from .test_native_input_transfer import apply, preview
from .test_native_signal_compiler import retained, slot
from .test_native_terminal_copies import literal_effective
from .test_native_terminal_copies import setup as original_source
from .test_native_terminal_labels import observed_shape

BASE = "/api/bacnet/controller/native-application/input/binary-terminal/recovery/prepare"


def setup(
    tmp_path, *, outcome="verified", possible=True, change=None, files=None, result_change=None
):
    storage, _, files, source = original_source(
        tmp_path, files=files or observed_shape(compressed=True)
    )
    before = storage.load(source["capture_id"])[0]
    compiler = NativeInputCompiler(files)
    edit = InputEdit.model_validate(terminal_edit(BinaryTerminalCompiler(compiler))).model_dump()
    output, compilation = compiler.compile(edit)
    body = {
        "id": secrets.token_hex(16),
        "target": before["target"],
        "identity": before["identity"],
        "old_instance": 5136,
        "new_instance": 5136,
        "old_name": "Authored controller",
        "new_name": "Authored controller",
        "change_kind": "input",
        "operation_profile": "native-local-universal-input-transfer/3",
        "physical_wiring_confirmed": True,
        "input_change_confirmed": True,
        "application_transfer_confirmed": True,
        "backup_id": before["id"],
        "input_edit": copy.deepcopy(edit),
        "compilation": compilation,
        "payload_sha256": sha(output),
        "native_payload_sha256": sha(MoiIdentity(output).data),
    }
    if change:
        change(body)
    intent = storage.intent(body)
    verification = {
        "intent_sha256": intent["evidence_sha256"],
        "status": outcome,
        "may_have_applied": possible,
        "operational": True,
        "system_status": 0,
        "native_sha256": sha(MoiIdentity(output).data),
        "preservation": verify_input_preservation(files, {**files, 3: output}, edit),
    }
    if result_change:
        result_change(verification)
    if outcome != "intent-only":
        storage.finish(intent["id"], verification)
    current_files = {**files, 3: output}
    current = retained(storage, current_files, identity=before["identity"])
    query = {
        "receipt_id": intent["id"],
        "capture_id": current["id"],
        "snapshot_sha256": current["evidence_sha256"],
    }
    return (
        storage,
        NativeBinaryTerminalRecovery(NativeBackupRecords(storage)),
        query,
        before,
        current_files,
        verification,
    )


@pytest.mark.parametrize("missing", [(), (15, 33, 84)])
@pytest.mark.parametrize("encoding", [0, 4])
@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wide", [False, True])
@pytest.mark.parametrize("slot_width", [1, 2, 3, 4])
def test_complete_literal_inverse_preserves_current_other_values_and_retained_evidence(
    tmp_path, compressed, wide, slot_width, encoding, missing
):
    original = observed_shape(
        binary=True, compressed=compressed, wide=wide, slot_width=slot_width, encoding=encoding
    )
    if missing:
        original = without_optional(original, missing)
    storage, service, query, before, files, _ = setup(tmp_path, files=original)
    current = copy.deepcopy(files)
    # An unrelated saved Real changes after the original move, without changing File3/11.
    real_slot(current, 4, struct.pack(">f", 9.25))
    capture = retained(storage, current, identity=before["identity"])
    query |= {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    unchanged = filesystem(storage.directory)
    report = service.prepare(query)
    assert report["profile"] == PROFILE and not report["already_recorded"]
    assert report["new_review_required"] and not report["can_apply"]
    assert (
        report["read_only"]
        and not report["controller_queries"]
        and not report["controller_writes"]
        and not report["field_actions"]
    )
    assert report["parent_lineage_enforced_by_field_transfer"] is False and "token" not in report
    assert report["origin"]["previous_slot"] == report["origin"]["proposal_slot"] == 1
    assert report["origin"]["current_slot"] == report["origin"]["recorded_after_slot"] == 3
    assert seal(report["origin"]) == report["origin_sha256"]
    assert (
        seal({k: v for k, v in report.items() if k != "evidence_sha256"})
        == report["evidence_sha256"]
    )
    proposal = report["proposal"]
    assert proposal["edit"]["action"] == "binary-terminal"
    inverse_fields = report["inverse_compilation"]
    assert inverse_fields["stored_configuration"]["polarity"] == (None if 84 in missing else 1)
    assert set(inverse_fields["captured_counter_values"]) == ({"15", "33"} - set(map(str, missing)))
    assert (
        report["inverse_compilation"]["terminal_compilation"]["device_type_character_encoding"]
        == encoding
    )
    output, compiled = NativeInputCompiler(current).compile(proposal["edit"])
    expected = literal_effective(MoiIdentity(original[3]).data)
    actual = MoiIdentity(output)
    # Fresh root saved value is preserved; the selected two terminal payloads return exactly.
    assert actual.reader.scalar(actual.root, 900) == 9.25
    assert actual.data.count(encoded(Real(9.25))) == 1
    assert actual.data.replace(encoded(Real(9.25)), encoded(Real(3.5)), 1) == expected
    assert report["inverse_compilation"] == compiled and report["inverse_output_sha256"] == sha(
        output
    )
    assert verify_input_preservation(current, {**current, 3: output}, proposal["edit"])[
        "other_configuration_preserved"
    ]
    assert MoiIdentity(expected).reader.scalar(MoiIdentity(expected).root, 900) == 3.5
    assert filesystem(storage.directory) == unchanged


def test_already_previous_merged_native_image_returns_no_inverse_or_authority(tmp_path):
    storage, service, query, before, _, _ = setup(tmp_path)
    _, original = storage.load(before["id"])
    previous = {**original, 3: NativeInputCompiler(original).app.source}
    current = retained(storage, previous, identity=before["identity"])
    report = service.prepare(
        query | {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}
    )
    assert report["already_recorded"] and not report["new_review_required"]
    assert all(
        report[k] is None for k in ["proposal", "inverse_compilation", "inverse_output_sha256"]
    )


@pytest.mark.parametrize(
    "outcome,possible",
    [
        ("intent-only", True),
        ("unknown", True),
        ("failed", True),
        ("not_sent", False),
        ("verified", False),
    ],
)
def test_unresolved_unverified_or_not_dispatched_parent_never_supplies_an_inverse(
    tmp_path, outcome, possible
):
    _, service, query, *_ = setup(tmp_path, outcome=outcome, possible=possible)
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "key,value",
    [
        ("operation_profile", "native-local-universal-input-transfer/1"),
        ("change_kind", "signal-default"),
        ("physical_wiring_confirmed", False),
        ("input_change_confirmed", False),
        ("application_transfer_confirmed", False),
        ("new_instance", 5137),
        ("old_instance", True),
        ("payload_sha256", "0" * 64),
        ("native_payload_sha256", "0" * 64),
        ("old_name", "Different"),
    ],
)
def test_parent_identity_confirmations_profile_and_payload_are_recomputed(tmp_path, key, value):
    _, service, query, *_ = setup(tmp_path, change=lambda b: b.update({key: value}))
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "fault",
    [
        "slot",
        "config",
        "compilation",
        "bool-alias",
        "extra-edit",
        "result-hash",
        "result-preservation",
    ],
)
def test_resealed_but_inconsistent_parent_or_verified_outcome_is_refused(tmp_path, fault):
    def change(b):
        if fault == "slot":
            b["input_edit"]["slot"] = 2
        elif fault == "config":
            b["input_edit"]["configuration_sha256"] = "0" * 64
        elif fault == "compilation":
            b["compilation"]["terminal_compilation"]["destination_slot"] = 2
        elif fault == "bool-alias":
            b["compilation"]["terminal_compilation"]["old_slot"] = True
        elif fault == "extra-edit":
            b["input_edit"]["unexpected"] = True

    def result(v):
        if fault == "result-hash":
            v["native_sha256"] = "0" * 64
        elif fault == "result-preservation":
            v["preservation"]["other_configuration_preserved"] = False

    _, service, query, *_ = setup(tmp_path, change=change, result_change=result)
    with pytest.raises(ValueError):
        service.prepare(query)


@pytest.mark.parametrize(
    "fault",
    ["route", "identity", "static", "program", "selected-config", "stale-snapshot", "unverified"],
)
def test_current_source_must_remain_the_recorded_controller_and_application(tmp_path, fault):
    storage, service, query, before, files, _ = setup(tmp_path)
    metadata = {"identity": before["identity"]}
    if fault == "route":
        metadata["target"] = {"address": "127.0.0.2:47819", "router": None, "dnet": None}
    elif fault == "identity":
        metadata["identity"] = {**before["identity"], "object-name": "Other"}
    elif fault == "static":
        files[11] += b"changed"
    elif fault == "program":
        files[3] = MoiIdentity(files[3]).data.replace(b"opaque footer", b"OPAQUE footer")
    elif fault == "selected-config":
        app = MoiIdentity(files[3])
        record = next(r for r in app.records if app.reader.scalar(r, 75) == "binary-input,101")
        prop = record["properties"][84]
        files[3] = (
            app.data[: prop["value_start_offset"]]
            + encoded(Enumerated(0))
            + app.data[prop["value_end_offset"] - 1 :]
        )
    elif fault == "unverified":
        metadata["source_identity_matches"] = False
    current = retained(storage, files, **metadata)
    query |= {"capture_id": current["id"], "snapshot_sha256": current["evidence_sha256"]}
    if fault == "stale-snapshot":
        query["snapshot_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        service.prepare(query)


def test_unknown_original_dispatch_can_use_a_later_immutable_verified_readback(tmp_path):
    storage, service, query, _, _, verification = setup(tmp_path, outcome="unknown")
    verification["status"] = "verified"
    storage.resolve(query["receipt_id"], verification)
    report = service.prepare(query)
    assert report["origin"]["verified_proof"]["kind"] == "readback-event"
    assert storage.receipt(query["receipt_id"])["result"]["status"] == "unknown"


def test_strict_local_http_preparation_has_no_field_or_transfer_effect(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    storage, service, query, *_ = setup(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Local recovery preparation attempted a field/intent path")

    for name in ["require", "_read", "connect", "disconnect", "release"]:
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    monkeypatch.setattr(app.state.native_applications.storage, "intent", forbidden)
    before = filesystem(storage.directory)
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, json=query).status_code == 403
        response = client.post(BASE, headers=headers, json=query)
        assert response.status_code == 200 and response.json() == service.prepare(query)
        for change in [
            {"token": "A" * 32},
            {"can_apply": True},
            {"edit": {}},
            {"receipt_id": True},
            {"snapshot_sha256": "0" * 64},
        ]:
            assert client.post(BASE, headers=headers, json=query | change).status_code == 422
        assert not client.get("/api/session").json()["field_network_open"]
        assert not app.state.native_applications.plans
    assert filesystem(storage.directory) == before


@pytest.mark.parametrize("fault", ["profile", "identity", "selected-edit", "status-type"])
def test_verified_result_requires_exact_typed_preservation_evidence(tmp_path, fault):
    def changed(result):
        if fault == "profile":
            result["preservation"]["profile"] = "native-local-universal-input-transfer/2"
        elif fault == "identity":
            result["preservation"]["identity_unchanged"] = False
        elif fault == "selected-edit":
            result["preservation"]["selected_edit"]["slot"] = 3.0
        else:
            result["system_status"] = 0.0

    _, service, query, *_ = setup(tmp_path, result_change=changed)
    with pytest.raises(ValueError, match="complete native preservation"):
        service.prepare(query)


def test_legacy_terminal_receipt_cannot_supply_a_typed_recovery_proposal(tmp_path):
    from .test_native_terminal_recovery import setup as legacy_setup

    storage, _, query, *_ = legacy_setup(tmp_path)
    before = filesystem(storage.directory)
    with pytest.raises(ValueError, match="configured binary"):
        NativeBinaryTerminalRecovery(NativeBackupRecords(storage)).prepare(query)
    assert filesystem(storage.directory) == before


def without_optional(files, properties):
    app = MoiIdentity(files[3])
    selected = next(r for r in app.records if app.reader.scalar(r, 32527) == "controller/3_101")
    raw = native_record(
        242,
        101,
        [
            (pid, app.data[p["value_start_offset"] : p["value_end_offset"] - 1])
            for pid, p in selected["properties"].items()
            if pid not in properties
        ],
    )
    return {
        **files,
        3: archive(
            app,
            [
                raw if r is selected else app.data[r["offset"] : r["end_offset"]]
                for r in app.records
            ],
        ),
    }


def saved_unsigned(files, pid, value, *, kind=2):
    width = 2 if kind == 9 else 4
    payload = value.to_bytes(width, "big")
    return {
        3: files[3],
        11: files[11] + slot((3 << 22) | 101, 242, pid, kind, len(files[12])),
        12: files[12] + payload + bytes([header_crc(payload) ^ 255]),
    }, len(files[12])


def changed_saved(files, offset, value, *, width=4):
    payload = value.to_bytes(width, "big")
    return {
        **files,
        12: files[12][:offset]
        + payload
        + bytes([header_crc(payload) ^ 255])
        + files[12][offset + width + 1 :],
    }


@pytest.mark.parametrize("property,value", [(15, 999999), (33, 1000001)])
@pytest.mark.parametrize("already", [False, True])
def test_saved_counter_ticks_remain_current_and_do_not_become_configuration_changes(
    tmp_path, property, value, already
):
    original, offset = saved_unsigned(observed_shape(), property, 77 if property == 15 else 90000)
    storage, service, query, before, files, _ = setup(tmp_path, files=original)
    if already:
        files = {**files, 3: NativeInputCompiler(original).app.source}
    files = changed_saved(files, offset, value)
    real_slot(files, 4, struct.pack(">f", 9.25))
    capture = retained(storage, files, identity=before["identity"])
    query |= {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
    unchanged = filesystem(storage.directory)
    report = service.prepare(query)
    assert report["already_recorded"] is already
    if already:
        assert report["proposal"] is None
    else:
        output, compiled = NativeInputCompiler(files).compile(report["proposal"]["edit"])
        assert compiled == report["inverse_compilation"]
        actual = MoiIdentity(output)
        record = actual.reader.records["controller/3_101"]
        assert actual.reader.scalar(record, property) == value
        assert actual.reader.scalar(record, 519) == 1
        assert actual.reader.scalar(actual.root, 900) == 9.25
        assert compiled["captured_counter_values"][str(property)] == value
        verify_input_preservation(files, {**files, 3: output}, report["proposal"]["edit"])
    assert filesystem(storage.directory) == unchanged


@pytest.mark.parametrize("property,before_value,after_value", [(931, 14, 15), (84, 1, 0)])
@pytest.mark.parametrize("already", [False, True])
def test_changed_saved_configuration_is_refused_under_unchanged_native_image(
    tmp_path, property, before_value, after_value, already
):
    original, offset = saved_unsigned(observed_shape(), property, before_value, kind=9)
    storage, service, query, before, files, _ = setup(tmp_path, files=original)
    if already:
        files = {**files, 3: NativeInputCompiler(original).app.source}
    current = changed_saved(files, offset, after_value, width=2)
    assert current[3] == files[3] and current[11] == files[11]
    capture = retained(storage, current, identity=before["identity"])
    with pytest.raises(ValueError, match="configuration changed"):
        service.prepare(
            query | {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
        )


@pytest.mark.parametrize(
    "property,value",
    [
        (4, CharacterString("On")),
        (46, CharacterString("Off")),
        (2390, CharacterString("Renamed input")),
        (28, CharacterString("Different description")),
        (931, Enumerated(15)),
        (84, Enumerated(0)),
        (31, CharacterString("UI IN3", _encoding=0)),
        (15, Unsigned(999999)),
        (33, Unsigned(1000001)),
    ],
    ids=[
        "active",
        "inactive",
        "name",
        "description",
        "states",
        "polarity",
        "encoding",
        "counter15",
        "counter33",
    ],
)
def test_changed_raw_application_is_refused_even_for_counter_only_changes(
    tmp_path, property, value
):
    storage, service, query, before, files, _ = setup(tmp_path)
    current = replaced(files, {property: encoded(value)})
    capture = retained(storage, current, identity=before["identity"])
    with pytest.raises(ValueError, match="application changed beyond"):
        service.prepare(
            query | {"capture_id": capture["id"], "snapshot_sha256": capture["evidence_sha256"]}
        )


@pytest.mark.parametrize("absent", [(15,), (33,), (84,), (15, 84), (33, 84)])
def test_optional_field_presence_remains_exact_without_defaults(tmp_path, absent):
    storage, service, query, _, files, _ = setup(
        tmp_path, files=without_optional(observed_shape(), absent)
    )
    report = service.prepare(query)
    output, _ = NativeInputCompiler(files).compile(report["proposal"]["edit"])
    before = NativeInputCompiler(files).app.reader.records["controller/3_101"]["properties"]
    after = MoiIdentity(output).reader.records["controller/3_101"]["properties"]
    assert before.keys() == after.keys()
    assert not set(absent).intersection(after)


@pytest.mark.parametrize("preservation", [None, [], "verified", True])
def test_malformed_sealed_preservation_is_a_local_rejection(tmp_path, preservation):
    _, service, query, *_ = setup(
        tmp_path, result_change=lambda result: result.update(preservation=preservation)
    )
    with pytest.raises(ValueError, match="complete native preservation"):
        service.prepare(query)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert client.post(BASE, headers=headers, json=query).status_code == 422


def test_configured_analog_parent_cannot_supply_binary_recovery(tmp_path):
    from .test_native_encoded_analog_recovery import setup as analog_setup

    storage, _, query, *_ = analog_setup(tmp_path)
    unchanged = filesystem(storage.directory)
    with pytest.raises(ValueError, match="configured binary"):
        NativeBinaryTerminalRecovery(NativeBackupRecords(storage)).prepare(query)
    assert filesystem(storage.directory) == unchanged


@pytest.mark.parametrize("unknown", [False, True])
async def test_owned_udp_parent_and_restarted_local_http_prepare_preserve_original_evidence(
    native_link, monkeypatch, unknown
):
    peer, service = binary_peer(native_link)
    peer.files, counter_offset = with_counter(peer.files)
    _, plan = await preview(
        native_link,
        terminal_edit(BinaryTerminalCompiler(NativeInputCompiler(peer.files))),
        "binary-recovery-parent",
    )
    if unknown:
        peer.mode = "drop-end"
    result = await service.apply_input(**apply(plan, "binary-recovery-parent"))
    assert result["result"]["status"] == ("unknown" if unknown else "verified"), result
    if unknown:
        peer.mode = "normal"
        reconciled = await service.reconcile(
            operation_id="binary-recovery-parent-readback", receipt_id=result["intent"]["id"]
        )
        assert reconciled["events"][-1]["detail"]["status"] == "verified"
    tick(peer, counter_offset, 999999)
    capture = await service.capture(**native_link[4], operation_id="capture-binary-recovery")
    request = {
        "receipt_id": result["intent"]["id"],
        "capture_id": capture["id"],
        "snapshot_sha256": capture["snapshot_evidence_sha256"],
    }
    events = list(peer.events)
    unchanged = filesystem(service.storage.directory)
    restarted = create_app(native_link[2].directory)

    def forbidden(*args, **kwargs):
        pytest.fail("Local binary recovery attempted field access or durable intent")

    for name in ("require", "connect", "_read", "disconnect", "release"):
        monkeypatch.setattr(restarted.state.bacnet, name, forbidden)
    monkeypatch.setattr(restarted.state.native_applications.storage, "intent", forbidden)
    with TestClient(restarted) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, headers=headers, json=request)
        assert response.status_code == 200, response.text
        report = response.json()
        assert report["proposal"]["edit"]["slot"] == 1
        assert report["inverse_compilation"]["captured_counter_values"]["15"] == 999999
        assert report["origin"]["verified_proof"]["kind"] == (
            "readback-event" if unknown else "result"
        )
        assert not client.get("/api/session").json()["field_network_open"]
        assert not restarted.state.native_applications.plans
    assert peer.events == events and filesystem(service.storage.directory) == unchanged
    assert service.storage.receipt(request["receipt_id"])["result"]["status"] == (
        "unknown" if unknown else "verified"
    )
