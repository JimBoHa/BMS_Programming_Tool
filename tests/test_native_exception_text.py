"""Restore unfinished raw fields with exact source ownership and no native authority."""

import asyncio
import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_exception_text import (
    DOCUMENT_PROFILE,
    IMPORT_PROFILE,
    MAX_DOCUMENT,
    NativeExceptionText,
)
from bms_tool.native_schedule_library import encoded
from fastapi.testclient import TestClient

from .test_native_schedule_library import acquire, saved

BASE = "/api/bacnet/schedules/library/exceptions/unfinished/import"


def document(capture):
    return {
        "profile": DOCUMENT_PROFILE,
        "field_authority": False,
        "source": [capture["id"], "schedule,1"],
        "buffer": {
            "rows": [
                {
                    "key": "event-1",
                    "kind": "calendarReference",
                    "date": ["20", "13", "32", "?"],
                    "start": ["*", "", "9", "00"],
                    "end": ["", "*", "-", "7"],
                    "fields": ["", "*", "9"],
                    "reference": "calendar,",
                    "priority": "-",
                    "transitions": [
                        {
                            "key": "time-1",
                            "time": ["0", "-", "2e", ""],
                            "native_type": "Real",
                            "value_text": "2e-",
                            "string_json": '"\\u',
                        }
                    ],
                }
            ],
            "imported": {"filename": "earlier.json", "review_id": "a" * 64},
        },
    }


@pytest.fixture(scope="module")
def raw_source_bytes(tmp_path_factory):
    report, _, _ = asyncio.run(acquire(tmp_path_factory.mktemp("raw-exception-source")))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


@pytest.fixture
def parts(tmp_path, raw_source_bytes):
    library, capture = saved(tmp_path, raw_source_bytes)
    return library, NativeExceptionText(library), document(capture)


def test_raw_invalid_fields_are_exact_deep_copies_without_review_or_capture_mutation(parts):
    library, service, body = parts
    originals = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
    raw = json.dumps(body, ensure_ascii=False, indent=2).encode()
    result = service.import_document(raw)
    assert result["profile"] == IMPORT_PROFILE and result["document_profile"] == DOCUMENT_PROFILE
    assert result["buffer"] == body["buffer"] and result["source"] == body["source"]
    assert result["file_sha256"] == hashlib.sha256(raw).hexdigest()
    assert all(
        result[key] is False
        for key in (
            "field_authority",
            "controller_queries",
            "capture_mutations",
            "native_review_created",
        )
    )
    assert not library.reviews
    result["buffer"]["rows"][0]["priority"] = "1"
    assert service.import_document(raw)["buffer"]["rows"][0]["priority"] == "-"
    assert {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()} == originals


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "authority",
        "numeric_false",
        "unknown_root",
        "source_shape",
        "unknown_source",
        "foreign_object",
        "source_type",
        "unknown_buffer",
        "bad_rows",
        "event_kind",
        "missing_field",
        "wrong_field_type",
        "wrong_field_length",
        "priority_limit",
        "reference_limit",
        "time_shape",
        "time_limit",
        "value_limit",
        "String_limit",
        "native_type",
        "key_empty",
        "key_duplicate",
        "time_key_duplicate",
        "event_count",
        "time_count",
        "metadata",
        "raw_metadata",
    ],
)
def test_unknown_or_oversized_shapes_refuse_without_changing_source(parts, case):
    library, service, body = parts
    row = body["buffer"]["rows"][0]
    time = row["transitions"][0]
    if case == "profile":
        body["profile"] = "native-schedule-exception-draft/1"
    elif case == "authority":
        body["field_authority"] = True
    elif case == "numeric_false":
        body["field_authority"] = 0
    elif case == "unknown_root":
        body["token"] = "a" * 32
    elif case == "source_shape":
        body["source"].append("extra")
    elif case == "unknown_source":
        body["source"][0] = "f" * 64
    elif case == "foreign_object":
        body["source"][1] = "calendar,1"
    elif case == "source_type":
        body["source"][1] = 17
    elif case == "unknown_buffer":
        body["buffer"]["can_apply"] = True
    elif case == "bad_rows":
        body["buffer"]["rows"] = {}
    elif case == "event_kind":
        row["kind"] = "file"
    elif case == "missing_field":
        row.pop("date")
    elif case == "wrong_field_type":
        row["date"][0] = 20
    elif case == "wrong_field_length":
        row["date"] = ["20"]
    elif case == "priority_limit":
        row["priority"] = "123"
    elif case == "reference_limit":
        row["reference"] = "x" * 81
    elif case == "time_shape":
        time["time"] = ["0"]
    elif case == "time_limit":
        time["time"][0] = "123"
    elif case == "value_limit":
        time["value_text"] = "🌡" * 129
    elif case == "String_limit":
        time["string_json"] = "🌡" * 770
    elif case == "native_type":
        time["native_type"] = "CharacterString"
    elif case == "key_empty":
        row["key"] = ""
    elif case == "key_duplicate":
        body["buffer"]["rows"].append(copy.deepcopy(row))
    elif case == "time_key_duplicate":
        row["transitions"].append(copy.deepcopy(time))
    elif case == "event_count":
        body["buffer"]["rows"] *= 33
    elif case == "time_count":
        row["transitions"] *= 33
    elif case == "metadata":
        body["buffer"]["imported"]["review_id"] = "not a digest"
    elif case == "raw_metadata":
        body["buffer"]["rawImported"] = {
            "filename": "raw.json",
            "file_sha256": "f" * 64,
            "token": "hidden",
        }
    with pytest.raises(ValueError):
        service.import_document(encoded(body))
    assert not library.reviews


@pytest.mark.parametrize(
    "raw",
    [
        b'{"profile":1,"profile":1}',
        b"[]",
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":"\xff"}',
        b'{"x":"\\ud800"}',
        b"[" * 66 + b"0" + b"]" * 66,
    ],
)
def test_duplicate_invalid_UTF8_Unicode_and_structure_refuse(parts, raw):
    with pytest.raises(ValueError):
        parts[1].import_document(raw)


@pytest.mark.parametrize("kind", ["date", "dateRange", "weekNDay", "calendarReference"])
def test_each_raw_period_and_null_keeps_inactive_numeric_and_string_work(parts, kind):
    _, service, body = parts
    row = body["buffer"]["rows"][0]
    row["kind"] = kind
    row["transitions"][0]["native_type"] = "Null"
    row["transitions"][0]["value_text"] = "1e-"
    row["transitions"][0]["string_json"] = '"\\u'
    body["buffer"]["rawImported"] = {"filename": "raw.json", "file_sha256": "b" * 64}
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]


def test_empty_buffer_remains_explicit_and_oversized_input_is_refused(parts):
    _, service, body = parts
    body["buffer"]["rows"] = []
    body["buffer"]["imported"] = None
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]
    with pytest.raises(ValueError, match="byte bound"):
        service.import_document(b" " * (MAX_DOCUMENT + 1))


def test_actual_local_route_requires_token_and_retains_original_source(tmp_path, raw_source_bytes):
    with TestClient(create_app(tmp_path)) as client:
        library = client.app.state.schedule_library
        capture = library._store(raw_source_bytes, "imported")
        body = document(capture)
        raw = encoded(body)
        assert (
            client.post(BASE, files={"file": ("raw.json", raw, "application/json")}).status_code
            == 403
        )
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(
            BASE, headers=headers, files={"file": ("raw.json", raw, "application/json")}
        )
        assert response.status_code == 200, response.text
        assert response.json()["buffer"] == body["buffer"]
        assert not client.app.state.bacnet.status()["connected"]
        assert library.source(capture["id"]) == raw_source_bytes and not library.reviews
        assert (
            client.post(
                BASE, headers=headers, files={"file": ("bad.json", b"{}", "application/json")}
            ).status_code
            == 422
        )


def test_input_file_budget_is_separate_from_unchanged_workspace_budget(parts):
    _, service, body = parts
    seed = body["buffer"]["rows"][0]
    seed["transitions"][0]["string_json"] = "x" * 1000
    seed["transitions"][0]["value_text"] = "y" * 256
    rows = []
    for i in range(32):
        row = copy.deepcopy(seed)
        row["key"] = f"row-{i}"
        row["transitions"] = [
            {**copy.deepcopy(seed["transitions"][0]), "key": f"time-{i}-{j}"} for j in range(32)
        ]
        rows.append(row)
    body["buffer"]["rows"] = rows
    raw = json.dumps(body, indent=2, ensure_ascii=False).encode()
    assert 512 * 1024 < len(raw) < MAX_DOCUMENT
    assert service.import_document(raw)["buffer"] == body["buffer"]
    for row in rows:
        for time in row["transitions"]:
            time["string_json"] = "\x00" * 700
    raw = json.dumps(body, ensure_ascii=False).encode()
    assert 4 * 1024 * 1024 < len(raw) < MAX_DOCUMENT
    with pytest.raises(ValueError, match="4 MiB"):
        service.import_document(raw)


async def test_original_string_basis_keeps_unicode_controls_invalid_json_and_null_text(tmp_path):
    from .test_native_schedule_strings import string_overrides, stringtag

    report, _, _ = await acquire(
        tmp_path / "string-peer", overrides=string_overrides(stringtag("old"))
    )
    assert report["complete"]
    library, capture = saved(tmp_path / "library", encoded(report))
    service = NativeExceptionText(library)
    body = document(capture)
    time = body["buffer"]["rows"][0]["transitions"][0]
    time.update(native_type="CharacterString", value_text="null \x00é🌡", string_json='"\\u')
    result = service.import_document(json.dumps(body, ensure_ascii=False).encode())
    assert result["native_type"] == "CharacterString" and result["buffer"] == body["buffer"]
    time["native_type"] = "Null"
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]
