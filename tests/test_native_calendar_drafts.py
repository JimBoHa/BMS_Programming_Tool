"""Independent Calendar tag literals and immutable offline source proof."""

import asyncio
import copy
import json

import pytest
from bms_tool.app import create_app
from bms_tool.moi_identity import sha
from bms_tool.native_calendar_drafts import (
    PROFILE,
    RULES_SHA256,
    CalendarDraft,
    NativeCalendarDrafts,
)
from bms_tool.native_schedule_library import NativeScheduleLibrary, digest, encoded
from fastapi.testclient import TestClient

from .test_native_schedule_library import acquire, reseal, saved

BASE = "/api/bacnet/schedules/library/calendar"
OLD = "0cff0d20ff1ea4ff0101ffa4ff0c1fff1f2bff0607"
ENTRIES = [
    {"kind": "date", "date": [126, 11, 2, 255]},
    {"kind": "dateRange", "start": [126, 11, 2, 255], "end": [126, 11, 4, 255]},
    {"kind": "weekNDay", "fields": [255, 6, 7]},
    {"kind": "weekNDay", "fields": [255, 7, 1]},
]
NEW = "0c7e0b02ff1ea47e0b02ffa47e0b04ff1f2bff06072bff0701"


@pytest.fixture(scope="module")
def source_bytes(tmp_path_factory):
    report, _, _ = asyncio.run(acquire(tmp_path_factory.mktemp("calendar-original")))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


def setup(tmp_path, source):
    library, capture = saved(tmp_path, source)
    request = {
        "capture_id": capture["id"],
        "object_id": "calendar,1",
        "entries": copy.deepcopy(ENTRIES),
    }
    return library, NativeCalendarDrafts(library), request


def originals(library):
    return {
        p.name: (p.read_bytes(), p.stat().st_mode & 0o777)
        for p in library.directory.iterdir()
        if p.is_file()
    }


def verify(review):
    assert review["id"] == digest({k: v for k, v in review.items() if k != "id"})
    assert review["profile"] == review["format"] == PROFILE
    assert review["rules_sha256"] == RULES_SHA256
    assert (
        not review["field_writes"]
        and not review["controller_queries"]
        and not review["capture_mutations"]
    )
    for side in ("old", "new"):
        assert review[side]["sha256"] == sha(bytes.fromhex(review[side]["encoded_hex"]))


def test_all_choices_literal_bytes_stateless_export_import_and_originals_survive_restart(
    tmp_path, source_bytes
):
    library, service, request = setup(tmp_path / "one", source_bytes)
    before = originals(library)
    source = service.source(request["capture_id"])
    (row,) = source["calendars"]
    assert row["eligible"] and row["value_encoded_hex"] == OLD
    assert row["property_encoded_hex"] == "3e" + OLD + "3f"
    reviewed = service.review(request)
    verify(reviewed)
    assert reviewed["old"]["encoded_hex"] == OLD
    assert reviewed["new"]["encoded_hex"] == NEW
    assert reviewed["new"]["entries"] == ENTRIES
    assert reviewed["new"]["minimum_known_protocol_revision"] == 18
    assert reviewed["new"]["target_revision_verified"] is False
    assert reviewed["diff"] == {
        "changed": True,
        "old_count": 3,
        "new_count": 4,
        "other_properties_changed": False,
    }
    document = service.export({"draft": request, "expected_review_id": reviewed["id"]})
    assert document == encoded(reviewed)
    restarted = NativeCalendarDrafts(NativeScheduleLibrary(tmp_path / "one"))
    assert restarted.import_review(document) == reviewed
    assert restarted.export({"draft": request, "expected_review_id": reviewed["id"]}) == document
    assert library.source(request["capture_id"]) == source_bytes and originals(library) == before
    assert library.reviews == {}  # No weekly-review eviction or new authority cache.


@pytest.mark.parametrize(
    "entries,expected",
    [
        ([], ""),
        ([ENTRIES[0], ENTRIES[0]], "0c7e0b02ff0c7e0b02ff"),
        ([ENTRIES[2], ENTRIES[0]], "2bff06070c7e0b02ff"),
    ],
)
def test_empty_duplicate_and_ordered_values_are_not_normalized(
    tmp_path, source_bytes, entries, expected
):
    library, service, request = setup(tmp_path, source_bytes)
    reviewed = service.review(request | {"entries": entries})
    verify(reviewed)
    assert reviewed["new"]["encoded_hex"] == expected and reviewed["new"]["entries"] == entries
    assert reviewed["new"]["minimum_known_protocol_revision"] is None


@pytest.mark.parametrize("week", [1, 2, 3, 4, 5, 6, 7, 8, 9, 255])
def test_documented_week_choices_are_exact_without_inventing_target_revision(
    tmp_path, source_bytes, week
):
    _, service, request = setup(tmp_path, source_bytes)
    reviewed = service.review(
        request | {"entries": [{"kind": "weekNDay", "fields": [14, week, 255]}]}
    )
    assert reviewed["new"]["encoded_hex"] == "2b0e" + bytes([week, 255]).hex()
    assert reviewed["new"]["minimum_known_protocol_revision"] == (18 if 7 <= week <= 9 else None)
    assert not reviewed["new"]["target_revision_verified"]


@pytest.mark.parametrize(
    "fields",
    [
        [True, 11, 2, 255],
        [126.0, 11, 2, 255],
        ["126", 11, 2, 255],
        [-1, 11, 2, 255],
        [256, 11, 2, 255],
        [126, 0, 2, 255],
        [126, 15, 2, 255],
        [126, 11, 0, 255],
        [126, 11, 35, 255],
        [126, 11, 2, 0],
        [126, 11, 2, 8],
        [126, 2, 29, 255],
        [0, 2, 29, 255],
        [126, 2, 30, 255],
        [126, 11, 2, 2],
        [126, 11, 2],
    ],
)
def test_invalid_or_coerced_date_patterns_are_refused(tmp_path, source_bytes, fields):
    _, service, request = setup(tmp_path, source_bytes)
    with pytest.raises(ValueError):
        service.review(request | {"entries": [{"kind": "date", "date": fields}]})


@pytest.mark.parametrize(
    "fields",
    [[0, 1, 1], [15, 1, 1], [1, 0, 1], [1, 10, 1], [1, 1, 0], [1, 1, 8], [1, True, 1], [1, "1", 1]],
)
def test_reserved_week_fields_and_coercion_are_refused(tmp_path, source_bytes, fields):
    _, service, request = setup(tmp_path, source_bytes)
    with pytest.raises(ValueError):
        service.review(request | {"entries": [{"kind": "weekNDay", "fields": fields}]})


def test_ranges_bounds_and_specific_identity_are_strict(tmp_path, source_bytes):
    _, service, request = setup(tmp_path, source_bytes)
    for entries in (
        [{"kind": "dateRange", "start": [126, 12, 1, 255], "end": [126, 1, 1, 255]}],
        [ENTRIES[0]] * 33,
        [{"kind": "calendarReference", "object": "calendar,2"}],
    ):
        with pytest.raises(ValueError):
            service.review(request | {"entries": entries})
    for obj in ("schedule,1", "calendar,4194303", "calendar:1"):
        with pytest.raises(ValueError):
            service.review(request | {"object_id": obj})
    for extra in ({"apply": True}, {"router": "127.0.0.1:49999"}, {"priority": 8}):
        with pytest.raises(ValueError):
            CalendarDraft.model_validate(request | extra)
    assert service.review(request | {"entries": [{"kind": "date", "date": [255, 2, 29, 255]}]})[
        "new"
    ]["entries"][0]["date"] == [255, 2, 29, 255]


@pytest.mark.parametrize(
    "case",
    [
        "device_unverified",
        "device_tags",
        "calendar_unverified",
        "calendar_tags",
        "partial",
        "hash",
        "representation",
        "duplicates",
        "wildcard_object",
    ],
)
def test_ambiguous_partial_substituted_or_unverified_sources_remain_ineligible(
    tmp_path, source_bytes, case
):
    report = json.loads(source_bytes)
    item = report["objects"][0]
    props = item["properties"]
    if case == "device_unverified":
        report["identity_verified"] = False
    elif case == "device_tags":
        report["device_identity"]["value"]["value"] = "device,43"
    elif case == "calendar_unverified":
        item["identity_verified"] = False
    elif case == "calendar_tags":
        props["object-identifier"]["value"]["value"] = "calendar,2"
    elif case == "partial":
        props["date-list"]["status"] = "timeout"
    elif case == "hash":
        props["date-list"]["encoded_value"]["sha256"] = "0" * 64
    elif case == "representation":
        props["date-list"]["value"][0]["value"]["fields"][0] = 126
    elif case == "duplicates":
        report["objects"].append(copy.deepcopy(item))
    elif case == "wildcard_object":
        item["object"] = "calendar,4194303"
    library, service, request = setup(tmp_path, reseal(report))
    source = service.source(request["capture_id"])
    assert source["calendars"] and not source["calendars"][0]["eligible"]
    assert originals(library)
    with pytest.raises(ValueError):
        service.review(request)


def test_source_drift_changed_review_or_unknown_import_never_exports_a_different_value(
    tmp_path, source_bytes
):
    library, service, request = setup(tmp_path, source_bytes)
    review = service.review(request)
    raw = encoded(review)
    with pytest.raises(ValueError):
        service.export({"draft": request | {"entries": []}, "expected_review_id": review["id"]})
    for change in (
        {"rules_sha256": "0" * 64},
        {"new": review["old"]},
        {"source": review["source"] | {"object": "calendar,2"}},
    ):
        changed = copy.deepcopy(review)
        changed.update(change)
        changed["id"] = digest({k: v for k, v in changed.items() if k != "id"})
        with pytest.raises(ValueError):
            service.import_review(encoded(changed))
    for invalid in (b"{}", b'{"profile":0,"profile":1}', raw + b"x", b" " * (128 * 1024 + 1)):
        with pytest.raises(ValueError):
            service.import_review(invalid)
    capture = library.directory / ("capture-" + request["capture_id"] + ".json")
    original = capture.read_bytes()
    capture.write_bytes(original.replace(b'"source_json"', b'"changed_json"'))
    with pytest.raises(ValueError):
        service.export({"draft": request, "expected_review_id": review["id"]})
    assert capture.read_bytes() != original  # Diagnostics never repair a substituted source.


def test_many_stateless_reviews_do_not_evict_weekly_drafts_or_change_original_storage(
    tmp_path, source_bytes
):
    from .test_native_schedule_library import request as weekly_request

    library, service, request = setup(tmp_path, source_bytes)
    detail = library.detail(request["capture_id"])
    old = library.review(**weekly_request(detail))
    cache = copy.deepcopy(library.reviews)
    before = originals(library)
    for i in range(40):
        service.review(
            request | {"entries": [{"kind": "date", "date": [126, 255, 255, 255]}] * (i % 32)}
        )
    assert library.reviews == cache and library.export_review(old["id"]) == cache[old["id"]]
    assert originals(library) == before


def test_exact_seed_is_no_op_and_optional_unavailable_quality_is_preserved(tmp_path, source_bytes):
    report = json.loads(source_bytes)
    report["complete"] = False
    report["status"] = "partial"
    item = report["objects"][0]
    item["complete"] = False
    item["properties"]["reliability"] = {
        "status": "unavailable",
        "problem": "authored optional property denial",
    }
    library, service, request = setup(tmp_path, reseal(report))
    before = originals(library)
    (row,) = service.source(request["capture_id"])["calendars"]
    assert row["eligible"]
    reviewed = service.review(request | {"entries": row["entries"]})
    assert not reviewed["diff"]["changed"] and reviewed["new"]["encoded_hex"] == OLD
    assert originals(library) == before


@pytest.mark.parametrize(
    "literal,issue",
    [
        ("2bff0a07", "WeekNDay"),
        ("0cff0f20ff", "date"),
        ("0d04ff0d20ff", "normalization"),
        ("0cff0d20ff" * 33, "32-entry"),
    ],
)
def test_invalid_or_noncanonical_captured_native_patterns_are_not_silently_rewritten(
    tmp_path, source_bytes, literal, issue
):
    from bacpypes3.object import CalendarObject
    from bacpypes3.pdu import PDU
    from bacpypes3.primitivedata import TagList
    from bms_tool.property_evidence import native_value

    report = json.loads(source_bytes)
    row = report["objects"][0]["properties"]["date-list"]
    raw = bytes.fromhex("3e" + literal + "3f")
    tags = TagList.decode(PDU(raw))
    pending = TagList(list(tags)[1:-1])
    value = CalendarObject.get_property_type("date-list").decode(pending)
    assert not pending
    errors = []
    row["value"] = native_value(value, errors)
    assert not errors
    row["encoded_value"] = {
        "hex": raw.hex(),
        "bytes": len(raw),
        "sha256": sha(raw),
        "complete": True,
    }
    library, service, request = setup(tmp_path, reseal(report))
    original = originals(library)
    (result,) = service.source(request["capture_id"])["calendars"]
    assert not result["eligible"] and issue.lower() in " ".join(result["issues"]).lower()
    with pytest.raises(ValueError):
        service.review(request)
    assert originals(library) == original


@pytest.mark.parametrize("routed", [False, True])
async def test_acquired_native_calendar_is_drafted_after_the_interface_is_closed(tmp_path, routed):
    report, inventory, requests = await acquire(tmp_path / "peer", routed=routed)
    assert inventory.closed and requests > 20
    library, service, request = setup(tmp_path / "library", encoded(report))
    before = originals(library)
    result = service.review(request)
    assert result["source"]["target"] == report["target"]
    assert result["new"]["encoded_hex"] == NEW
    assert result["source"]["target"]["dnet"] == (3001 if routed else None)
    assert originals(library) == before


def test_local_http_exports_exact_review_with_no_field_or_capture_mutations(
    tmp_path, source_bytes, monkeypatch
):
    from bms_tool import app as app_module

    monkeypatch.setattr(app_module, "web_directory", lambda: None)
    app = create_app(tmp_path)
    library, service, request = setup(tmp_path, source_bytes)
    with TestClient(app) as client:
        token = client.get("/api/session").json()["token"]
        headers = {"X-Studio-Token": token}
        before = originals(library)
        for path, body in (("/source", {"id": request["capture_id"]}), ("/review", request)):
            assert client.get(BASE + path).status_code == 405
            assert client.post(BASE + path, json=body).status_code == 403
            assert (
                client.post(BASE + path, headers=headers, json=body | {"apply": True}).status_code
                == 422
            )
        source = client.post(BASE + "/source", headers=headers, json={"id": request["capture_id"]})
        assert source.status_code == 200, source.text
        response = client.post(BASE + "/review", headers=headers, json=request)
        assert response.status_code == 200, response.text
        review = response.json()
        verify(review)
        exported = client.post(
            BASE + "/export",
            headers=headers,
            json={"draft": request, "expected_review_id": review["id"]},
        )
        assert exported.status_code == 200 and exported.content == encoded(review)
        imported = client.post(
            BASE + "/import",
            headers=headers,
            files={"file": ("calendar.json", exported.content, "application/json")},
        )
        assert imported.status_code == 200 and imported.json() == review
        assert not client.get("/api/session").json()["field_network_open"]
        assert originals(library) == before
