"""Literal exception arrays and stateless source-qualified local engineering."""

import asyncio
import copy
import json

import pytest
from bms_tool.app import create_app
from bms_tool.native_schedule_exceptions import (
    MAX_DOCUMENT,
    PROFILE,
    RULES_SHA256,
    NativeScheduleExceptions,
)
from bms_tool.native_schedule_library import NativeScheduleLibrary, digest, encoded
from fastapi.testclient import TestClient

from .test_native_schedule_library import acquire, reseal, saved
from .test_native_schedule_library import request as weekly_request
from .test_native_schedule_strings import string_overrides, stringtag

BASE = "/api/bacnet/schedules/library/exceptions"
OLD = "0e0cff021dff0f2eb4091e000044400000002f39081c018000022eb4091e000044400000002f3908"
EVENTS = [
    {
        "period": {"kind": "date", "date": [126, 11, 2, 1]},
        "priority": 1,
        "transitions": [
            {"time": [8, 0, 0, 0], "native_type": "Real", "value_text": "-0"},
            {"time": [18, 0, 0, 0], "native_type": "Null", "value_text": "null"},
        ],
    },
    {
        "period": {"kind": "dateRange", "start": [126, 11, 2, 1], "end": [126, 11, 4, 3]},
        "priority": 8,
        "transitions": [],
    },
    {
        "period": {"kind": "weekNDay", "fields": [255, 7, 1]},
        "priority": 16,
        "transitions": [{"time": [12, 0, 0, 0], "native_type": "Real", "value_text": "1.5"}],
    },
    {
        "period": {"kind": "calendarReference", "object_id": "calendar,2"},
        "priority": 8,
        "transitions": [{"time": [9, 30, 0, 0], "native_type": "Real", "value_text": "2.0"}],
    },
]
NEW = (
    "0e0c7e0b02010f2eb4080000004480000000b412000000002f3901"
    "0e1ea47e0b0201a47e0b04031f0f2e2f3908"
    "0e2bff07010f2eb40c000000443fc000002f3910"
    "1c018000022eb4091e000044400000002f3908"
)


@pytest.fixture(scope="module")
def source_bytes(tmp_path_factory):
    report, _, _ = asyncio.run(acquire(tmp_path_factory.mktemp("exception-source")))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


@pytest.fixture(scope="module")
def string_source(tmp_path_factory):
    report, _, _ = asyncio.run(
        acquire(
            tmp_path_factory.mktemp("exception-string-source"),
            overrides=string_overrides(stringtag("old")),
        )
    )
    assert report["complete"]
    return encoded(report)


def setup(directory, source, events=None):
    library, capture = saved(directory, source)
    return (
        library,
        NativeScheduleExceptions(library),
        {
            "capture_id": capture["id"],
            "object_id": "schedule,1",
            "events": copy.deepcopy(EVENTS if events is None else events),
        },
    )


def originals(library):
    return {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}


def test_literal_complete_array_all_periods_signed_zero_release_and_stateless_exact_copies(
    tmp_path, source_bytes
):
    library, service, request = setup(tmp_path, source_bytes)
    before = originals(library)
    source = service.source(request["capture_id"])
    (row,) = source["schedules"]
    assert row["eligible"] and row["native_type"] == "Real"
    assert row["value_encoded_hex"] == OLD and not row["Calendar_references_queried"]
    reviewed = service.review(request)
    assert reviewed["profile"] == reviewed["format"] == PROFILE
    assert reviewed["rules_sha256"] == RULES_SHA256
    assert reviewed["id"] == digest({k: v for k, v in reviewed.items() if k != "id"})
    assert reviewed["old"]["encoded_hex"] == OLD and reviewed["new"]["encoded_hex"] == NEW
    assert reviewed["request"]["events"] == EVENTS
    assert reviewed["new"]["events"][0]["transitions"][0]["value_text"] == "-0.0"
    assert reviewed["new"]["minimum_known_protocol_revision"] == 18
    assert reviewed["new"]["target_revision_verified"] is False
    assert (
        not reviewed["field_writes"]
        and not reviewed["controller_queries"]
        and not reviewed["capture_mutations"]
    )
    exact = service.export({"draft": request, "expected_review_id": reviewed["id"]})
    assert exact == encoded(reviewed) and b'"value_text":"-0"' in exact
    restarted = NativeScheduleExceptions(NativeScheduleLibrary(tmp_path))
    assert restarted.import_review(exact) == reviewed
    assert originals(library) == before and library.source(request["capture_id"]) == source_bytes
    assert not library.reviews


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_actual_acquisition_can_be_closed_before_all_exception_engineering(tmp_path, routed):
    report, inventory, reads = await acquire(tmp_path / "peer", routed=routed)
    assert report["complete"] and reads > 0
    library, service, request = setup(tmp_path / "library", encoded(report))
    # acquire closes its actual field interface before returning this source.
    assert inventory.bacnet.app is None
    before = originals(library)
    source = service.source(request["capture_id"])
    request["events"] = source["schedules"][0]["events"]
    reviewed = service.review(request)
    assert reviewed["diff"]["changed"] is False and reviewed["new"]["encoded_hex"] == OLD
    assert (
        service.import_review(
            service.export({"draft": request, "expected_review_id": reviewed["id"]})
        )
        == reviewed
    )
    assert originals(library) == before


@pytest.mark.parametrize("indices", [[], [3, 3], [3, 2, 0], list(range(4)) * 8])
def test_empty_duplicate_ordered_and_32_event_arrays_are_not_normalized(
    tmp_path, source_bytes, indices
):
    events = [EVENTS[i] for i in indices]
    _, service, request = setup(tmp_path, source_bytes, events)
    report = service.review(request)
    assert report["request"]["events"] == events
    assert [row["period"] for row in report["new"]["events"]] == [row["period"] for row in events]
    assert report["diff"]["new_count"] == len(events)
    if not events:
        assert report["new"]["encoded_hex"] == ""


@pytest.mark.parametrize(
    "kind,atom,text,new_hex",
    [
        ("Boolean", "11", "false", "10"),
        ("Unsigned", "2101", "4294967295", "24ffffffff"),
        ("Integer", "31ff", "-2147483648", "3480000000"),
        ("Enumerated", "9101", "4294967295", "94ffffffff"),
        ("Real", "4400000000", "0.1", "443dcccccd"),
        ("Double", "55080000000000000000", "0.1", "55083fb999999999999a"),
    ],
)
async def test_observed_native_basis_keeps_each_exact_primitive_wire_type(
    tmp_path, kind, atom, text, new_hex
):
    report, _, _ = await acquire(tmp_path / "peer", overrides=string_overrides(bytes.fromhex(atom)))
    events = [
        {
            "period": {"kind": "calendarReference", "object_id": "calendar,2"},
            "priority": 5,
            "transitions": [{"time": [0, 0, 0, 0], "native_type": kind, "value_text": text}],
        }
    ]
    _, service, request = setup(tmp_path / "library", encoded(report), events)
    reviewed = service.review(request)
    assert reviewed["source"]["native_type"] == kind
    assert reviewed["new"]["encoded_hex"] == "1c018000022eb400000000" + new_hex + "2f3905"


@pytest.mark.parametrize(
    "text", ["", "null", "  ", "é", "e\u0301", "🌡", '"\\\x00\r\n\t', "\x00" * 256, "🌡" * 64]
)
def test_string_exception_values_preserve_exact_utf8_and_controls(tmp_path, string_source, text):
    event = {
        "period": {"kind": "calendarReference", "object_id": "calendar,2"},
        "priority": 5,
        "transitions": [
            {"time": [0, 0, 0, 0], "native_type": "CharacterString", "value_text": text}
        ],
    }
    _, service, request = setup(tmp_path, string_source, [event])
    reviewed = service.review(request)
    assert reviewed["new"]["events"][0]["transitions"][0]["value_text"] == text
    assert (
        reviewed["new"]["encoded_hex"]
        == "1c018000022eb400000000" + stringtag(text).hex() + "2f3905"
    )
    assert (
        service.import_review(
            service.export({"draft": request, "expected_review_id": reviewed["id"]})
        )
        == reviewed
    )


@pytest.mark.parametrize(
    "change",
    [
        "priority_zero",
        "priority_bool",
        "priority_text",
        "time_wildcard",
        "duplicate_time",
        "reverse_time",
        "wrong_type",
        "bad_null",
        "underflow",
        "partial_range",
        "foreign_reference",
        "alias_reference",
        "events33",
        "times33",
        "mutation",
    ],
)
def test_invalid_or_ambiguous_new_events_refuse_without_mutating_the_source(
    tmp_path, source_bytes, change
):
    library, service, request = setup(tmp_path, source_bytes, [EVENTS[0]])
    event = request["events"][0]
    if change == "priority_zero":
        event["priority"] = 0
    elif change == "priority_bool":
        event["priority"] = True
    elif change == "priority_text":
        event["priority"] = "1"
    elif change == "time_wildcard":
        event["transitions"][0]["time"][0] = 255
    elif change == "duplicate_time":
        event["transitions"].append(copy.deepcopy(event["transitions"][0]))
    elif change == "reverse_time":
        event["transitions"].reverse()
    elif change == "wrong_type":
        event["transitions"][0]["native_type"] = "Integer"
    elif change == "bad_null":
        event["transitions"][1]["value_text"] = "false"
    elif change == "underflow":
        event["transitions"][0]["value_text"] = "1e-999"
    elif change == "partial_range":
        event["period"] = {"kind": "dateRange", "start": [255, 1, 1, 255], "end": [126, 11, 4, 3]}
    elif change == "foreign_reference":
        event["period"] = {"kind": "calendarReference", "object_id": "device,42"}
    elif change == "alias_reference":
        event["period"] = {"kind": "calendarReference", "object_id": "calendar,02"}
    elif change == "events33":
        request["events"] *= 33
    elif change == "times33":
        event["transitions"] = event["transitions"][:1] * 33
    elif change == "mutation":
        request["apply"] = True
    before = originals(library)
    with pytest.raises(ValueError):
        service.review(request)
    assert originals(library) == before and not library.reviews


@pytest.mark.parametrize("damage", ["identity", "tags", "count", "partial", "duplicate"])
def test_bad_captured_context_stays_original_and_ineligible(tmp_path, source_bytes, damage):
    source = json.loads(source_bytes)
    row = next(obj for obj in source["objects"] if obj["object"] == "schedule,1")
    if damage == "identity":
        row["identity_verified"] = False
    elif damage == "tags":
        row["properties"]["schedule-default"]["value"] = 123
    elif damage == "count":
        row["properties"]["exception-schedule"]["elements"].pop()
    elif damage == "partial":
        row["properties"]["exception-schedule"]["complete"] = False
    elif damage == "duplicate":
        source["objects"].append(copy.deepcopy(row))
    raw = reseal(source)
    library, service, request = setup(tmp_path, raw)
    before = originals(library)
    assert service.source(request["capture_id"])["schedules"][0]["eligible"] is False
    with pytest.raises(ValueError):
        service.review(request)
    assert library.source(request["capture_id"]) == raw and originals(library) == before


@pytest.mark.parametrize("field", ["source", "wire", "request", "authority", "profile"])
def test_resealed_import_substitutions_and_stale_export_ids_refuse(tmp_path, source_bytes, field):
    library, service, request = setup(tmp_path, source_bytes)
    reviewed = service.review(request)
    altered = copy.deepcopy(reviewed)
    if field == "source":
        altered["source"]["target"]["address"] = "192.0.2.123"
    elif field == "wire":
        altered["new"]["encoded_hex"] = ""
    elif field == "request":
        altered["request"]["events"][0]["priority"] = 2
    elif field == "authority":
        altered["field_writes"] = True
    elif field == "profile":
        altered["profile"] = "native-schedule-weekly-day-draft/1"
    altered["id"] = digest({k: v for k, v in altered.items() if k != "id"})
    before = originals(library)
    with pytest.raises(ValueError):
        service.import_review(encoded(altered))
    with pytest.raises(ValueError):
        service.export({"draft": request, "expected_review_id": "0" * 64})
    assert originals(library) == before


def test_real_http_offline_routes_exact_copies_authentication_and_no_authority(
    tmp_path, source_bytes
):
    library, service, request = setup(tmp_path, source_bytes)
    expected = service.review(request)
    before = originals(library)
    with TestClient(create_app(tmp_path)) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        assert not client.get("/api/session").json()["field_network_open"]
        assert client.post(BASE + "/source", json={"id": request["capture_id"]}).status_code == 403
        assert client.post(BASE + "/review", json=request).status_code == 403
        assert (
            client.post(
                BASE + "/review", headers=headers, json={**request, "token": "foreign"}
            ).status_code
            == 422
        )
        source = client.post(BASE + "/source", headers=headers, json={"id": request["capture_id"]})
        assert source.status_code == 200 and source.json()["schedules"][0]["eligible"]
        reviewed = client.post(BASE + "/review", headers=headers, json=request)
        assert reviewed.status_code == 200 and reviewed.json() == expected
        exported = client.post(
            BASE + "/export",
            headers=headers,
            json={"draft": request, "expected_review_id": expected["id"]},
        )
        assert exported.status_code == 200 and exported.content == encoded(expected)
        assert (
            client.post(
                BASE + "/export", json={"draft": request, "expected_review_id": expected["id"]}
            ).status_code
            == 403
        )
        assert (
            client.post(
                BASE + "/import",
                files={"file": ("exceptions.json", exported.content, "application/json")},
            ).status_code
            == 403
        )
        imported = client.post(
            BASE + "/import",
            headers=headers,
            files={"file": ("exceptions.json", exported.content, "application/json")},
        )
        assert imported.status_code == 200 and imported.json() == expected
        assert not client.get("/api/session").json()["field_network_open"]
    assert originals(library) == before


@pytest.mark.parametrize("text", ["x" * 257, "🌡" * 65, "\ud800"])
def test_unrepresentable_or_oversized_string_values_refuse(tmp_path, string_source, text):
    event = {
        "period": {"kind": "calendarReference", "object_id": "calendar,2"},
        "priority": 1,
        "transitions": [
            {"time": [0, 0, 0, 0], "native_type": "CharacterString", "value_text": text}
        ],
    }
    library, service, request = setup(tmp_path, string_source, [event])
    before = originals(library)
    with pytest.raises(ValueError):
        service.review(request)
    assert originals(library) == before


def test_exact_32_specific_time_values_and_last_hundredth_are_retained(tmp_path, source_bytes):
    event = copy.deepcopy(EVENTS[3])
    event["transitions"] = [
        {"time": [0, index, 0, 0], "native_type": "Real", "value_text": "1"} for index in range(32)
    ]
    event["transitions"][-1]["time"] = [23, 59, 59, 99]
    _, service, request = setup(tmp_path, source_bytes, [event])
    reviewed = service.review(request)
    assert len(reviewed["new"]["events"][0]["transitions"]) == 32
    assert reviewed["new"]["encoded_hex"].endswith("b4173b3b63443f8000002f3908")


def test_bounded_document_rejection_keeps_originals_and_creates_no_review_cache(
    tmp_path, string_source
):
    event = {
        "period": {"kind": "calendarReference", "object_id": "calendar,2"},
        "priority": 1,
        "transitions": [
            {"time": [0, index, 0, 0], "native_type": "CharacterString", "value_text": "x" * 256}
            for index in range(32)
        ],
    }
    library, service, request = setup(tmp_path, string_source, [event] * 32)
    before = originals(library)
    with pytest.raises(ValueError, match="512 KiB"):
        service.review(request)
    with pytest.raises(ValueError, match="byte bound"):
        service.import_review(b" " * (MAX_DOCUMENT + 1))
    assert originals(library) == before and not library.reviews


def test_duplicate_json_fields_and_new_review_metadata_cannot_change_old_weekly_authority(
    tmp_path, source_bytes
):
    library, service, request = setup(tmp_path, source_bytes)
    for index in range(16):
        library.review(
            **weekly_request(
                {"id": request["capture_id"]},
                transitions=[
                    {"time": [8, 0, 0, 0], "native_type": "Real", "value_text": str(index)}
                ],
            )
        )
    before = copy.deepcopy(library.reviews)
    reviewed = service.review(request)
    raw = service.export({"draft": request, "expected_review_id": reviewed["id"]})
    duplicate = b'{"profile":"duplicate",' + raw[1:]
    with pytest.raises(ValueError, match="Duplicate"):
        service.import_review(duplicate)
    assert service.import_review(raw) == reviewed and library.reviews == before


@pytest.mark.parametrize("week", [7, 8, 9])
@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_captured_modern_week_patterns_are_separately_qualified_without_widening_weekly(
    tmp_path, week, routed
):
    literal = (
        bytes.fromhex("0e2bff") + bytes([week]) + bytes.fromhex("010f2eb4091e000044400000002f3908")
    )
    report, _, _ = await acquire(
        tmp_path / "peer",
        routed=routed,
        overrides={("schedule,1", "exception-schedule", 1): literal},
    )
    assert report["complete"]
    library, capture = saved(tmp_path / "library", encoded(report))
    service = NativeScheduleExceptions(library)
    old = library.detail(capture["id"])["objects"][0]
    assert old["eligible"] is False and "WeekNDay" in str(old["issues"])
    row = service.source(capture["id"])["schedules"][0]
    assert row["eligible"] and row["minimum_known_protocol_revision"] == 18
    request = {"capture_id": capture["id"], "object_id": "schedule,1", "events": row["events"]}
    reviewed = service.review(request)
    assert reviewed["diff"]["changed"] is False and reviewed["old"]["encoded_hex"].startswith(
        literal.hex()
    )
    assert reviewed["new"]["minimum_known_protocol_revision"] == 18
    with pytest.raises(ValueError, match="WeekNDay"):
        library.review(**weekly_request(capture))
