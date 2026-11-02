"""Independent field-range bytes, early refusal and unchanged local evidence."""

import copy

import pytest
from bms_tool.native_calendar_drafts import NativeCalendarDrafts
from bms_tool.native_calendar_write import RULES_SHA256, NativeCalendarWrites

from .test_native_calendar_write import apply, close, link

START, END, ANY = [126, 11, 2, 1], [126, 11, 4, 3], [255, 255, 255, 255]
INVALID = [
    ("start", [255, 1, 1, 255]),
    ("start", [126, 11, 2, 255]),
    ("start", [126, 13, 2, 1]),
    ("start", [126, 11, 32, 1]),
    ("start", [255, 255, 255, 1]),
    ("end", [255, 12, 31, 255]),
    ("end", [126, 11, 4, 255]),
    ("end", [255, 255, 4, 255]),
]


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_unchanged_legacy_range_is_observation_without_a_write_request(tmp_path, routed):
    peer, client, inventory, library, service, request = await link(tmp_path, routed=routed)
    try:
        drafts = NativeCalendarDrafts(library)
        source = drafts.source(request["draft"]["capture_id"])
        draft = {**request["draft"], "entries": source["calendars"][0]["entries"]}
        local = drafts.review(draft)
        preview = await service.preview(
            **{**request, "draft": draft, "expected_review_id": local["id"]}
        )
        assert preview["status"] == "no_change" and preview["can_apply"] is False
        assert preview["token"] is None and not service.plans and not peer.writes
        assert "request_service_body_hex" not in preview and "request_apdu_bytes" not in preview
        with pytest.raises(ValueError, match="fully specified date"):
            service._request(local, peer.endpoint)
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize("side,fields", INVALID)
async def test_partial_or_special_range_endpoints_never_read_or_prepare_a_field_write(
    tmp_path, routed, side, fields
):
    entry = {"kind": "dateRange", "start": START, "end": END, side: fields}
    peer, client, inventory, library, service, request = await link(
        tmp_path, routed=routed, entries=[entry]
    )
    try:
        originals = {p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()}
        local = NativeCalendarDrafts(library).review(request["draft"])
        raw = NativeCalendarDrafts(library).export(
            {"draft": request["draft"], "expected_review_id": local["id"]}
        )
        assert NativeCalendarDrafts(library).import_review(raw) == local
        assert local["request"]["entries"] == [entry]
        reads, journal = list(peer.requests), service.journal.status()
        with pytest.raises(ValueError, match=f"entry 1 {side} requires a fully specified"):
            await service.preview(**request)
        assert peer.requests == reads and not peer.writes
        assert not service.plans and service.active is None
        assert service.journal.status() == journal
        assert originals == {
            p.name: p.read_bytes() for p in library.directory.iterdir() if p.is_file()
        }
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize(
    "start,end,literal",
    [
        (START, END, "1ea47e0b0201a47e0b04031f"),
        (ANY, END, "1ea4ffffffffa47e0b04031f"),
        (START, ANY, "1ea47e0b0201a4ffffffff1f"),
        (ANY, ANY, "1ea4ffffffffa4ffffffff1f"),
        (START, START, "1ea47e0b0201a47e0b02011f"),
        ([124, 2, 29, 4], [124, 2, 29, 4], "1ea47c021d04a47c021d041f"),
    ],
)
async def test_specific_or_wholly_unspecified_ranges_transfer_literal_bytes_once(
    tmp_path, routed, start, end, literal
):
    entry = {"kind": "dateRange", "start": start, "end": end}
    peer, client, inventory, library, service, request = await link(
        tmp_path, routed=routed, entries=[entry]
    )
    try:
        original = library.source(request["draft"]["capture_id"])
        reviewed = await service.preview(**request)
        assert reviewed["can_apply"] and not peer.writes
        assert reviewed["request_service_body_hex"] == "0c0180000119173e" + literal + "3f"
        receipt = await apply(service, reviewed)
        assert receipt["protocol_accepted"] is True and receipt["readback"]["status"] == "match"
        retained = service.journal.receipt(receipt["id"])
        assert peer.writes == [bytes.fromhex(literal)]
        await service.reconcile(operation_id="range_readback", receipt_id=receipt["id"])
        assert peer.writes == [bytes.fromhex(literal)]
        assert service.journal.receipt(receipt["id"]) == retained
        assert library.source(request["draft"]["capture_id"]) == original
        # Source bytes may contain older partial ranges; replacing them can repair
        # that field. New-write qualification does not rewrite historical evidence.
        assert b"ff0101ff" in original
        assert RULES_SHA256 == "03496cdf67d30e34f470f1eb31477776919737ad3f6ebce51d504d698d0b8149"
    finally:
        await close(peer, client, inventory, service)


@pytest.mark.parametrize(
    "fields",
    [
        [255.0] * 4,
        [126, 11, 2, True],
        [126, 11, 2, 2],
        [123, 2, 29, 3],
        [254, 12, 32, 1],
        [256, 1, 1, 1],
    ],
)
def test_request_encoding_rechecks_actual_date_range_admission(fields):
    review = {
        "source": {"object": "calendar,1"},
        "new": {
            "entries": [{"kind": "dateRange", "start": copy.deepcopy(fields), "end": ANY}],
            "encoded_hex": "",
        },
    }
    with pytest.raises(ValueError, match="fully specified date"):
        NativeCalendarWrites._request(review, "127.0.0.1:47808")
