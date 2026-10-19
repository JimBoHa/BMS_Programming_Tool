"""Revision checksums retain their original meaning across hash-format migration."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from bms_tool.models import Program, canonical
from bms_tool.storage import (
    CANONICAL_HASH_FORMAT,
    LEGACY_HASH_FORMAT,
    RevisionIntegrityError,
    Store,
)


def legacy_database(directory):
    program = Program(
        id="legacy-project",
        name="Legacy project",
        revision=1,
        metadata={"z": {"second": 2, "first": 1}, "a": 3},
    )
    content = program.model_dump_json()
    digest = hashlib.sha256(content.encode()).hexdigest()
    created = "2026-01-01T00:00:00+00:00"
    detail = json.dumps({"id": program.id, "revision": 1, "sha256": digest}, sort_keys=True)
    previous_hash = "0" * 64
    entry_hash = hashlib.sha256(
        (previous_hash + created + "project.save" + detail).encode()
    ).hexdigest()
    revision = (program.id, 1, program.name, content, digest, created)
    audit = (1, created, "project.save", detail, previous_hash, entry_hash)
    with sqlite3.connect(directory / "studio.sqlite3") as db:
        db.execute(
            "CREATE TABLE revisions(id TEXT,revision INTEGER,name TEXT,content TEXT,sha256 TEXT,"
            "created TEXT,PRIMARY KEY(id,revision))"
        )
        db.execute(
            "CREATE TABLE audit(sequence INTEGER PRIMARY KEY,created TEXT,operation TEXT,detail TEXT,"
            "previous_hash TEXT,entry_hash TEXT)"
        )
        db.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?)", revision)
        db.execute("INSERT INTO audit VALUES(?,?,?,?,?,?)", audit)
    return program, revision, audit


def raw_revision(store, revision=1):
    with sqlite3.connect(store.db) as db:
        return db.execute(
            "SELECT id,revision,name,content,sha256,created,hash_format FROM revisions WHERE revision=?",
            (revision,),
        ).fetchone()


def test_migration_preserves_legacy_content_hash_and_audit_chain_then_saves_new_format(tmp_path):
    old, original, old_audit = legacy_database(tmp_path)
    assert original[4] != old.digest()
    store = Store(tmp_path)
    assert raw_revision(store) == (*original, LEGACY_HASH_FORMAT)
    assert store.load(old.id).model_dump() == old.model_dump()
    assert store.versions(old.id)[0]["hash_format"] == LEGACY_HASH_FORMAT
    with sqlite3.connect(store.db) as db:
        assert db.execute("SELECT * FROM audit").fetchone() == old_audit
    edited = store.load(old.id)
    edited.description = "Saved after canonical hash migration"
    saved = store.save(edited, expected_revision=1)
    assert saved.revision == 2
    current = raw_revision(store, 2)
    assert current[4] == hashlib.sha256(canonical(saved)).hexdigest()
    assert current[6] == CANONICAL_HASH_FORMAT
    # Saving a new revision must not silently migrate the old checksum or content.
    assert raw_revision(store) == (*original, LEGACY_HASH_FORMAT)
    audit = store.audit()
    assert audit[-1] == dict(
        zip(
            ("sequence", "created", "operation", "detail", "previous_hash", "entry_hash"),
            old_audit,
            strict=True,
        )
    )
    assert audit[0]["previous_hash"] == old_audit[-1]
    assert json.loads(audit[0]["detail"])["hash_format"] == CANONICAL_HASH_FORMAT
    reopened = Store(tmp_path)
    assert reopened.load(old.id, 1).model_dump() == old.model_dump()
    assert reopened.load(old.id).model_dump() == saved.model_dump()
    assert [row["hash_format"] for row in reopened.versions(old.id)] == [
        CANONICAL_HASH_FORMAT,
        LEGACY_HASH_FORMAT,
    ]


def test_new_revision_hash_and_program_digest_ignore_nested_metadata_key_order(tmp_path):
    first = Program(id="ordered", metadata={"z": {"b": 2, "a": 1}, "a": 3})
    second = Program(id="ordered", metadata={"a": 3, "z": {"a": 1, "b": 2}})
    assert first.model_dump_json() != second.model_dump_json()
    assert first.digest() == second.digest()
    left, right = Store(tmp_path / "left"), Store(tmp_path / "right")
    saved_left, saved_right = left.save(first), right.save(second)
    assert saved_left.digest() == saved_right.digest()
    assert raw_revision(left)[4] == raw_revision(right)[4]
    assert raw_revision(left)[6] == raw_revision(right)[6] == CANONICAL_HASH_FORMAT
    # Whitespace or object key ordering does not alter canonical-json/1 meaning.
    reordered = json.dumps(json.loads(raw_revision(left)[3]), sort_keys=True, indent=4)
    with sqlite3.connect(left.db) as db:
        db.execute("UPDATE revisions SET content=?", (reordered,))
    assert left.load(first.id).digest() == saved_right.digest()


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize(
    "mutation", ["content", "hash", "invalid-json", "invalid-program", "format"]
)
def test_tampered_or_unknown_revision_format_is_rejected(tmp_path, legacy, mutation):
    if legacy:
        program, _, _ = legacy_database(tmp_path)
        store = Store(tmp_path)
    else:
        store = Store(tmp_path)
        program = store.save(Program(id="new-project", name="New project"))
    with sqlite3.connect(store.db) as db:
        if mutation == "content":
            content = json.loads(raw_revision(store)[3])
            content["description"] = "Unexpected changed content"
            db.execute("UPDATE revisions SET content=?", (json.dumps(content),))
        elif mutation == "hash":
            db.execute("UPDATE revisions SET sha256=?", ("0" * 64,))
        elif mutation == "invalid-json":
            db.execute("UPDATE revisions SET content=?", ("{not JSON",))
        elif mutation == "invalid-program":
            db.execute("UPDATE revisions SET content=?", ('{"schema_version":999}',))
        else:
            db.execute("UPDATE revisions SET hash_format=?", ("future-unknown/9",))
    message = "hash format" if mutation == "format" else "invalid|integrity verification"
    with pytest.raises(RevisionIntegrityError, match=message):
        Store(tmp_path).load(program.id)


def test_legacy_checksum_still_covers_exact_stored_bytes(tmp_path):
    program, original, _ = legacy_database(tmp_path)
    store = Store(tmp_path)
    reformatted = json.dumps(json.loads(original[3]), indent=2)
    with sqlite3.connect(store.db) as db:
        db.execute("UPDATE revisions SET content=?", (reformatted,))
    with pytest.raises(RevisionIntegrityError, match="hash mismatch"):
        store.load(program.id)


@pytest.mark.parametrize("field,value", [("id", "wrong"), ("revision", 9), ("name", "Wrong name")])
def test_stored_revision_identity_is_checked_independently_of_content_checksum(
    tmp_path, field, value
):
    store = Store(tmp_path)
    program = store.save(Program(id="identity", name="Stored identity"))
    with sqlite3.connect(store.db) as db:
        db.execute(f"UPDATE revisions SET {field}=?", (value,))
    identifier = value if field == "id" else program.id
    with pytest.raises(RevisionIntegrityError, match="identity"):
        store.load(identifier)


def test_concurrent_initialization_migrates_legacy_schema_once_without_rewriting_evidence(tmp_path):
    program, original, audit = legacy_database(tmp_path)
    barrier = Barrier(6)

    def initialize(_):
        barrier.wait(timeout=10)
        store = Store(tmp_path)
        return store.load(program.id).digest(), store.versions(program.id)[0]["hash_format"]

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(initialize, range(6)))
    assert results == [(program.digest(), LEGACY_HASH_FORMAT)] * 6
    store = Store(tmp_path)
    assert raw_revision(store) == (*original, LEGACY_HASH_FORMAT)
    with sqlite3.connect(store.db) as db:
        assert [r[1] for r in db.execute("PRAGMA table_info(revisions)")].count("hash_format") == 1
        assert db.execute("SELECT * FROM audit").fetchall() == [audit]
