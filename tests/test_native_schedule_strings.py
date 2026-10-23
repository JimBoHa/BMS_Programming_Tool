"""Strict preserved UTF8 payloads and literal native UDP string/day writes."""

import asyncio
import copy
import hashlib
import json
import tempfile

import pytest
from bacpypes3.constructeddata import AnyAtomic
from bacpypes3.object import ScheduleObject
from bacpypes3.pdu import PDU
from bacpypes3.primitivedata import CharacterString, TagList
from bms_tool import native_schedule_library as library_module
from bms_tool import native_schedule_write as write_module
from bms_tool.native_schedule_library import (
    DRAFT_PROFILE,
    RULES_SHA256,
    STRING_DRAFT_PROFILE,
    STRING_RULES_SHA256,
    NativeScheduleLibrary,
    NativeTransition,
    WeeklyDayDraft,
    digest,
    encoded,
    primitive,
)
from bms_tool.native_schedule_write import STRING_PROFILE, WeeklyWriteJournal
from bms_tool.property_evidence import native_value

from tests.test_native_schedule_library import acquire, request, reseal, saved
from tests.test_native_schedule_write import apply_options, assert_retired, link


def stringtag(text):
    """Independently author BACnet app-tag7 and its length; no SDK encoder oracle."""
    payload = b"\x00" + text.encode("utf-8", "strict")
    length = len(payload)
    header = (
        bytes([0x70 | length])
        if length <= 4
        else b"\x75" + (bytes([length]) if length <= 253 else b"\xfe" + length.to_bytes(2, "big"))
    )
    return header + payload


def string_overrides(atom):
    result = {("schedule,1", p, None): atom for p in ("schedule-default", "present-value")}
    result.update(
        {
            ("schedule,1", "weekly-schedule", day): bytes.fromhex("0eb408000000") + atom + b"\x0f"
            for day in range(1, 8)
        }
    )
    for index, period in ((1, "0e0cff021dff0f"), (2, "1c01800002")):
        result[("schedule,1", "exception-schedule", index)] = (
            bytes.fromhex(period + "2eb4091e0000") + atom + bytes.fromhex("2f3908")
        )
    return result


def string_request(capture, transitions=None, **changes):
    return request(
        capture,
        draft_profile=STRING_DRAFT_PROFILE,
        transitions=transitions
        if transitions is not None
        else [{"time": [8, 0, 0, 0], "native_type": "CharacterString", "value_text": "new"}],
        **changes,
    )


@pytest.fixture(scope="module")
def string_source():
    with tempfile.TemporaryDirectory() as directory:
        report, _, _ = asyncio.run(acquire(directory, overrides=string_overrides(stringtag("old"))))
    assert report["complete"]
    return encoded(report)


@pytest.mark.parametrize(
    "text", ["", "null", "  ", "é", "e\u0301", "🌡", '"\\\x00\r\n\t', "\x00" * 256, "🌡" * 64]
)
def test_literal_string_encoder_preserves_empty_unicode_controls_and_wire_byte_bound(text):
    value = primitive(
        NativeTransition(time=[0, 0, 0, 0], native_type="CharacterString", value_text=text)
    )
    raw = bytes(value.encode().encode().pduData)
    assert raw == stringtag(text)
    decoded = CharacterString.decode(TagList.decode(PDU(raw)))
    assert str(decoded) == text and decoded._encoding == 0


@pytest.mark.parametrize("text", ["a" * 257, "🌡" * 65, "\ud800", "\udfff"])
def test_string_text_overflow_or_surrogate_is_nice_refusal(text):
    with pytest.raises(ValueError):
        primitive(
            NativeTransition(time=[0, 0, 0, 0], native_type="CharacterString", value_text=text)
        )


def test_old_seven_domain_rules_and_request_shapes_remain_exact():
    assert RULES_SHA256 == "3a69e8f5e2de0cc74e21af9db7a0b6607cb1a1388d1667a5c3cd66cc6d1aff6e"
    assert (
        write_module.RULES_SHA256
        == "5fda23c9c4b5a9ac07b621fe90507fe3626a913ba3014778a938750ca28cf98c"
    )
    assert list(library_module.PRIMITIVES) == [
        "Null",
        "Boolean",
        "Unsigned",
        "Integer",
        "Enumerated",
        "Real",
        "Double",
    ]
    old = {"capture_id": "0" * 64, "object_id": "schedule,1", "day": 1, "transitions": []}
    assert WeeklyDayDraft(**old).model_dump() == old
    assert STRING_RULES_SHA256 != RULES_SHA256


def test_valid_capture_literal_null_empty_days_profile_authority_and_restart(
    tmp_path, string_source
):
    library, capture = saved(tmp_path, string_source)
    archive = library.archive(capture["id"])
    selected = capture["objects"][0]
    assert selected["eligible"] and selected["native_type"] == "CharacterString"
    assert (
        selected["draft_profile"] == STRING_DRAFT_PROFILE
        and selected["rules_sha256"] == STRING_RULES_SHA256
    )
    assert selected["days"][0]["transitions"][0]["value_text"] == "old"
    for transitions in (
        [],
        [{"time": [0, 0, 0, 0], "native_type": "Null", "value_text": "null"}],
        [
            {"time": [0, 0, 0, 0], "native_type": "CharacterString", "value_text": ""},
            {"time": [1, 0, 0, 0], "native_type": "CharacterString", "value_text": "null"},
        ],
    ):
        arguments = string_request(capture, transitions)
        reviewed = library.review(**arguments)
        assert reviewed["profile"] == reviewed["format"] == STRING_DRAFT_PROFILE
        assert reviewed["rules_sha256"] == STRING_RULES_SHA256
        assert reviewed["request"]["draft_profile"] == STRING_DRAFT_PROFILE
        exported = library.export_review(reviewed["id"])
        restarted = NativeScheduleLibrary(tmp_path)
        assert restarted.archive(capture["id"]) == archive
        assert restarted.import_review(exported) == reviewed
        assert restarted.export_review(reviewed["id"]) == exported
        forged = json.loads(exported)
        forged["profile"] = forged["format"] = DRAFT_PROFILE
        forged["rules_sha256"] = RULES_SHA256
        forged["id"] = digest({k: v for k, v in forged.items() if k != "id"})
        with pytest.raises(ValueError):
            restarted.import_review(encoded(forged))
        missing = dict(arguments)
        missing.pop("draft_profile")
        with pytest.raises(ValueError, match="explicit UTF8"):
            library.review(**missing)
    assert library.source(capture["id"]) == string_source
    assert reviewed["new"]["encoded_hex"] == "0eb4000000007100b4010000007505006e756c6c0f"


def replace_property_atom(report, prop, index, atom):
    result = copy.deepcopy(report)
    props = next(item for item in result["objects"] if item["object"] == "schedule,1")["properties"]
    row = props[prop] if index is None else props[prop]["elements"][index - 1]
    original = bytes.fromhex(row["encoded_value"]["hex"])
    assert stringtag("old") in original
    raw = original.replace(stringtag("old"), atom)
    row["encoded_value"].update(
        hex=raw.hex(), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
    )
    datatype = ScheduleObject.get_property_type(prop)
    if index is not None:
        datatype = datatype._subtype
    tags = TagList.decode(PDU(raw))
    decoded = datatype.decode(TagList(list(tags)[1:-1]))
    # Truthfully represent the SDK fallback too. Strict raw-tag qualification
    # must refuse this despite an otherwise self-consistent capture/seal.
    row["value"] = native_value(decoded, [])
    return result


@pytest.mark.parametrize(
    "prop,index",
    [
        ("schedule-default", None),
        ("present-value", None),
        *(("weekly-schedule", i) for i in range(1, 8)),
        ("exception-schedule", 1),
        ("exception-schedule", 2),
    ],
)
@pytest.mark.parametrize(
    "atom",
    [bytes.fromhex("720141"), bytes.fromhex("7200ff"), bytes.fromhex("7205e9")],
    ids=["unknown-encoding", "invalid-utf8-fallback", "legacy-latin1"],
)
def test_every_original_default_present_week_exception_atom_refuses_before_lossy_interpretation(
    tmp_path, string_source, prop, index, atom, monkeypatch
):
    source = reseal(replace_property_atom(json.loads(string_source), prop, index, atom))
    original = AnyAtomic.get_value

    def fail_on_bad(self):
        if bytes(self.tagList.encode().pduData) == atom:
            pytest.fail("Invalid String atom reached SDK get_value before strict raw validation")
        return original(self)

    monkeypatch.setattr(AnyAtomic, "get_value", fail_on_bad)
    library, capture = saved(tmp_path, source)
    assert not capture["objects"][0]["eligible"]
    assert any("UTF8" in issue for issue in capture["objects"][0]["issues"])
    assert library.source(capture["id"]) == source
    archive = library.archive(capture["id"])
    assert NativeScheduleLibrary(tmp_path).archive(capture["id"]) == archive
    with pytest.raises(ValueError):
        library.review(**string_request(capture))


async def close_parts(parts):
    peer, client, inventory, _, service, _ = parts
    await service.close()
    await inventory.close()
    client.close()
    peer.close()
    await asyncio.sleep(0.01)


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
@pytest.mark.parametrize("text", ["", "null", 'é\x00\r\n"\\', "\x00" * 256])
async def test_actual_native_udp_string_write_exact_tags_receipt_reconcile_and_passive_restart(
    tmp_path, routed, text
):
    parts = await link(tmp_path, routed=routed, primitive=stringtag("old"))
    peer, client, inventory, library, service, capture = parts
    try:
        reviewed = library.review(
            **string_request(
                capture,
                [
                    {"time": [8, 0, 0, 0], "native_type": "CharacterString", "value_text": text},
                    {"time": [17, 0, 0, 0], "native_type": "Null", "value_text": "null"},
                ],
            )
        )
        plan = await service.preview(
            operation_id="string_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="Local String day replacement",
        )
        assert plan["can_apply"], plan
        assert (
            plan["profile"] == STRING_PROFILE
            and plan["rules_sha256"] == write_module.STRING_WRITE_RULES_SHA256
        )
        raw = await service.apply(**apply_options(plan))
        receipt = json.loads(raw)
        assert (
            receipt["profile"] == STRING_PROFILE
            and receipt["protocol_accepted"]
            and receipt["readback"]["status"] == "match"
        )
        assert peer.writes == [
            (1, bytes.fromhex("0eb408000000") + stringtag(text) + bytes.fromhex("b411000000000f"))
        ]
        assert service.journal.receipt(receipt["id"]) == raw
        assert WeeklyWriteJournal(client.store).receipt(receipt["id"]) == raw
        again = json.loads(
            await service.reconcile(operation_id="string_reconcile", receipt_id=receipt["id"])
        )
        assert (
            again["profile"] == STRING_PROFILE
            and again["rules_sha256"] == write_module.STRING_WRITE_RULES_SHA256
        )
        assert (
            again["read_only"]
            and again["writes_sent"] == 0
            and again["readback"]["status"] == "match"
        )
        assert len(peer.writes) == 1 and not peer.errors
        assert_retired(client)
    finally:
        await close_parts(parts)


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize(
    "mode,accepted,match",
    [("drop", False, True), ("reject", False, False), ("partial_error", False, False)],
)
async def test_string_ack_loss_and_negative_reply_keep_one_attempt_uncertainty(
    tmp_path, routed, mode, accepted, match
):
    parts = await link(tmp_path, routed=routed, primitive=stringtag("old"))
    peer, client, _, library, service, capture = parts
    try:
        reviewed = library.review(**string_request(capture))
        plan = await service.preview(
            operation_id="uncertain_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="Local uncertainty test",
        )
        assert plan["can_apply"], plan
        peer.mode = mode
        raw = await service.apply(**apply_options(plan))
        receipt = json.loads(raw)
        assert receipt["may_have_applied"] and receipt["protocol_accepted"] is accepted
        assert (receipt["readback"]["status"] == "match") is match
        assert len(peer.writes) == 1 and not peer.errors
        assert_retired(client)
    finally:
        await close_parts(parts)


async def test_string_oversize_day_is_offline_exportable_but_never_dispatches(tmp_path):
    parts = await link(tmp_path, primitive=stringtag("old"))
    peer, _, _, library, service, capture = parts
    try:
        reviewed = library.review(
            **string_request(
                capture,
                [
                    {
                        "time": [i, 0, 0, 0],
                        "native_type": "CharacterString",
                        "value_text": "x" * 256,
                    }
                    for i in range(3)
                ],
            )
        )
        assert len(library.export_review(reviewed["id"])) > 480
        plan = await service.preview(
            operation_id="oversize_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="Oversize String review",
        )
        assert not plan["can_apply"] and any("480-byte" in reason for reason in plan["reasons"])
        assert not peer.writes
    finally:
        await close_parts(parts)


@pytest.mark.parametrize(
    "kind", ["Null", "Boolean", "Unsigned", "Integer", "Enumerated", "Real", "Double"]
)
def test_all_legacy_transition_models_still_refuse_empty_text(kind):
    with pytest.raises(ValueError):
        NativeTransition(time=[0, 0, 0, 0], native_type=kind, value_text="")


@pytest.mark.parametrize(
    "atom",
    [
        bytes.fromhex("720341"),
        bytes.fromhex("720441"),
        bytes.fromhex("720241"),
        bytes.fromhex("72ff41"),
        bytes.fromhex("70"),
        bytes.fromhex("7300c080"),
        bytes.fromhex("7400eda080"),
        bytes.fromhex("7300e282"),
    ],
)
def test_other_original_encoding_and_utf8_malformations_refuse_direct_raw_guard(atom):
    tags = TagList.decode(PDU(atom))
    with pytest.raises(ValueError):
        library_module.strict_character_strings(tags)


@pytest.mark.parametrize(
    "prop,index",
    [
        ("schedule-default", None),
        ("present-value", None),
        ("weekly-schedule", 7),
        ("exception-schedule", 2),
    ],
)
def test_mixed_native_domain_capture_stays_preserved_but_ineligible(
    tmp_path, string_source, prop, index
):
    source = reseal(
        replace_property_atom(json.loads(string_source), prop, index, bytes.fromhex("11"))
    )
    library, capture = saved(tmp_path, source)
    assert not capture["objects"][0]["eligible"]
    assert library.source(capture["id"]) == source
    with pytest.raises(ValueError):
        library.review(**string_request(capture))


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("phase", ["before", "after"])
async def test_string_cancellation_preserves_dispatch_uncertainty_and_owned_retirement(
    tmp_path, routed, phase
):
    parts = await link(tmp_path, routed=routed, primitive=stringtag("old"))
    peer, client, _, library, service, capture = parts
    try:
        reviewed = library.review(**string_request(capture))
        plan = await service.preview(
            operation_id="cancel_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="String cancellation test",
        )
        assert plan["can_apply"]
        if phase == "before":
            peer.hold_property = "schedule-default"
            peer.entered.clear()
        else:
            peer.mode = "hold"
        arguments = apply_options(plan)
        task = asyncio.create_task(service.apply(**arguments))
        await asyncio.wait_for(
            peer.entered.wait() if phase == "before" else peer.write_entered.wait(), 1
        )
        assert service.cancel(arguments["operation_id"])["cancel_requested"]
        raw = await task
        receipt = json.loads(raw)
        assert receipt["profile"] == STRING_PROFILE
        assert receipt["dispatch_started"] is (phase == "after")
        assert receipt["may_have_applied"] is (phase == "after")
        assert len(peer.writes) == int(phase == "after")
        assert WeeklyWriteJournal(client.store).receipt(receipt["id"]) == raw
        assert_retired(client)
    finally:
        await close_parts(parts)


async def test_fresh_bad_unselected_string_atom_blocks_apply_before_dispatch(tmp_path):
    parts = await link(tmp_path, primitive=stringtag("old"))
    peer, _, _, library, service, capture = parts
    try:
        reviewed = library.review(**string_request(capture))
        plan = await service.preview(
            operation_id="fresh_string_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="Fresh String context guard",
        )
        assert plan["can_apply"]
        peer.days[6] = bytes.fromhex("0eb4080000007200ff0f")
        raw = await service.apply(**apply_options(plan))
        receipt = json.loads(raw)
        assert (
            not receipt["dispatch_started"] and not receipt["may_have_applied"] and not peer.writes
        )
        assert any("UTF8" in e for e in receipt["errors"])
    finally:
        await close_parts(parts)


@pytest.mark.parametrize("routed", [False, True])
async def test_string_result_journal_failure_keeps_exact_durable_unresolved_intent(
    tmp_path, routed, monkeypatch
):
    import sqlite3

    parts = await link(tmp_path, routed=routed, primitive=stringtag("old"))
    peer, client, _, library, service, capture = parts
    try:
        reviewed = library.review(**string_request(capture))
        plan = await service.preview(
            operation_id="intent_string_preview",
            draft_id=reviewed["id"],
            operator_name="Test operator",
            rationale="String durable intent failure",
        )
        assert plan["can_apply"]

        def fail_result(_):
            raise sqlite3.OperationalError("Authored String result-store failure")

        monkeypatch.setattr(service.journal, "result", fail_result)
        receipt = json.loads(await service.apply(**apply_options(plan)))
        assert receipt["protocol_accepted"] and receipt["journal_error"] and len(peer.writes) == 1
        raw = WeeklyWriteJournal(client.store).receipt(receipt["id"])
        unresolved = json.loads(raw)
        assert (
            unresolved["profile"] == STRING_PROFILE and unresolved["journal_state"] == "intent_only"
        )
        assert unresolved["dispatch_started"] is None and unresolved["protocol_status"] == "unknown"
        assert unresolved["may_have_applied"] and unresolved["readback"]["status"] == "unknown"
        assert WeeklyWriteJournal(client.store).receipt(receipt["id"]) == raw
        forged = copy.deepcopy(unresolved)
        forged["profile"] = write_module.PROFILE
        forged["rules_sha256"] = write_module.RULES_SHA256
        forged = write_module.seal({k: v for k, v in forged.items() if k != "evidence_sha256"})
        with pytest.raises(ValueError, match="conflicts"):
            WeeklyWriteJournal._checked(encoded(forged), forged["id"])
        assert_retired(client)
    finally:
        await close_parts(parts)


@pytest.mark.parametrize(
    "prop,index",
    [
        ("schedule-default", None),
        ("present-value", None),
        *(("weekly-schedule", i) for i in range(1, 8)),
        ("exception-schedule", 1),
        ("exception-schedule", 2),
    ],
)
@pytest.mark.parametrize(
    "atom",
    [bytes.fromhex("75020058"), bytes.fromhex("f2070058")],
    ids=["nonminimal-length", "nonminimal-tag-number"],
)
def test_captured_string_tag_header_normalization_is_refused_before_interpretation(
    tmp_path, string_source, prop, index, atom, monkeypatch
):
    source = reseal(replace_property_atom(json.loads(string_source), prop, index, atom))
    original = AnyAtomic.get_value

    def fail_on_normalized_header(self):
        if bytes(self.tagList.encode().pduData) == bytes.fromhex("720058"):
            pytest.fail("Noncanonical original String header reached SDK interpretation")
        return original(self)

    monkeypatch.setattr(AnyAtomic, "get_value", fail_on_normalized_header)
    library, capture = saved(tmp_path, source)
    assert not capture["objects"][0]["eligible"]
    assert any("property-tag" in issue for issue in capture["objects"][0]["issues"])
    assert library.source(capture["id"]) == source


@pytest.mark.parametrize("routed", [False, True], ids=["direct", "routed"])
async def test_actual_wire_header_normalization_is_explicit_while_utf8_payload_stays_exact(
    tmp_path, routed
):
    # This is valid text with a nonminimal APP7 length header. Inventory already
    # canonicalizes headers; the String profile qualifies preserved payloads and
    # captured encoded_value, not an equality claim about original UDP headers.
    parts = await link(tmp_path, routed=routed, primitive=bytes.fromhex("750100"))
    peer, _, _, library, _, capture = parts
    try:
        assert capture["objects"][0]["eligible"]
        report = json.loads(library.source(capture["id"]))
        item = next(item for item in report["objects"] if item["object"] == "schedule,1")
        row = item["properties"]["schedule-default"]
        assert row["encoded_value"]["hex"] == "3e71003f"
        assert "3e7501003f" in row["transport_evidence"]["udp_payload_hex"]
        reviewed = library.review(**string_request(capture, []))
        assert reviewed["profile"] == STRING_DRAFT_PROFILE
        assert not peer.writes and not peer.errors
    finally:
        await close_parts(parts)
