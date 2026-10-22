"""Native wire evidence, offline draft proof and durable immutable capture tests."""

import asyncio
import copy
import hashlib
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from bms_tool import native_schedule_library as module
from bms_tool.connections import Bacnet
from bms_tool.native_schedule_library import (
    CaptureAction,
    NativeScheduleLibrary,
    NativeTransition,
    WeeklyDayDraft,
    digest,
    encoded,
    primitive,
    strict_json,
)
from bms_tool.schedule_inventory import ScheduleInventory
from bms_tool.storage import Store

from .test_connections import free_udp
from .test_file_access import held_process  # noqa: F401
from .test_schedule_inventory import make_peer, options


async def acquire(directory, *, routed=False, overrides=None, behavior="normal"):
    """The peer writes independently authored BACnet tags, not product encoders."""
    peer = await make_peer(routed=routed, behavior=behavior)
    original = peer.value
    peer.value = lambda obj, prop, index: (overrides or {}).get(
        (str(obj), prop, index), original(obj, prop, index)
    )
    client = Bacnet(Store(directory))
    await client.connect(f"127.0.0.1:{free_udp()}")
    inventory = ScheduleInventory(
        client, client.store, timeout=0.2, operation_timeout=5, request_gap=0
    )
    try:
        report = await inventory.read(**options(peer))
        assert not peer.errors
        return report, inventory, len(peer.requests)
    finally:
        await inventory.close()
        client.close()
        peer.close()
        await asyncio.sleep(0.01)


@pytest.fixture(scope="module")
def source_bytes():
    with tempfile.TemporaryDirectory() as directory:
        report, _, _ = asyncio.run(acquire(directory))
    assert report["complete"] and report["identity_verified"]
    return encoded(report)


def saved(tmp_path, source):
    library = NativeScheduleLibrary(tmp_path)
    detail = library._store(source, "imported")
    return library, detail


def request(detail, **changes):
    return {
        "capture_id": detail["id"],
        "object_id": "schedule,1",
        "day": 1,
        "transitions": [{"time": [8, 0, 0, 0], "native_type": "Real", "value_text": "2.5"}],
    } | changes


def reseal(report):
    report = copy.deepcopy(report)
    report["evidence_sha256"] = digest(
        {key: value for key, value in report.items() if key != "evidence_sha256"}
    )
    return encoded(report)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_actual_udp_capture_exact_source_restart_and_offline_proof(tmp_path, routed):
    report, inventory, requests = await acquire(tmp_path / "peer", routed=routed)
    library = NativeScheduleLibrary(tmp_path / "library", inventory)
    detail = library.save(report["id"])
    source = encoded(report)
    assert requests > 20
    assert detail["id"] == hashlib.sha256(source).hexdigest()
    assert library.source(detail["id"]) == source
    assert b'"value":-0.0' in source and b'"value":2.0' in source
    assert detail["target"] == report["target"]
    assert detail["objects"][0]["days"][0]["transitions"][0]["value_text"] == "-0.0"
    assert detail["objects"][0]["days"][0]["encoded_hex"] == "3e0eb40800000044800000000f3f"
    assert "days" not in library.status()["captures"][0]["objects"][0]
    archive = library.archive(detail["id"])
    restarted = NativeScheduleLibrary(tmp_path / "library")  # no connector at all
    assert restarted.archive(detail["id"]) == archive
    assert restarted.source(detail["id"]) == source
    reviewed = restarted.review(**request(detail))
    # An independent literal expected value catches encoder/index/time mistakes.
    assert reviewed["new"]["encoded_hex"] == "0eb40800000044402000000f"
    assert reviewed["old"]["encoded_hex"] == "0eb40800000044800000000f"
    assert reviewed["diff"]["array_index"] == 1
    assert not reviewed["diff"]["other_days_changed"] and not reviewed["field_writes"]
    assert "exception-schedule" in reviewed["diff"]["unchanged_context"]
    assert reviewed["id"] == digest({k: v for k, v in reviewed.items() if k != "id"})
    exported = restarted.export_review(reviewed["id"])
    imported = NativeScheduleLibrary(tmp_path / "imported")
    copied = imported.import_capture(archive)
    assert copied["origin"] == "imported" and imported.source(copied["id"]) == source
    assert copied["ingest"]["incoming_archive_sha256"] == hashlib.sha256(archive).hexdigest()
    assert (
        copied["import_provenance"]["incoming_archive_sha256"]
        == hashlib.sha256(archive).hexdigest()
    )
    new_archive = imported.archive(copied["id"])
    assert (
        copied["import_provenance"]["stored_archive_sha256"]
        == hashlib.sha256(new_archive).hexdigest()
    )
    imported.import_capture(archive)
    assert imported.archive(copied["id"]) == new_archive
    assert imported.import_review(exported) == reviewed
    assert imported.export_review(reviewed["id"]) == exported


def test_preserved_signed_zero_empty_day_and_readable_real_rounding(tmp_path, source_bytes):
    library, detail = saved(tmp_path, source_bytes)
    seed = detail["objects"][0]["days"][0]["transitions"]
    unchanged = library.review(**request(detail, transitions=seed))
    assert not unchanged["diff"]["changed"]
    assert unchanged["new"]["transitions"][0]["wire_value_text"] == "-0.0"
    rounded = library.review(**request(detail, transitions=[{**seed[0], "value_text": "0.1"}]))[
        "new"
    ]["transitions"][0]
    assert rounded["decimal_text_changed"] and rounded["binary64_to_wire_changed"]
    assert rounded["wire_value_text"] == "0.10000000149011612"
    assert rounded["wire_encoded_hex"] == "443dcccccd"
    empty = library.review(**request(detail, transitions=[]))
    assert empty["new"]["encoded_hex"] == "0e0f"
    released = library.review(
        **request(detail, transitions=[{**seed[0], "native_type": "Null", "value_text": "null"}])
    )
    assert released["new"]["encoded_hex"] == "0eb408000000000f"
    assert "not evaluated" in released["interpretation"]["null_behavior"]


@pytest.mark.parametrize(
    "kind,text,expected",
    [
        ("Boolean", "false", "10"),
        ("Boolean", "true", "11"),
        ("Null", "null", "00"),
        ("Integer", "-2147483648", "3480000000"),
        ("Unsigned", "4294967295", "24ffffffff"),
        ("Enumerated", "7", "9107"),
        ("Double", "-0.0", "55088000000000000000"),
    ],
    ids=["false", "true", "null", "signed32", "unsigned32", "enum", "negativezero64"],
)
def test_declared_native_primitives_against_independent_tags(kind, text, expected):
    value = primitive(NativeTransition(time=[23, 59, 59, 99], native_type=kind, value_text=text))
    assert bytes(value.encode().encode().pduData).hex() == expected


@pytest.mark.parametrize(
    "kind,text",
    [
        ("Boolean", "1"),
        ("Null", "None"),
        ("Unsigned", "-1"),
        ("Integer", "2147483648"),
        ("Enumerated", "4294967296"),
        ("Real", "1e39"),
        ("Real", "1e-50"),
        ("Double", "1e309"),
        ("Double", "1e-999"),
        ("Real", "NaN"),
        ("Real", "+1"),
        ("Integer", "01"),
        ("Integer", "-0"),
    ],
    ids=[
        "boolcode",
        "nulltext",
        "negativeunsigned",
        "signedoverflow",
        "enumoverflow",
        "realoverflow",
        "realunderflow",
        "doubleoverflow",
        "doubleunderflow",
        "nan",
        "plussign",
        "leadingzero",
        "negativezeroint",
    ],
)
def test_primitive_range_grammar_and_nonfinite_fail_closed(kind, text):
    with pytest.raises(ValueError):
        primitive(NativeTransition(time=[0, 0, 0, 0], native_type=kind, value_text=text))


@pytest.mark.parametrize(
    "kind,old_hex,new_text,new_hex",
    [
        ("Boolean", "10", "true", "11"),
        ("Unsigned", "2164", "101", "2165"),
        ("Integer", "31ff", "-2", "31fe"),
        ("Enumerated", "9101", "2", "9102"),
        ("Double", "55083ff8000000000000", "2.5", "55084004000000000000"),
    ],
    ids=["boolean", "unsigned", "signed", "enumerated", "double"],
)
async def test_native_consistent_default_domains_are_preserved_and_drafted(
    tmp_path, kind, old_hex, new_text, new_hex
):
    raw = bytes.fromhex(old_hex)
    overrides = {("schedule,1", prop, None): raw for prop in ("schedule-default", "present-value")}
    overrides.update(
        {
            ("schedule,1", "weekly-schedule", day): bytes.fromhex("0eb408000000") + raw + b"\x0f"
            for day in range(1, 8)
        }
    )
    for index, period in ((1, "0e0cff021dff0f"), (2, "1c01800002")):
        overrides[("schedule,1", "exception-schedule", index)] = (
            bytes.fromhex(period + "2eb4091e0000") + raw + bytes.fromhex("2f3908")
        )
    report, _, _ = await acquire(tmp_path / "peer", overrides=overrides)
    library, detail = saved(tmp_path / "library", encoded(report))
    assert detail["objects"][0]["eligible"]
    assert detail["objects"][0]["native_type"] == kind
    result = library.review(
        **request(
            detail,
            transitions=[
                {
                    "time": [8, 0, 0, 0],
                    "native_type": kind,
                    "value_text": new_text,
                }
            ],
        )
    )
    assert result["new"]["encoded_hex"] == "0eb408000000" + new_hex + "0f"


@pytest.mark.parametrize(
    "changes",
    [
        {"day": True},
        {"day": 0},
        {"day": 8},
        {"object_id": "calendar,1"},
        {"transitions": [{"time": [True, 0, 0, 0], "native_type": "Real", "value_text": "1"}]},
        {"transitions": [{"time": [24, 0, 0, 0], "native_type": "Real", "value_text": "1"}]},
        {"transitions": [{"time": [1, 0, 0, 255], "native_type": "Real", "value_text": "1"}]},
        {"transitions": [{"time": [1, 0, 0, 0], "native_type": "Real", "value_text": 1}]},
    ],
    ids=[
        "boolday",
        "dayzero",
        "dayeight",
        "calendar",
        "boolhour",
        "hour24",
        "wildcard",
        "numbertext",
    ],
)
def test_strict_native_day_request_types(changes):
    with pytest.raises(ValueError):
        WeeklyDayDraft(**request({"id": "a" * 64}, **changes))


def test_duplicate_unsorted_and_wrong_type_are_not_interpreted(tmp_path, source_bytes):
    library, detail = saved(tmp_path, source_bytes)
    row = request(detail)["transitions"][0]
    for transitions in (
        [row, row],
        [row, {**row, "time": [7, 0, 0, 0]}],
        [{**row, "native_type": "Boolean", "value_text": "true"}],
        [row] * 33,
    ):
        with pytest.raises(ValueError):
            library.review(**request(detail, transitions=transitions))
    assert not library.reviews


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({("schedule,1", "schedule-default", None): b"\x00"}, "non-Null"),
        ({("schedule,1", "schedule-default", None): b"\x11"}, "datatype conflicts"),
        ({("schedule,1", "present-value", None): b"\x11"}, "datatype conflicts"),
        (
            {("schedule,1", "weekly-schedule", 1): b"\x0e\xb4\x08\0\0\0\x11\x0f"},
            "datatype conflicts",
        ),
        (
            {
                ("schedule,1", "exception-schedule", 1): bytes.fromhex(
                    "0e0cff021dff0f2eb4091e0000112f3908"
                )
            },
            "datatype conflicts",
        ),
        (
            {
                ("schedule,1", "exception-schedule", 1): bytes.fromhex(
                    "0e0cff021dff0f2eb4091e000044400000002f3900"
                )
            },
            "priority",
        ),
        (
            {("schedule,1", "effective-period", None): bytes.fromhex("a47e021effa47e0c1fff")},
            "calendar date",
        ),
        ({("schedule,1", "reliability", None): b"\x92\x03\xe7"}, "unknown"),
        ({("schedule,1", "priority-for-writing", None): b"\x21\x00"}, "priority"),
        (
            {
                ("schedule,1", "exception-schedule", 2): bytes.fromhex(
                    "1c01bfffff2eb4091e000044400000002f3908"
                )
            },
            "Calendar object",
        ),
        (
            {
                ("schedule,1", "exception-schedule", 2): bytes.fromhex(
                    "0e2bff07ff0f2eb4091e000044400000002f3908"
                )
            },
            "WeekNDay",
        ),
    ],
    ids=[
        "nulldefault",
        "booldefault",
        "boolpresent",
        "boolweekly",
        "boolevent",
        "eventpriority",
        "impossibledate",
        "unknownreliability",
        "priorityzero",
        "wildcardcalendar",
        "unqualifiedweek7",
    ],
)
async def test_native_context_mismatches_preserved_but_draft_deferred(tmp_path, overrides, reason):
    report, _, _ = await acquire(tmp_path / "peer", overrides=overrides)
    library, detail = saved(tmp_path / "library", encoded(report))
    assert library.source(detail["id"]) == encoded(report)
    assert not detail["objects"][0]["eligible"]
    assert reason in detail["objects"][0]["issues"][0]
    with pytest.raises(ValueError, match=reason):
        library.review(**request(detail))


async def test_opaque_native_timevalue_is_retained_without_edit_interpretation(tmp_path):
    report, _, _ = await acquire(tmp_path / "peer", behavior="unknown_any")
    source = encoded(report)
    library, detail = saved(tmp_path / "library", source)
    assert not detail["objects"][0]["eligible"]
    assert library.source(detail["id"]) == source
    assert library.detail(detail["id"])["report"] == report
    with pytest.raises(ValueError):
        library.review(**request(detail))
    assert not library.reviews


def test_decoded_value_source_tags_index_and_context_cannot_be_reinterpreted(
    tmp_path, source_bytes
):
    original = json.loads(source_bytes)
    for field, value in (
        ("array_index", True),
        ("value", {}),
        ("nested_decode_errors", ["unknown"]),
    ):
        changed = copy.deepcopy(original)
        changed["objects"][1]["properties"]["weekly-schedule"]["elements"][0][field] = value
        library, detail = saved(tmp_path / field, reseal(changed))
        assert not detail["objects"][0]["eligible"]
        with pytest.raises(ValueError):
            library.review(**request(detail))
    for prop in ("exception-schedule", "schedule-default", "effective-period"):
        changed = copy.deepcopy(original)
        del changed["objects"][1]["properties"][prop]
        _, detail = saved(tmp_path / prop, reseal(changed))
        assert not detail["objects"][0]["eligible"]


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b'{"x":1e-9999}',
        b'{"x":1e-9999999999999999999999999999999999999999}',
        b'{"\\ud800":1}',
        b'{"x":"\\ud800"}',
        '{"x":1}'.encode("utf-16"),
        b"[" * 66 + b"0" + b"]" * 66,
    ],
    ids=[
        "duplicate",
        "nan",
        "overflow",
        "underflow",
        "exponentoverflow",
        "keyunicode",
        "valueunicode",
        "nonutf8",
        "depth",
    ],
)
def test_strict_json_refuses_lossy_or_unbounded_inputs(raw):
    with pytest.raises(ValueError):
        strict_json(raw, 1024)


def test_capture_and_review_seals_unknown_profiles_and_source_tamper(tmp_path, source_bytes):
    library, detail = saved(tmp_path, source_bytes)
    archive = library.archive(detail["id"])
    for field, value in (
        ("format", "unknown/2"),
        ("source_json", source_bytes.decode() + " "),
        ("id", "a" * 64),
    ):
        changed = json.loads(archive)
        changed[field] = value
        with pytest.raises(ValueError):
            library.import_capture(encoded(changed))
    changed = json.loads(source_bytes)
    changed["target"]["device"] = "device,99"
    with pytest.raises(ValueError, match="evidence seal"):
        library._store(encoded(changed), "imported")
    changed = json.loads(source_bytes)
    changed["id"] = 11111111111111111111111111111111
    with pytest.raises(ValueError, match="inventory source profile"):
        library._store(reseal(changed), "imported")
    review = library.review(**request(detail))
    exported = library.export_review(review["id"])
    forged = json.loads(exported)
    forged["new"]["encoded_hex"] = "0e0f"
    forged["id"] = digest({k: v for k, v in forged.items() if k != "id"})
    with pytest.raises(ValueError, match="differs"):
        library.import_review(encoded(forged))
    assert library.export_review(review["id"]) == exported
    path = library.directory / f"capture-{detail['id']}.json"
    path.write_bytes(archive[:-1] + b" ")
    with pytest.raises(ValueError):
        library.source(detail["id"])


def test_immutable_count_and_byte_pressure_never_overwrite(tmp_path, source_bytes, monkeypatch):
    library, detail = saved(tmp_path, source_bytes)
    original = library.archive(detail["id"])
    # Repeated save deduplicates without rewriting source or local ingest time.
    assert library._store(source_bytes, "session")["id"] == detail["id"]
    assert library.archive(detail["id"]) == original
    for index in range(1, 32):
        report = json.loads(source_bytes)
        report["id"] = f"{index:032x}"
        library._store(reseal(report), "imported")
    assert len(library.status()["captures"]) == 32
    extra = json.loads(source_bytes)
    extra["id"] = "f" * 32
    with pytest.raises(ValueError, match="capacity"):
        library._store(reseal(extra), "imported")
    assert library.archive(detail["id"]) == original
    other = NativeScheduleLibrary(tmp_path / "bytes")
    monkeypatch.setattr(module, "MAX_STORAGE", len(original) // 2)
    with pytest.raises(ValueError, match="capacity"):
        other._store(source_bytes, "session")
    assert list(other.directory.glob("capture-*")) == []


def test_nonregular_capture_and_failed_publication_preserve_evidence(
    tmp_path, source_bytes, monkeypatch
):
    library, detail = saved(tmp_path, source_bytes)
    path = library.directory / f"capture-{detail['id']}.json"
    original = path.read_bytes()
    path.unlink()
    path.mkdir()
    with pytest.raises((ValueError, OSError)):
        library.archive(detail["id"])
    with pytest.raises(ValueError, match="nonregular"):
        library.status()
    path.rmdir()
    target = tmp_path / "external"
    target.write_bytes(original)
    try:
        path.symlink_to(target)
    except OSError:
        pass
    else:
        with pytest.raises((ValueError, OSError)):
            library._store(source_bytes, "session")
        assert target.read_bytes() == original
        path.unlink()
    other = NativeScheduleLibrary(tmp_path / "failure")

    def unavailable(*args, **kwargs):
        raise OSError("hard links unavailable")

    monkeypatch.setattr(module.os, "link", unavailable)
    with pytest.raises(OSError, match="hard links"):
        other._store(source_bytes, "session")
    assert list(other.directory.iterdir()) == [other.directory / ".capture.lock"]


def test_actual_capture_writer_ownership_is_bounded(tmp_path, source_bytes, held_process):  # noqa: F811
    library = NativeScheduleLibrary(tmp_path)
    process = held_process(library.directory / ".capture.lock")
    with pytest.raises(ValueError, match="busy"):
        library._store(source_bytes, "session")
    assert not list(library.directory.glob("capture-*"))
    process.communicate("release\n", timeout=10)
    library._store(source_bytes, "session")


def test_review_retention_is_bounded_and_import_needs_original_source(tmp_path, source_bytes):
    library, detail = saved(tmp_path, source_bytes)
    first = None
    for day in range(1, 18):
        row = request(detail)["transitions"][0]
        reviewed = library.review(**request(detail, transitions=[{**row, "value_text": str(day)}]))
        first = first or reviewed["id"]
    assert len(library.reviews) == 16
    with pytest.raises(ValueError, match="not retained"):
        library.export_review(first)
    empty = NativeScheduleLibrary(tmp_path / "empty")
    with pytest.raises(ValueError, match="unavailable"):
        empty.import_review(library.export_review(reviewed["id"]))
    with pytest.raises(ValueError):
        CaptureAction(id="a" * 32)


def test_parallel_native_reviews_keep_independent_seals_and_bounded_retention(
    tmp_path, source_bytes
):
    library, detail = saved(tmp_path, source_bytes)

    def review(number):
        row = request(detail)["transitions"][0]
        return library.review(**request(detail, transitions=[{**row, "value_text": str(number)}]))

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(review, range(32)))
    assert len(library.reviews) == 16
    originals = {result["id"]: encoded(result) for result in results}
    for id in library.reviews:
        assert library.export_review(id) == originals[id]
    assert len({result["id"] for result in results}) == 32
