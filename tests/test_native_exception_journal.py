"""Exception journal retention, source binding and bounded storage admission."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from bms_tool import native_exception_write as module
from bms_tool.native_exception_write import PROFILE, ExceptionWriteJournal, seal
from bms_tool.native_schedule_library import encoded
from bms_tool.storage import Store


def body(number=1):
    return {
        "id": f"{number:032x}",
        "profile": PROFILE,
        "rules_sha256": module.RULES_SHA256,
        "target": {
            "address": "127.0.0.1:47808",
            "device": "device,42",
            "router": None,
            "dnet": None,
        },
        "object_id": "schedule,1",
        "property": "exception-schedule",
        "array_index": None,
        "operation_id": "authored_exceptions",
        "status": "not_sent",
        "dispatch_started": False,
        "may_have_applied": False,
        "protocol_status": "not_sent",
        "protocol_accepted": False,
        "readback": {"status": "not_attempted"},
        "review": {"authored": "immutable source binding"},
        "native_request": {"apdu_hex": "0000010f0c0440000119263e3f"},
    }


def test_intent_crash_projection_and_result_are_independent_immutable_evidence(tmp_path):
    store = Store(tmp_path)
    journal = ExceptionWriteJournal(store)
    original = body()
    digest = journal.intent(original)
    with store.connect() as db:
        raw = db.execute("SELECT intent FROM native_exception_writes").fetchone()[0]
    assert hashlib.sha256(raw).hexdigest() == digest
    unknown = json.loads(ExceptionWriteJournal(Store(tmp_path)).receipt(original["id"]))
    assert unknown["status"] == "unknown" and unknown["dispatch_started"] is None
    assert unknown["protocol_accepted"] is None and unknown["may_have_applied"]
    assert unknown["readback"]["status"] == "unknown"
    assert unknown["intent_snapshot"]["dispatch_started"] is False
    completed = {
        **original,
        "status": "unknown",
        "dispatch_started": True,
        "may_have_applied": True,
        "protocol_status": "unknown",
        "protocol_accepted": None,
        "intent_sha256": digest,
    }
    result = journal.result(completed)
    assert ExceptionWriteJournal(Store(tmp_path)).receipt(original["id"]) == result
    with pytest.raises(ValueError, match="immutable"):
        journal.result(completed)
    with store.connect() as db:
        assert db.execute("SELECT intent FROM native_exception_writes").fetchone()[0] == raw


@pytest.mark.parametrize(
    "key",
    [
        "target",
        "object_id",
        "property",
        "array_index",
        "review",
        "native_request",
        "rules_sha256",
        "operation_id",
    ],
)
def test_result_and_passive_read_refuse_resealed_context_substitution(tmp_path, key):
    store = Store(tmp_path)
    journal = ExceptionWriteJournal(store)
    original = body()
    journal.intent(original)
    changed = {**original, key: "substituted"}
    with pytest.raises(ValueError, match="original intent"):
        journal.result(changed)
    raw = journal.result(original)
    forged = json.loads(raw)
    forged[key] = "substituted"
    forged.pop("evidence_sha256")
    with store.connect() as db:
        db.execute("UPDATE native_exception_writes SET result=?", (encoded(seal(forged)),))
    with pytest.raises(ValueError, match="original intent"):
        journal.receipt(original["id"])


@pytest.mark.parametrize("missing_intent", [False, True])
def test_changed_or_missing_retained_intent_never_becomes_a_complete_receipt(
    tmp_path, missing_intent
):
    store = Store(tmp_path)
    journal = ExceptionWriteJournal(store)
    original = body()
    journal.intent(original)
    journal.result(original)
    with store.connect() as db:
        db.execute(
            "UPDATE native_exception_writes SET intent=?", (None if missing_intent else b"{}",)
        )
    with pytest.raises(ValueError):
        journal.receipt(original["id"])
    assert len(journal.status()["records"]) == 1


def test_reserved_result_capacity_is_shared_and_never_evicts_original_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "JOURNAL_BYTES", 3 * module.RECORD_BYTES)
    store = Store(tmp_path)
    one = ExceptionWriteJournal(store)
    two = ExceptionWriteJournal(Store(tmp_path))
    one.intent(body(1))
    two.intent(body(2))
    before = {n: one.receipt(f"{n:032x}") for n in (1, 2)}
    with pytest.raises(ValueError, match="capacity"):
        one.intent(body(3))
    assert {n: two.receipt(f"{n:032x}") for n in (1, 2)} == before
    one.result(body(1))
    two.intent(body(3))
    assert len(one.status()["records"]) == 3 and one.status()["automatic_eviction"] is False


def test_competing_capacity_claims_keep_one_slot_without_eviction(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "JOURNAL_RECORDS", 1)
    store = Store(tmp_path)
    ExceptionWriteJournal(store)

    def write(number):
        try:
            ExceptionWriteJournal(Store(tmp_path)).intent(body(number))
            return True
        except ValueError as error:
            assert "capacity" in str(error)
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, (1, 2)))
    assert sorted(results) == [False, True]
    assert len(ExceptionWriteJournal(store).status()["records"]) == 1


@pytest.mark.parametrize(
    "raw", [b"{}", b"[]", b"not json", b'{"id":1,"id":1}', "text is not a BLOB"]
)
def test_corrupt_original_records_are_retained_and_refused(tmp_path, raw):
    store = Store(tmp_path)
    journal = ExceptionWriteJournal(store)
    with store.connect() as db:
        db.execute(
            "INSERT INTO native_exception_writes VALUES(?,?,NULL,?)", ("1" * 32, raw, "authored")
        )
    with pytest.raises(ValueError):
        journal.receipt("1" * 32)
    assert len(journal.status()["records"]) == 1
    with store.connect() as db:
        assert db.execute("SELECT intent FROM native_exception_writes").fetchone()[0] == raw


def test_result_without_original_dispatch_intent_is_not_published(tmp_path):
    store = Store(tmp_path)
    journal = ExceptionWriteJournal(store)
    with pytest.raises(ValueError, match="original intent"):
        journal.result({**body(), "dispatch_started": True})
    assert journal.status()["records"] == []
