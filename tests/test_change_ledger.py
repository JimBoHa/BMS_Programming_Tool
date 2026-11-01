"""Bounded local evidence, original routes, uncertainty and zero field dispatch."""

import copy
import json
from types import SimpleNamespace

import pytest
from bms_tool import change_ledger
from bms_tool.app import create_app
from bms_tool.change_ledger import AUDIT_BYTES, SOURCES, WINDOW, LedgerQuery
from bms_tool.device_instance import PROFILE as INSTANCE_PROFILE
from bms_tool.native_schedule_write import PROFILE as SCHEDULE_PROFILE
from fastapi.testclient import TestClient
from pydantic import ValidationError

STAMP = "2026-01-02T03:04:05+00:00"
TARGET = {"address": "1101:3", "router": "127.0.0.1:47809", "dnet": 1101}


@pytest.fixture
def application(tmp_path, monkeypatch):
    app = create_app(tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("The local ledger attempted a field operation")

    for name in ("require", "_read", "connect", "disconnect", "release"):
        monkeypatch.setattr(app.state.bacnet, name, forbidden)
    return app


async def query(app, **options):
    return await app.state.change_ledger.read(LedgerQuery(**options))


def native(app, number=1, **extra):
    return app.state.native_applications.storage.intent(
        {
            "id": f"{number:032x}",
            "target": {**TARGET, "address": f"1101:{number}"},
            "identity": {"device": "device,123"},
            "old_instance": 123,
            "new_instance": 124,
            "connector_config": {"local_address": "127.0.0.1:47810", **TARGET},
            **extra,
        }
    )


def instance(app, number=1, **extra):
    row = {
        "id": f"{number:032x}",
        "profile": INSTANCE_PROFILE,
        "target": TARGET.copy(),
        "identity": {"device": "device,123"},
        "created_at": STAMP,
        "status": "unknown",
        "may_have_applied": True,
        "readback": {"status": "unknown"},
        "old_instance": 123,
        "new_instance": 124,
        **extra,
    }
    app.state.device_instances.journal.result(row)
    return row


def schedule(app, number=1, **extra):
    row = {
        "id": f"{number:032x}",
        "profile": SCHEDULE_PROFILE,
        "target": {**TARGET, "device": "device,123"},
        "created_at": STAMP,
        "status": "unknown",
        "may_have_applied": True,
        "readback": {"status": "unknown"},
        "object_id": "schedule,4",
        **extra,
    }
    return row, app.state.schedule_writes.journal.result(row)


async def test_empty_offline_query_is_readonly_and_does_not_append_audit(application):
    store = application.state.store
    before = store.audit()
    report = await query(application)
    assert report["rows"] == report["errors"] == []
    assert report["read_only"] and report["field_requests"] == 0
    assert report["next_cursor"] is None and store.audit() == before
    assert {r["source"] for r in report["coverage"]} == set(SOURCES)


async def test_families_keep_own_evidence_and_original_targets(application):
    app = application
    app.state.store.record("project.save", {"id": "local-one", "revision": 2})
    n = native(app)
    instance(app)
    schedule(app)
    app.state.bbmd_admin.journal.save(
        {
            "id": "bbma-" + "a" * 24,
            "created_at": STAMP,
            "endpoint": "127.0.0.1:47811",
            "operation": "write-bdt",
            "state": "complete",
            "dispatch_possible": True,
            "outcome": "desired-state-observed",
            "authorship_proven": False,
        }
    )
    app.state.event_ack._receipts["event-one"] = {
        "id": "event-one",
        "status": "unknown",
        "may_have_applied": True,
        "target": {**TARGET, "device": "device,123"},
        "started_at": STAMP,
    }
    app.state.temco_transfer.operations["temco-one"] = {
        "state": "complete",
        "target": {"address": "127.0.0.1:47812"},
        "updated": STAMP,
    }
    app.state.bacnet.commands["owned-one"] = {
        "address": "1101:3",
        "object_id": "analog-output,1",
        "status": "active",
        "config": {"router": TARGET["router"], "dnet": TARGET["dnet"]},
    }
    before = app.state.store.audit()
    report = await query(app)
    assert not report["errors"]
    rows = {r["source"]: r for r in report["rows"]}
    assert set(rows) == set(SOURCES) and app.state.store.audit() == before
    assert rows["native"]["target"] == {**n["target"], "device": "device,123"}
    assert all(rows[s]["pending"] for s in ("native", "instance", "schedule", "event", "command"))
    assert rows["bbmd"]["state"] == "desired-state-observed"
    assert rows["bbmd"]["outcome"] == rows["temco"]["outcome"] == "verified"
    assert rows["event"]["session_scoped"] and not rows["command"]["session_scoped"]
    assert rows["audit"]["kind"] == "audit" and rows["command"]["kind"] == "ownership"


async def test_instance_readback_resolves_display_without_rewriting_attempt(application):
    app = application
    original = instance(app)
    assert (await query(app, source="instance"))["rows"][0]["pending"]
    app.state.device_instances.journal.readback(
        original["id"],
        {
            "profile": INSTANCE_PROFILE,
            "readback": {"status": "verified_new"},
        },
    )
    row = (await query(app, source="instance"))["rows"][0]
    assert row["outcome"] == "verified" and not row["pending"]
    assert (
        app.state.device_instances.journal.receipt(original["id"])["attempt"]["status"] == "unknown"
    )


async def test_native_late_readback_resolves_original_uncertainty(application):
    app = application
    intent = native(app, change_kind="name", old_name="Old", new_name="New")
    assert (await query(app, source="native"))["rows"][0]["pending"]
    app.state.native_applications.storage.resolve(intent["id"], {"status": "verified"})
    row = (await query(app, source="native"))["rows"][0]
    assert row["outcome"] == "verified" and not row["pending"] and "name" in row["label"]


@pytest.mark.parametrize(
    "kind,label,edit_key,edit,expected_object",
    [
        (
            "signal-default",
            "Native Real default transfer",
            "default_edit",
            {"ref": "controller/526_1"},
            "controller/526_1",
        ),
        (
            "boolean-default",
            "Native Boolean default transfer",
            "default_edit",
            {"ref": "controller/524_1"},
            "controller/524_1",
        ),
        (
            "wire-source",
            "Native wire source transfer",
            "wire_edit",
            {"diagram_ref": "controller/575_1", "wire_index": 0},
            "controller/575_1",
        ),
    ],
)
async def test_current_native_edit_profiles_keep_their_actual_kind_and_object(
    application, kind, label, edit_key, edit, expected_object
):
    intent = native(application, change_kind=kind, new_instance=123, **{edit_key: edit})
    before = application.state.native_applications.storage.receipt(intent["id"])
    (row,) = (await query(application, source="native"))["rows"]
    assert row["label"] == label
    assert row["native_change_kind"] == kind and row["object"] == expected_object
    assert row["pending"] and row["target"] == {**intent["target"], "device": "device,123"}
    assert application.state.native_applications.storage.receipt(intent["id"]) == before


@pytest.mark.parametrize("kind", [None, "future-compiler", 7, ["name"], {"kind": "instance"}])
async def test_unknown_native_kind_never_becomes_an_instance_change(application, kind):
    native(application, change_kind=kind)
    (row,) = (await query(application, source="native"))["rows"]
    assert row["native_change_kind"] == "unsupported"
    assert row["label"] == "Native application transfer (unsupported operation)"


@pytest.mark.parametrize("kind", ["instance", "name"])
async def test_existing_native_identity_kinds_retain_their_labels(application, kind):
    native(application, change_kind=kind)
    (row,) = (await query(application, source="native"))["rows"]
    assert row["native_change_kind"] == kind
    assert row["label"] == f"Native controller {kind} change"


@pytest.mark.parametrize("original_possible", [None, False, True])
async def test_native_dispatch_retains_original_attempt_facts_after_later_readback(
    application, original_possible
):
    storage = application.state.native_applications.storage
    intent = native(application, change_kind="wire-source", new_instance=123)
    if original_possible is not None:
        storage.finish(
            intent["id"],
            {
                "intent_sha256": intent["evidence_sha256"],
                "status": "unknown" if original_possible else "preflight-failed",
                "may_have_applied": original_possible,
            },
        )
    storage.resolve(intent["id"], {"status": "verified", "may_have_applied": not original_possible})
    before = storage.receipt(intent["id"])
    (row,) = (await query(application, source="native"))["rows"]
    assert row["dispatch"] == ("not entered" if original_possible is False else "possible")
    assert row["state"] == "verified" and row["outcome"] == "verified" and not row["pending"]
    assert storage.receipt(intent["id"]) == before


@pytest.mark.parametrize(
    "outcome,attention",
    [
        ("unknown", True),
        ("different-state-observed", True),
        ("not-dispatched", False),
        ("desired-state-observed", False),
    ],
)
async def test_bbmd_observation_uses_actual_outcome_vocabulary(application, outcome, attention):
    application.state.bbmd_admin.journal.save(
        {
            "id": "bbma-" + "b" * 24,
            "created_at": STAMP,
            "endpoint": "127.0.0.1:47811",
            "operation": "write-bdt",
            "state": "complete",
            "dispatch_possible": outcome != "not-dispatched",
            "outcome": outcome,
        }
    )
    row = (await query(application, source="bbmd"))["rows"][0]
    assert row["pending"] is attention and row["state"] == outcome


async def test_filters_preserve_duplicate_device_instances_by_exact_route(application):
    app = application
    for sequence, router in enumerate(("127.0.0.1:47809", "127.0.0.1:47819")):
        instance(app, sequence + 1, target={**TARGET, "router": router})
    report = await query(app, source="instance", selected_target={**TARGET, "device": "device,124"})
    assert len(report["rows"]) == 1
    assert report["rows"][0]["target"]["router"] == TARGET["router"]
    # An instance change must remain findable by original station after its ID changes.
    assert report["rows"][0]["target"]["device"] == "device,123"
    assert not (
        await query(app, source="instance", selected_target={**TARGET, "router": "127.0.0.1:47820"})
    )["rows"]


async def test_direct_station_addresses_normalize_default_udp_port(application):
    instance(application, target={"address": "127.0.0.1", "router": None, "dnet": None})
    report = await query(
        application, source="instance", selected_target={"address": "127.0.0.1:47808"}
    )
    assert len(report["rows"]) == 1


async def test_serial_mac_filter_requires_exact_retained_interface(application):
    app = application
    config = {"transport": "mstp", "port": "/dev/authored-trunk-a", "mac": 120, "baudrate": 38400}
    for key, port in (("one", config["port"]), ("two", "/dev/authored-trunk-b")):
        app.state.bacnet.commands[key] = {
            "address": "3",
            "status": "active",
            "config": {**config, "port": port},
        }
    assert len((await query(app, source="command"))["rows"]) == 2
    assert not (await query(app, source="command", selected_target={"address": "3"}))["rows"]
    result = await query(
        app, source="command", selected_target={"address": "3", "interface_key": json.dumps(config)}
    )
    assert len(result["rows"]) == 1 and result["rows"][0]["id"] == "one"
    assert config["port"] in result["rows"][0]["interface_label"]


async def test_older_windows_do_not_restart_exhausted_sources_or_repeat_rows(application):
    app = application
    app.state.store.record("project.save", {"id": "one-audit"})
    for n in range(1, WINDOW + 3):
        native(app, n)
        app.state.event_ack._receipts[f"event-{n:03}"] = {"status": "unknown", "created_at": STAMP}
    first = await query(app)
    second = await query(app, **first["next_cursor"])
    assert first["next_cursor"]["exhausted"] == [
        "audit",
        "bbmd",
        "command",
        "instance",
        "schedule",
        "temco",
    ]
    assert len(first["rows"]) == 2 * WINDOW + 1 and len(second["rows"]) == 4
    assert not {r["key"] for r in first["rows"]} & {r["key"] for r in second["rows"]}
    assert second["next_cursor"] is None


async def test_empty_filtered_window_still_exposes_older_matches(application):
    app = application
    for n in range(1, WINDOW + 2):
        app.state.store.record("project.save", {"id": "needle" if n == 1 else "ordinary"})
    first = await query(app, source="audit", text="needle")
    assert not first["rows"] and first["next_cursor"]
    second = await query(app, source="audit", text="needle", **first["next_cursor"])
    assert len(second["rows"]) == 1 and second["next_cursor"] is None
    assert not (await query(app, source="audit", outcome="attention"))["rows"]


async def test_corrupt_source_record_is_visible_error_and_cannot_become_verified(application):
    app = application
    native(app)
    with app.state.store.connect() as db:
        db.execute("UPDATE application_transfers SET intent=?", (b'{"status":"verified"}',))
    app.state.store.record("project.save", {"id": "unaffected"})
    report = await query(app)
    assert [r["source"] for r in report["rows"]] == ["audit"]
    assert any(e["source"] == "native" for e in report["errors"])


async def test_unavailable_optional_bbmd_journal_does_not_hide_other_sources(application):
    application.state.change_ledger.bbmd = None
    application.state.store.record("project.save", {"id": "unaffected"})
    report = await query(application)
    assert len(report["rows"]) == 1 and report["errors"][0]["source"] == "bbmd"


async def test_audit_integrity_bound_and_detail_redaction(application):
    app = application
    app.state.store.record(
        "project.save",
        {
            "id": "project",
            "password": "secret-example",
            "nested": {"apply_token": "not-a-plan", "count": 3},
        },
    )
    row = (await query(app, source="audit"))["rows"][0]
    detail = await app.state.change_ledger.detail("audit", row["id"])
    assert "secret-example" not in json.dumps(detail) and "not-a-plan" not in json.dumps(detail)
    assert detail["record"]["detail"]["nested"]["count"] == 3
    with app.state.store.connect() as db:
        db.execute("UPDATE audit SET detail=?", ('{"id":"tampered"}',))
    report = await query(app, source="audit")
    assert not report["rows"] and report["errors"]
    with pytest.raises(ValueError, match="integrity"):
        await app.state.change_ledger.detail("audit", row["id"])
    app.state.store.record("caf.patch", {"padding": "x" * AUDIT_BYTES})
    report = await query(app, source="audit")
    assert not report["rows"] and len(report["errors"]) == 2


async def test_memory_snapshot_is_detached_before_disk_await(application):
    app = application
    app.state.event_ack._receipts["event-one"] = {"target": TARGET.copy(), "status": "unknown"}
    snapshot = app.state.change_ledger.memory(LedgerQuery())
    app.state.event_ack._receipts["event-one"]["target"]["router"] = "127.0.0.1:47999"
    assert snapshot["event"]["event-one"]["target"] == TARGET


def test_read_budget_retains_unread_source_positions(application, monkeypatch):
    app = application
    for n in range(3):
        app.state.store.record("project.save", {"id": str(n)})
    service = app.state.change_ledger
    clock = {"now": 0, "advance": True}
    monkeypatch.setattr(change_ledger, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    original = service._load

    def advance_after_one(*args):
        record = original(*args)
        if clock["advance"]:
            clock.update(now=6, advance=False)
        return record

    monkeypatch.setattr(service, "_load", advance_after_one)
    request = LedgerQuery(source="audit")
    first = service.query(request, service.memory(request))
    assert len(first["rows"]) == 1 and first["errors"]
    assert first["next_cursor"] == {"before": {"audit": "3"}, "exhausted": []}
    clock["now"] = 0
    request = LedgerQuery(source="audit", **first["next_cursor"])
    second = service.query(request, service.memory(request))
    assert len(second["rows"]) == 2 and second["next_cursor"] is None
    assert not {r["id"] for r in first["rows"]} & {r["id"] for r in second["rows"]}


async def test_durable_event_uncertainty_survives_session_receipt_retirement(application):
    app = application
    app.state.store.record(
        "bacnet.event_ack.result",
        {
            "id": "retired-session",
            "target": TARGET.copy(),
            "status": "unknown",
            "may_have_applied": True,
        },
    )
    report = await query(app, source="audit", outcome="attention")
    assert len(report["rows"]) == 1 and report["rows"][0]["state"] == "unknown"
    assert report["rows"][0]["kind"] == "audit"
    detail = await app.state.change_ledger.detail("audit", report["rows"][0]["id"])
    assert detail["record"]["detail"]["id"] == "retired-session"


async def test_non_change_audit_events_are_outside_ledger_scope(application):
    app = application
    app.state.store.record("bacnet.read", {"password": "not-returned"})
    assert not (await query(app, source="audit"))["rows"]
    with pytest.raises(ValueError, match="outside"):
        await app.state.change_ledger.detail("audit", "1")


@pytest.mark.parametrize(
    "body",
    [
        {"source": "unknown"},
        {"before": {"audit": "-1"}},
        {"before": {"native": "1 OR 1=1"}},
        {"before": {"command": "../escape"}},
        {"before": {"audit": "1"}, "exhausted": ["audit"]},
        {"exhausted": ["audit", "audit"]},
        {"text": "x\n"},
        {"text": "x" * 201},
        {"selected_target": {"address": "a", "dnet": True}},
        {"selected_target": {"address": "3", "interface_key": "not-json"}},
        {"selected_target": {"address": "3", "interface_key": '{"nested":{"port":"x"}}'}},
    ],
)
def test_query_admission_is_bounded(body):
    with pytest.raises(ValidationError):
        LedgerQuery(**body)


def test_local_http_admission_and_original_receipt_bytes(application):
    row, raw = schedule(application, status="verified", may_have_applied=True, value=-0.0)
    # No lifespan needed: this test is entirely offline and does not open adapters.
    client = TestClient(application)
    assert client.post("/api/changes/query", json={}).status_code == 403
    headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
    result = client.post("/api/changes/query", json={"source": "schedule"}, headers=headers)
    assert result.status_code == 200, result.text
    item = result.json()["rows"][0]
    assert item["outcome"] == "verified"
    exported = client.get("/api" + item["detail_path"])
    assert exported.content == raw and b'"value":-0.0' in raw
    assert client.get("/api/changes/records/schedule/" + row["id"]).status_code == 422
    before = copy.deepcopy(application.state.bacnet.commands)
    assert (
        client.post("/api/changes/query", json={"text": "anything"}, headers=headers).status_code
        == 200
    )
    assert application.state.bacnet.commands == before
