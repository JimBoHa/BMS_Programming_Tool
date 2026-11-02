"""Cancel completed reviews before field dispatch without altering original receipts."""

import copy
import json

import pytest
from bms_tool.native_calendar_drafts import NativeCalendarDrafts
from bms_tool.native_calendar_write import RULES_SHA256 as CALENDAR_RULES
from bms_tool.native_schedule_write import RULES_SHA256 as WEEKLY_RULES
from bms_tool.native_schedule_write import STRING_WRITE_RULES_SHA256

from .test_native_calendar_write import DATE
from .test_native_calendar_write import close as calendar_close
from .test_native_calendar_write import link as calendar_link
from .test_native_schedule_strings import close_parts, string_request, stringtag
from .test_native_schedule_write import draft
from .test_native_schedule_write import link as weekly_link
from .test_schedule_inventory import options


async def domain_link(tmp_path, domain, routed):
    if domain == "calendar":
        peer, client, inventory, library, service, request = await calendar_link(
            tmp_path, routed=routed
        )

        async def preview(operation_id, other=False):
            body = copy.deepcopy(request)
            if other:
                capture = library.save(
                    (await inventory.read(**options(peer, object_ids=["calendar,2"])))["id"]
                )
                body["draft"] = {
                    "capture_id": capture["id"],
                    "object_id": "calendar,2",
                    "entries": [DATE],
                }
                body["expected_review_id"] = NativeCalendarDrafts(library).review(body["draft"])[
                    "id"
                ]
            return await service.preview(**{**body, "operation_id": operation_id})

        async def close():
            await calendar_close(peer, client, inventory, service)
    else:
        parts = await weekly_link(
            tmp_path, routed=routed, primitive=stringtag("old") if domain == "string" else None
        )
        peer, client, inventory, library, service, capture = parts

        async def preview(operation_id, other=False):
            day = 2 if other else 1
            if domain == "string":
                request = string_request(
                    capture,
                    [
                        {
                            "time": [8, 0, 0, 0],
                            "native_type": "CharacterString",
                            "value_text": "changed",
                        }
                    ],
                )
                request["day"] = day
                local = library.review(**request)
            else:
                local = draft(library, capture, day=day)
            return await service.preview(
                operation_id=operation_id,
                draft_id=local["id"],
                operator_name="Authored",
                rationale="Completed review cancellation",
            )

        async def close():
            await close_parts(parts)

    return peer, client, service, preview, close


@pytest.mark.parametrize("domain", ["calendar", "numeric", "string"])
@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_completed_cancel_invalidates_exact_owned_token_and_keeps_unrelated_review(
    tmp_path, domain, routed
):
    peer, client, service, preview, close = await domain_link(tmp_path, domain, routed)
    try:
        first = await preview("owned_cancel_preview")
        assert first["can_apply"], first["reasons"]
        other = await preview("unrelated_preview", True)
        assert other["can_apply"], other["reasons"]
        original = copy.deepcopy(service.plans[other["token"]]["body"])
        reads = len(peer.requests)
        result = service.cancel(first["operation_id"])
        assert result["cancel_requested"] is False and result["reviews_retired"] == 1
        assert len(peer.requests) == reads and not peer.writes
        assert service.plans[other["token"]]["body"] == original
        with pytest.raises(ValueError, match="invalid|already used"):
            await service.apply(
                operation_id="stale_manual_apply",
                token=first["token"],
                review_sha256=first["review_sha256"],
            )
        assert (
            len(peer.requests) == reads
            and not peer.writes
            and not service.journal.status()["records"]
        )
        again = service.cancel(first["operation_id"])
        assert again["reviews_retired"] == 0 and again["cancel_requested"] is False
        assert other["token"] in service.plans
    finally:
        await close()


@pytest.mark.parametrize("domain", ["calendar", "numeric", "string"])
async def test_apply_consumes_valid_review_and_cancel_cannot_rewrite_its_receipt(tmp_path, domain):
    peer, client, service, preview, close = await domain_link(tmp_path, domain, True)
    try:
        plan = await preview("ready_apply_preview")
        assert plan["can_apply"], plan["reasons"]
        raw = await service.apply(
            operation_id="valid_native_apply",
            token=plan["token"],
            review_sha256=plan["review_sha256"],
        )
        receipt = json.loads(raw)
        assert receipt["readback"]["status"] == "match" and len(peer.writes) == 1
        before = service.journal.receipt(receipt["id"])
        result = service.cancel(plan["operation_id"])
        assert result["reviews_retired"] == 0 and result["cancel_requested"] is False
        observation = json.loads(
            await service.reconcile(operation_id="retained_readback", receipt_id=receipt["id"])
        )
        assert observation["readback"]["status"] == "match" and observation["writes_sent"] == 0
        assert len(peer.writes) == 1 and service.journal.receipt(receipt["id"]) == before == raw
    finally:
        await close()


def test_existing_native_authority_seals_remain_unchanged():
    assert CALENDAR_RULES == "03496cdf67d30e34f470f1eb31477776919737ad3f6ebce51d504d698d0b8149"
    assert WEEKLY_RULES == "5fda23c9c4b5a9ac07b621fe90507fe3626a913ba3014778a938750ca28cf98c"
    assert (
        STRING_WRITE_RULES_SHA256
        == "a448c5c8eea93bd61f241fdccd6338da773caa5c96f7f4f015ae0390c32a1374"
    )


@pytest.mark.parametrize("domain", ["calendar", "numeric", "string"])
async def test_completed_review_can_be_cancelled_offline_without_field_queries(tmp_path, domain):
    peer, client, service, preview, close = await domain_link(tmp_path, domain, False)
    try:
        plan = await preview("offline_owned_preview")
        assert plan["can_apply"]
        client.close()
        reads = len(peer.requests)
        result = service.cancel(plan["operation_id"])
        assert result["reviews_retired"] == 1 and not service.plans
        with pytest.raises(ValueError, match="invalid|already used"):
            await service.apply(
                operation_id="offline_stale_apply",
                token=plan["token"],
                review_sha256=plan["review_sha256"],
            )
        assert len(peer.requests) == reads and not peer.writes
    finally:
        await close()
