"""Raw Calendar recovery keeps invalid fields without creating native authority."""

import asyncio
import copy
import hashlib
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_calendar_text import (
    DOCUMENT_PROFILE,
    IMPORT_PROFILE,
    MAX_DOCUMENT,
    NativeCalendarText,
)
from bms_tool.native_schedule_library import encoded
from fastapi.testclient import TestClient

from .test_native_schedule_library import acquire, saved

BASE = "/api/bacnet/schedules/library/calendar/unfinished/import"


def document(capture):
    return {
        "profile": DOCUMENT_PROFILE,
        "field_authority": False,
        "source": [capture["id"], "calendar,1"],
        "buffer": {
            "rows": [
                {
                    "kind": "date",
                    "date": ["20", "?", "32", ""],
                    "start": ["", "*", "-", "00"],
                    "end": ["2154", "14", "34", "*"],
                    "fields": ["*", "9", "?"],
                }
            ],
            "imported": "a" * 64,
        },
    }


@pytest.fixture(scope="module")
def calendar_source_bytes(tmp_path_factory):
    report, _, _ = asyncio.run(acquire(tmp_path_factory.mktemp("calendar-raw-source"), routed=True))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


@pytest.fixture
def parts(tmp_path, calendar_source_bytes):
    library, capture = saved(tmp_path, calendar_source_bytes)
    return library, NativeCalendarText(library), document(capture)


def test_invalid_active_and_inactive_fields_are_exact_copies_and_source_is_unchanged(parts):
    library, service, body = parts
    original = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
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
    result["buffer"]["rows"][0]["date"][0] = "2026"
    assert service.import_document(raw)["buffer"] == body["buffer"]
    assert not library.reviews
    assert {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()} == original


@pytest.mark.parametrize(
    "case",
    [
        "profile",
        "authority",
        "numeric_false",
        "root_extra",
        "source_shape",
        "source_missing",
        "source_type",
        "noncanonical_object",
        "wrong_object",
        "unknown_object",
        "buffer_extra",
        "imported_type",
        "imported_hash",
        "rows_shape",
        "row_count",
        "row_extra",
        "kind",
        "missing_field",
        "field_shape",
        "field_type",
        "field_limit",
        "raw_metadata",
        "raw_hash",
    ],
)
def test_unknown_and_oversized_shapes_do_not_mutate_or_review(parts, case):
    library, service, body = parts
    row = body["buffer"]["rows"][0]
    if case == "profile":
        body["profile"] = "native-calendar-date-list-draft/1"
    elif case == "authority":
        body["field_authority"] = True
    elif case == "numeric_false":
        body["field_authority"] = 0
    elif case == "root_extra":
        body["token"] = "x" * 32
    elif case == "source_shape":
        body["source"].append("extra")
    elif case == "source_missing":
        body["source"][0] = "f" * 64
    elif case == "source_type":
        body["source"][1] = 1
    elif case == "noncanonical_object":
        body["source"][1] = "calendar,01"
    elif case == "wrong_object":
        body["source"][1] = "schedule,1"
    elif case == "unknown_object":
        body["source"][1] = "calendar,9"
    elif case == "buffer_extra":
        body["buffer"]["can_apply"] = True
    elif case == "imported_type":
        body["buffer"]["imported"] = None
    elif case == "imported_hash":
        body["buffer"]["imported"] = "not a hash"
    elif case == "rows_shape":
        body["buffer"]["rows"] = {}
    elif case == "row_count":
        body["buffer"]["rows"] *= 33
    elif case == "row_extra":
        row["key"] = "not portable"
    elif case == "kind":
        row["kind"] = "calendarReference"
    elif case == "missing_field":
        row.pop("end")
    elif case == "field_shape":
        row["date"] = ["20"]
    elif case == "field_type":
        row["start"][0] = 2026
    elif case == "field_limit":
        row["date"][0] = "🌡" * 3
    elif case == "raw_metadata":
        body["buffer"]["rawImported"] = {"filename": "x" * 1025, "file_sha256": "a" * 64}
    elif case == "raw_hash":
        body["buffer"]["rawImported"] = {"filename": "old.json", "file_sha256": "bad"}
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
def test_strict_unicode_duplicate_key_number_and_depth_limits(parts, raw):
    with pytest.raises(ValueError):
        parts[1].import_document(raw)


@pytest.mark.parametrize("kind", ["date", "dateRange", "weekNDay"])
def test_raw_periods_empty_and_duplicate_rows_and_bounded_provenance_stay_distinct(parts, kind):
    _, service, body = parts
    body["buffer"]["rows"][0]["kind"] = kind
    body["buffer"]["rows"] *= 2
    body["buffer"]["rawImported"] = {"filename": "prior.json", "file_sha256": "b" * 64}
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]
    body["buffer"]["rows"] = []
    body["buffer"]["imported"] = ""
    assert service.import_document(encoded(body))["buffer"] == body["buffer"]


def test_all_maximum_escaped_fields_fit_file_ceiling_and_oversize_is_refused(parts):
    _, service, body = parts
    seed = body["buffer"]["rows"][0]
    for name in ("date", "start", "end", "fields"):
        seed[name] = ["\x00" * 4] * len(seed[name])
    body["buffer"]["rows"] = [copy.deepcopy(seed) for _ in range(32)]
    body["buffer"]["rawImported"] = {"filename": "\x00" * 1024, "file_sha256": "b" * 64}
    raw = json.dumps(body, ensure_ascii=False, indent=2).encode()
    assert len(raw) < MAX_DOCUMENT
    assert service.import_document(raw)["buffer"] == body["buffer"]
    with pytest.raises(ValueError, match="byte bound"):
        service.import_document(b" " * (MAX_DOCUMENT + 1))


def test_actual_token_protected_local_route_preserves_capture_and_keeps_interface_closed(
    tmp_path, calendar_source_bytes
):
    with TestClient(create_app(tmp_path)) as client:
        library = client.app.state.schedule_library
        capture = library._store(calendar_source_bytes, "imported")
        raw = encoded(document(capture))
        assert client.post(BASE, files={"file": ("raw.json", raw)}).status_code == 403
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        response = client.post(BASE, headers=headers, files={"file": ("raw.json", raw)})
        assert response.status_code == 200, response.text
        assert response.json()["buffer"] == document(capture)["buffer"]
        assert library.source(capture["id"]) == calendar_source_bytes and not library.reviews
        assert not client.get("/api/session").json()["field_network_open"]
        assert (
            client.post(BASE, headers=headers, files={"file": ("bad.json", b"{}")}).status_code
            == 422
        )
