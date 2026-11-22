"""Maintained contact assignments on authored native images and a loopback BACnet controller."""

import pytest
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier, Unsigned
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_contact_points import contact_options
from bms_tool.native_inputs import archive, encoded, native_record, raw_property, replace_properties
from bms_tool.native_runtime_io import compile_io, effective_source, qualified_io_source
from bms_tool.native_runtime_io_transfer import IOReadback

from .test_native_applications import native_link as native_link
from .test_native_runtime_io import confirm, identity, review, source
from .test_native_runtime_io import io_link as io_link

INSTANCE = 3330123


def addition(polarity="normal"):
    return dict(
        action="allocate-binary",
        slot=2,
        object_instance=INSTANCE,
        name="Example contact",
        polarity=polarity,
    )


def moving():
    return dict(action="binary-input-terminal", slot=3, expected_slot=2, object_instance=INSTANCE)


def turning(polarity="reverse", slot=2):
    return dict(
        action="binary-input-polarity",
        slot=slot,
        expected_slot=slot,
        object_instance=INSTANCE,
        polarity=polarity,
    )


def find_contact(app):
    return next(r for r in app.records if app.reader.scalar(r, 75) == f"binary-input,{INSTANCE}")


def contact_files(compressed=False):
    original = source(compressed=compressed)
    app, _ = effective_source(original, identity())
    current = {**original, 3: app.source}
    data, _ = compile_io(current, identity(), addition())
    return {**current, 3: data}


@pytest.mark.parametrize("compressed", [True, False])
def test_move_and_reverse_preserve_the_source_identity_wires_and_state_labels(compressed):
    files = contact_files(compressed)
    app = MoiIdentity(files[3])
    selected = find_contact(app)
    recs = [
        replace_properties(
            app,
            r,
            {
                4: encoded(CharacterString("Operating")),
                46: encoded(CharacterString("Stopped")),
                15: encoded(Unsigned(17)),
            },
        )
        if r is selected
        else app.data[r["offset"] : r["end_offset"]]
        for r in app.records
    ]
    wire = native_record(127, 670, [(60123, encoded(ObjectIdentifier((3, INSTANCE))))])
    files[3] = archive(app, recs + [wire])
    app, _, cap, _ = qualified_io_source(files, identity())
    cat = contact_options(app, cap)
    assert cat["available_slots"] == [3] and cat["contacts"][0]["polarity"] == "normal"
    for edit, delta in [(moving(), {31, 519}), (turning(), {84})]:
        out, proof = compile_io(files, identity(), edit)
        after = MoiIdentity(out)
        assert (
            proof["graph_wires_changed"] is False
            and proof["original_record_count"] == proof["output_record_count"]
        )
        for before, end in zip(app.records, after.records, strict=True):
            if before["class_id"] != 242:
                assert (
                    app.data[before["offset"] : before["end_offset"]]
                    == after.data[end["offset"] : end["end_offset"]]
                )
                continue
            assert {
                k
                for k in before["properties"]
                if raw_property(app, before, k) != raw_property(after, end, k)
            } == delta
            assert after.reader.scalar(end, 4) == "Operating" and after.reader.scalar(end, 15) == 17


@pytest.mark.parametrize(
    "edit",
    [
        moving() | {"slot": 1},
        moving() | {"expected_slot": 1},
        turning("normal"),
        moving() | {"polarity": "reverse"},
        turning() | {"slot": 3},
        addition() | {"object_instance": INSTANCE + 1, "name": "example CONTACT", "slot": 3},
    ],
)
def test_stale_occupied_duplicate_or_mixed_configuration_is_rejected(edit):
    with pytest.raises(ValueError):
        compile_io(contact_files(), identity(), edit)


def test_unknown_input_ownership_and_unresolved_program_reference_are_rejected():
    files = source()
    app = MoiIdentity(files[3])
    for prop, value, msg in [
        (31, CharacterString("UI IN2"), "could own"),
        (65010, ObjectIdentifier((3, INSTANCE)), "occurs in the retained image"),
    ]:
        extra = native_record(127, 55, [(prop, encoded(value))])
        rows = [app.data[r["offset"] : r["end_offset"]] for r in app.records]
        with pytest.raises(ValueError, match=msg):
            compile_io(files | {3: archive(app, rows + [extra])}, identity(), addition())


def test_persistent_terminal_setting_that_would_undo_a_move_is_rejected():
    files = contact_files()
    # An inline saved parameter pins the published Device_Type to the original terminal.
    body = (
        ((3 << 22) | INSTANCE).to_bytes(4, "big")
        + (31).to_bytes(2, "big")
        + bytes([0x4F, 7])
        + (242).to_bytes(2, "big")
        + b"\x1e"
        + encoded(CharacterString("UI IN2"))
        + b"\x1f"
        + bytes(5)
        + b"\x12\x34"
    )
    files[11] += (len(body) + 2).to_bytes(2, "big") + body
    with pytest.raises(ValueError, match="Saved parameters would reinstate"):
        compile_io(files, identity(), moving())


def test_http_contact_inventory_is_private_local_and_bound_to_one_capture(tmp_path):
    from bms_tool.app import create_app
    from fastapi.testclient import TestClient

    app = create_app(tmp_path)
    target = {"address": "127.0.0.1:47999", "router": None, "dnet": None}
    device = {**target, "device": identity()["device"]}
    native = app.state.native_applications
    capture = native.storage.save(
        {
            **device,
            "target": target,
            "identity": identity(),
            "connector_config": {},
            "source_identity_matches": True,
        },
        contact_files(),
    )
    exact = {
        **device,
        "capture_id": capture["id"],
        "snapshot_sha256": capture["evidence_sha256"],
        "operation_id": "authored-contact-inventory",
    }
    base = "/api/bacnet/controller/native-application/runtime-io"
    with TestClient(app) as client:
        headers = {"X-Studio-Token": client.get("/api/session").json()["token"]}
        for path, data in [("/contact-sources", device), ("/contacts", exact)]:
            assert client.post(base + path, json=data).status_code == 403
        listing = client.post(base + "/contact-sources", json=device, headers=headers)
        assert listing.status_code == 200, listing.text
        assert [s["capture_id"] for s in listing.json()["sources"]] == [capture["id"]]
        other = {**device, "device": "device,5137"}
        assert not client.post(base + "/contact-sources", json=other, headers=headers).json()[
            "sources"
        ]
        result = client.post(base + "/contacts", json=exact, headers=headers)
        assert result.status_code == 200, result.text
        catalog = result.json()
        assert catalog["contacts"][0]["object"] == f"binary-input,{INSTANCE}"
        assert catalog["available_slots"] == [3]
        assert catalog["controller_queries"] is catalog["controller_writes"] is False
        for mismatch in [other, {"snapshot_sha256": "0" * 64}]:
            stale = client.post(base + "/contacts", json={**exact, **mismatch}, headers=headers)
            assert stale.status_code == 422 and "exact controller" in stale.text
        assert not native.storage.receipts()
        assert client.get("/api/session").json()["field_network_open"] is False


async def test_add_move_polarity_and_readback_follow_physical_contact_state(io_link):
    peer, native, target, svc = io_link
    peer.contact_terminals = {2: 1, 3: 0}
    for edit, state in [(addition(), 1), (moving(), 0), (turning(slot=3), 1)]:
        _, plan = await review(io_link, edit)
        with pytest.raises(ValueError, match="contact polarity"):
            await svc.apply(confirm(plan))
        rec = await svc.apply(confirm(plan, input_wiring_confirmed=True))
        result = rec["result"]
        assert result["status"] == "verified", result
        assert result["published_io"]["present_value"] == state
        assert result["published_io"]["519"] == edit["slot"]
        assert result["published_io"]["84"] == int(edit.get("polarity") == "reverse")
        assert result["published_io"]["75"] == f"binary-input,{INSTANCE}"
    applies = peer.events.count(("state", "start-restore"))
    peer.contact_terminals[3] = 1
    back = await svc.readback(
        IOReadback(**target, receipt_id=rec["intent"]["id"], operation_id="contact-readback")
    )
    assert back["latest_readback"]["published_io"]["present_value"] == 0
    assert peer.events.count(("state", "start-restore")) == applies == 3
    assert not native.bacnet.commands


async def test_contact_polarity_changing_after_review_stops_before_transfer(io_link):
    peer, _, _, svc = io_link
    peer.files = contact_files()
    _, plan = await review(io_link, turning())
    peer.contact_polarity_override = 1
    rec = await svc.apply(confirm(plan, input_wiring_confirmed=True))
    assert rec["result"]["status"] == "not_sent" and ("state", "start-restore") not in peer.events


async def test_allocator_advancing_during_backup_stops_contact_allocation(io_link, monkeypatch):
    peer, native, _, service = io_link
    _, plan = await review(io_link, addition())
    original = native.capture_session

    async def capture(*args, **kwargs):
        result = await original(*args, **kwargs)
        peer.next_input = INSTANCE + 1
        return result

    monkeypatch.setattr(native, "capture_session", capture)
    receipt = await service.apply(confirm(plan, input_wiring_confirmed=True))
    assert receipt["result"]["status"] == "not_sent"
    assert any("allocator" in message for message in receipt["result"]["errors"])
    assert ("state", "start-restore") not in peer.events


async def test_out_of_service_contact_readback_leaves_uncertainty_without_another_write(io_link):
    peer, _, target, svc = io_link
    _, plan = await review(io_link, addition("reverse"))
    peer.contact_oos = True
    rec = await svc.apply(confirm(plan, input_wiring_confirmed=True))
    assert rec["pending"] and rec["result"]["status"] == "unknown"
    peer.contact_oos = False
    back = await svc.readback(
        IOReadback(**target, receipt_id=rec["intent"]["id"], operation_id="contact-recovery")
    )
    assert back["latest_readback"]["published_io"]["84"] == 1 and not back["pending"]
    assert peer.events.count(("state", "start-restore")) == 1


async def test_implicit_polarity_on_move_is_preserved_and_rechecked(io_link):
    peer, _, _, svc = io_link
    files = contact_files()
    app = MoiIdentity(files[3])
    row = find_contact(app)
    new = native_record(
        242,
        INSTANCE,
        [(pid, raw_property(app, row, pid)[:-1]) for pid in row["properties"] if pid != 84],
    )
    peer.files = files | {
        3: archive(
            app, [new if r is row else app.data[r["offset"] : r["end_offset"]] for r in app.records]
        )
    }
    peer.implicit_polarity = 1
    _, plan = await review(io_link, moving())
    assert plan["live_guard"]["polarity"] == 1
    peer.implicit_polarity = 0
    refused = await svc.apply(confirm(plan, input_wiring_confirmed=True))
    assert (
        refused["result"]["status"] == "not_sent" and ("state", "start-restore") not in peer.events
    )
    peer.implicit_polarity = 1
    _, plan = await review(io_link, moving())
    rec = await svc.apply(confirm(plan, input_wiring_confirmed=True))
    assert rec["result"]["status"] == "verified", rec["result"]
    assert rec["result"]["published_io"]["84"] == 1
