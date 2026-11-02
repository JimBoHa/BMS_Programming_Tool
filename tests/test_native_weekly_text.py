"""Unfinished fields survive recovery; source evidence and native authority do not change."""

import asyncio
import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_schedule_library import encoded
from bms_tool.native_weekly_text import (
    DOCUMENT_PROFILE,
    IMPORT_PROFILE,
    MAX_DOCUMENT,
    NativeWeeklyText,
)
from fastapi.testclient import TestClient

from .test_native_schedule_library import acquire, saved

BASE = "/api/bacnet/schedules/library/weekly/unfinished/import"


def document(capture):
    return {
        "profile": DOCUMENT_PROFILE,
        "field_authority": False,
        "source": [capture["id"], "schedule,1", "1"],
        "buffer": {
            "rows": [
                {
                    "time": ["1e", "", "-", "00"],
                    "native_type": "Real",
                    "value_text": "-2e-",
                    "string_json": '"\\u',
                }
            ],
            "imported": {"filename": "old-review.json", "review_id": "a" * 64},
        },
    }


@pytest.fixture(scope="module")
def weekly_source_bytes(tmp_path_factory):
    report, _, _ = asyncio.run(acquire(tmp_path_factory.mktemp("weekly-raw-source"), routed=True))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


@pytest.fixture
def parts(tmp_path, weekly_source_bytes):
    library, capture = saved(tmp_path, weekly_source_bytes)
    return library, NativeWeeklyText(library), document(capture)


def test_invalid_text_exact_copy_no_review_and_originals_unchanged(parts):
    library, service, body = parts
    before = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
    raw = json.dumps(body, indent=2, ensure_ascii=False).encode()
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
    result["buffer"]["rows"][0]["time"][0] = "12"
    assert service.import_document(raw)["buffer"] == body["buffer"]
    assert {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()} == before


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "authority",
        "numeric_false",
        "unknown_root",
        "source_shape",
        "source_missing",
        "foreign_object",
        "noncanonical_object",
        "unknown_object",
        "day_number",
        "day_range",
        "day_padded",
        "unknown_buffer",
        "rows_shape",
        "row_count",
        "unknown_row",
        "time_shape",
        "time_type",
        "time_limit",
        "value_type",
        "value_limit",
        "string_type",
        "string_limit",
        "native_type",
        "provenance",
        "raw_provenance",
    ],
)
def test_rejects_unknown_authority_or_oversized_shapes_without_mutation(parts, case):
    library, service, body = parts
    row = body["buffer"]["rows"][0]
    if case == "profile":
        body["profile"] = "native-schedule-weekly-day-draft/1"
    elif case == "authority":
        body["field_authority"] = True
    elif case == "numeric_false":
        body["field_authority"] = 0
    elif case == "unknown_root":
        body["token"] = "a" * 32
    elif case == "source_shape":
        body["source"].append("more")
    elif case == "source_missing":
        body["source"][0] = "f" * 64
    elif case == "foreign_object":
        body["source"][1] = "calendar,1"
    elif case == "noncanonical_object":
        body["source"][1] = "schedule,01"
    elif case == "unknown_object":
        body["source"][1] = "schedule,9"
    elif case == "day_number":
        body["source"][2] = 1
    elif case == "day_range":
        body["source"][2] = "8"
    elif case == "day_padded":
        body["source"][2] = "01"
    elif case == "unknown_buffer":
        body["buffer"]["dirty"] = True
    elif case == "rows_shape":
        body["buffer"]["rows"] = {}
    elif case == "row_count":
        body["buffer"]["rows"] *= 33
    elif case == "unknown_row":
        row["key"] = 1
    elif case == "time_shape":
        row["time"] = ["0"]
    elif case == "time_type":
        row["time"][0] = 0
    elif case == "time_limit":
        row["time"][0] = "123"
    elif case == "value_type":
        row["value_text"] = 1
    elif case == "value_limit":
        row["value_text"] = "🌡" * 129
    elif case == "string_type":
        row["string_json"] = None
    elif case == "string_limit":
        row["string_json"] = "🌡" * 770
    elif case == "native_type":
        row["native_type"] = "CharacterString"
    elif case == "provenance":
        body["buffer"]["imported"]["review_id"] = "wrong"
    elif case == "raw_provenance":
        body["buffer"]["rawImported"] = {
            "filename": "old.json",
            "file_sha256": "b" * 64,
            "can_apply": True,
        }
    before = library.source(body["source"][0]) if case != "source_missing" else None
    with pytest.raises(ValueError):
        service.import_document(encoded(body))
    assert not library.reviews
    if before is not None:
        assert library.source(body["source"][0]) == before


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
def test_strict_parser_refuses_duplicates_invalid_unicode_numbers_and_depth(parts, raw):
    with pytest.raises(ValueError):
        parts[1].import_document(raw)


@pytest.mark.parametrize("day", list("1234567"))
def test_each_day_retains_null_inactive_string_text_and_unverified_metadata(parts, day):
    _, service, body = parts
    body["source"][2] = day
    body["buffer"]["rows"][0]["native_type"] = "Null"
    body["buffer"]["rawImported"] = {"filename": "prior raw.json", "file_sha256": "b" * 64}
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]


def test_empty_day_and_maximum_escaped_editor_rows_fit_unchanged_file_bound(parts):
    _, service, body = parts
    body["buffer"]["rows"] = []
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]
    row = {
        "time": ["\x00\x00"] * 4,
        "native_type": "Real",
        "value_text": "\x00" * 256,
        "string_json": "\x00" * 1538,
    }
    body["buffer"]["rows"] = [copy.deepcopy(row) for _ in range(32)]
    body["buffer"]["imported"]["filename"] = "\x00" * 1024
    body["buffer"]["rawImported"] = {"filename": "\x00" * 1024, "file_sha256": "b" * 64}
    raw = json.dumps(body, indent=2, ensure_ascii=False).encode()
    assert len(raw) < MAX_DOCUMENT
    assert service.import_document(raw)["buffer"] == body["buffer"]
    with pytest.raises(ValueError, match="byte bound"):
        service.import_document(b" " * (MAX_DOCUMENT + 1))


async def test_string_capture_preserves_controls_incomplete_literal_and_explicit_null(tmp_path):
    from .test_native_schedule_strings import string_overrides, stringtag

    report, _, _ = await acquire(tmp_path / "peer", overrides=string_overrides(stringtag("old")))
    library, capture = saved(tmp_path / "library", encoded(report))
    service, body = NativeWeeklyText(library), document(capture)
    row = body["buffer"]["rows"][0]
    row.update(native_type="CharacterString", value_text="null\x00é🌡", string_json='"\\u')
    result = service.import_document(json.dumps(body, ensure_ascii=False).encode())
    assert result["native_type"] == "CharacterString" and result["buffer"] == body["buffer"]
    row["native_type"] = "Null"
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]
    row["native_type"] = "Real"
    with pytest.raises(ValueError, match="captured default"):
        service.import_document(encoded(body))


async def test_raw_recovery_does_not_broaden_older_weekly_exception_context_rules(tmp_path):
    overrides = {
        ("schedule,1", "exception-schedule", 1): bytes.fromhex(
            "0e2bff07010f2eb4091e000044400000002f3908"
        )
    }
    report, _, _ = await acquire(tmp_path / "peer", overrides=overrides)
    assert report["complete"] and report["identity_verified"]
    library, capture = saved(tmp_path / "library", encoded(report))
    original = library.source(capture["id"])
    with pytest.raises(ValueError):
        NativeWeeklyText(library).import_document(encoded(document(capture)))
    assert library.source(capture["id"]) == original and not library.reviews


def test_actual_HTTP_route_requires_token_keeps_source_and_creates_no_field_authority(
    tmp_path,
    weekly_source_bytes,
):
    with TestClient(create_app(tmp_path)) as client:
        library = client.app.state.schedule_library
        capture = library._store(weekly_source_bytes, "imported")
        raw = encoded(document(capture))
        assert client.post(BASE, files={"file": ("raw.json", raw)}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, headers=headers, files={"file": ("raw.json", raw)})
        assert response.status_code == 200, response.text
        assert response.json()["buffer"] == document(capture)["buffer"]
        assert not client.app.state.bacnet.status()["connected"] and not library.reviews
        assert library.source(capture["id"]) == weekly_source_bytes
        assert (
            client.post(BASE, headers=headers, files={"file": ("bad.json", b"{}")}).status_code
            == 422
        )
        assert (
            client.post(
                BASE, headers=headers, files={"file": ("large.json", b" " * (MAX_DOCUMENT + 1))}
            ).status_code
            == 422
        )
