"""Author-created output records and a loopback controller with real BACnet priorities."""

from types import MethodType

import pytest
from bacpypes3.apdu import ReadPropertyACK
from bacpypes3.app import Application
from bacpypes3.constructeddata import Any
from bacpypes3.errors import ExecutionError
from bacpypes3.local.analog import AnalogOutputObject
from bacpypes3.local.binary import BinaryOutputObject
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    TagList,
    Unsigned,
)
from bms_tool.connections import Bacnet
from bms_tool.moi_identity import MoiIdentity
from bms_tool.native_inputs import archive, encoded, native_record, raw_property
from bms_tool.native_output_points import output_options
from bms_tool.native_runtime_io import compile_io, effective_source
from bms_tool.native_runtime_io_transfer import IOReadback
from bms_tool.storage import Store

from .test_native_applications import native_link as native_link
from .test_native_applications import port
from .test_native_runtime_io import confirm, identity, review, source
from .test_native_runtime_io import io_link as io_link


def configured(*, extra=(), other=(), compressed=False):
    files = source(compressed=compressed)
    app, _ = effective_source(files, identity())
    records = [app.data[r["offset"] : r["end_offset"]] for r in app.records if r["class_id"] != 239]
    for cid, kind, serial, name, slot, label, fields in (
        (
            239,
            4,
            71,
            "Example relay",
            1,
            "BO OUT1",
            [
                (4, CharacterString("Run")),
                (46, CharacterString("Idle")),
                (518, Enumerated(0)),
                (931, Enumerated(83)),
                (33, Unsigned(9)),
            ],
        ),
        (241, 1, 72, "Example modulator", 5, "CO OUT2", [(117, Enumerated(98)), (3478, Real(120))]),
    ):
        props = [
            (32527, CharacterString(f"{app.ref}/{kind}_{serial}")),
            (75, ObjectIdentifier((kind, serial))),
            (2390, CharacterString(name)),
            (28, CharacterString("Independent fixture")),
            (31, CharacterString(label)),
            (990, Unsigned(slot)),
            *fields,
            *extra,
        ]
        records.append(native_record(cid, serial, [(k, encoded(v)) for k, v in props]))
    return {**files, 3: archive(app, records + list(other))}


def proposal(mode):
    binary = mode == "binary"
    return dict(
        action=f"allocate-{mode}-output",
        expected_slot=1 if binary else 5,
        template_instance=71 if binary else 72,
        slot=3 if binary else 4,
        object_instance=3300123,
        name="Independent test output",
    )


@pytest.mark.parametrize("mode", ["binary", "proportional"])
@pytest.mark.parametrize("compressed", [False, True])
def test_independent_outputs_preserve_original_points_and_graph(mode, compressed):
    files = configured(compressed=compressed)
    baseline, _ = effective_source(files, identity())
    options = {o["mode"]: o for o in output_options(baseline)}
    assert options["binary"]["available_slots"] == [2, 3, 4]
    assert options["proportional"]["available_slots"] == [4]
    edit = proposal(mode)
    out, proof = compile_io(files, identity(), edit)
    after = MoiIdentity(out)
    for old, new in zip(baseline.records, after.records[:-1], strict=True):
        assert (
            baseline.data[old["offset"] : old["end_offset"]]
            == after.data[new["offset"] : new["end_offset"]]
        )
    new = after.records[-1]
    assert next(iter(new["properties"])) == 32527
    assert after.reader.scalar(new, 75) == proof["object_id"]
    assert (
        after.reader.scalar(new, 990) == edit["slot"]
        and after.reader.scalar(new, 2390) == edit["name"]
    )
    assert 33 not in new["properties"] and proof["graph_wires_changed"] is False
    assert after.reader.scalar(new, 4 if mode == "binary" else 3478) == (
        "Run" if mode == "binary" else 120
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(slot=5),
        dict(slot=1),
        dict(template_instance=72),
        dict(template_instance=3300123),
        dict(name="EXAMPLE RELAY"),
        dict(object_instance=71),
        dict(expected_slot=2),
    ],
)
def test_incompatible_stale_or_colliding_edits_rejected(change):
    with pytest.raises(ValueError):
        compile_io(configured(), identity(), proposal("binary") | change)


def test_unqualified_template_ambiguous_occupancy_and_existing_reference_rejected():
    extra = [(60000, CharacterString("unknown hardware setting"))]
    with pytest.raises(ValueError, match="unqualified"):
        compile_io(configured(extra=extra), identity(), proposal("binary"))
    for kind, value, message in [
        (990, Unsigned(3), "could own"),
        (60001, ObjectIdentifier((4, 3300123)), "occurs in the retained image"),
        (60001, CharacterString("8-2/4_3300123"), "occurs in the retained image"),
    ]:
        orphan = native_record(127, 44, [(kind, encoded(value))])
        with pytest.raises(ValueError, match=message):
            compile_io(configured(other=[orphan]), identity(), proposal("binary"))


def test_configurable_outputs_share_an_occupancy_map_and_preserve_slot_encodings():
    from bacpypes3.primitivedata import ApplicationTag

    files = configured()
    app, _ = effective_source(files, identity())
    binary = next(r for r in app.records if r["class_id"] == 239)
    from bms_tool.native_inputs import replace_properties

    def payload(tag, data):
        return bytes(ApplicationTag(tag, data).encode().pduData)

    edited = replace_properties(
        app,
        binary,
        {
            31: payload(7, b"\x04" + "BO OUT1".encode("utf-16-be")),
            990: payload(2, b"\x00\x01"),
            519: payload(2, b"\x00\x01"),
        },
    )
    files[3] = archive(
        app,
        [edited if r is binary else app.data[r["offset"] : r["end_offset"]] for r in app.records],
    )
    move = dict(action="binary-output-terminal", object_instance=71, expected_slot=1, slot=4)
    new, result = compile_io(files, identity(), move)
    moved = MoiIdentity(new)
    point = next(r for r in moved.records if r["class_id"] == 239)
    assert raw_property(moved, point, 31)[:-1] == payload(
        7, b"\x04" + "CO OUT1".encode("utf-16-be")
    )
    assert (
        raw_property(moved, point, 990)
        == raw_property(moved, point, 519)
        == payload(2, b"\x00\x04") + b"\x2f"
    )
    assert result["changes"][0]["after_signal"] == "externally powered 24 VAC triac"
    options = {r["mode"]: r for r in output_options(moved)}
    assert not options["proportional"]["available_slots"]
    assert options["binary"]["available_slots"] == [1, 2, 3]
    with pytest.raises(ValueError, match="free compatible"):
        compile_io(files, identity(), move | {"slot": 5})
    # Both configurable positions can accept a BO when the corresponding AO is absent.
    without_ao = archive(
        app, [app.data[r["offset"] : r["end_offset"]] for r in app.records if r["class_id"] != 241]
    )
    _, fifth = compile_io(files | {3: without_ao}, identity(), proposal("binary") | {"slot": 5})
    assert fifth["changes"][0]["after_device_type"] == "CO OUT2"


def test_proportional_move_preserves_same_point_and_scaling():
    files = configured()
    move = dict(action="proportional-output-terminal", object_instance=72, expected_slot=5, slot=4)
    new, r = compile_io(files, identity(), move)
    app = MoiIdentity(new)
    obj = next(x for x in app.records if app.reader.scalar(x, 75) == "analog-output,72")
    assert (
        app.reader.scalar(obj, 31),
        app.reader.scalar(obj, 990),
        app.reader.scalar(obj, 3478),
    ) == ("CO OUT1", 4, 120)
    assert r["original_record_count"] == r["output_record_count"]
    with pytest.raises(ValueError):
        compile_io(files, identity(), move | {"slot": 3})


@pytest.fixture
async def output_link(io_link):
    peer, native, target, service = io_link
    peer.files = configured()
    peer.next_input = 3200100
    base = peer.do_ReadPropertyRequest
    peer.force_active = False
    peer.wrong_slot_alias = False
    peer.command_test_object = None
    original_write = peer.do_WritePropertyRequest

    async def write(self, request):
        if (
            request.objectIdentifier == self.command_test_object
            and int(request.propertyIdentifier) == 85
            and int(request.priority or 16) == 8
        ):
            return await Application.do_WritePropertyRequest(self, request)
        return await original_write(request)

    async def read(self, request):
        obj, pid = request.objectIdentifier, int(request.propertyIdentifier)
        if int(obj[0]) not in (1, 4):
            return await base(request)
        app = MoiIdentity(self.files[3])
        r = next((r for r in app.records if app.reader.scalar(r, 75) == str(obj)), None)
        if r is None:
            raise ExecutionError(errorClass="object", errorCode="unknown-object")
        if pid in (85, 87, 104, 111, 103, 81):
            point = self.get_object_id(obj)
            if point is None:
                config = dict(
                    objectIdentifier=obj,
                    objectName=app.reader.scalar(r, 2390),
                    presentValue=0,
                    relinquishDefault=0,
                    outOfService=False,
                    reliability="no-fault-detected",
                )
                point = (
                    BinaryOutputObject(**config)
                    if int(obj[0]) == 4
                    else AnalogOutputObject(**config, units="percent")
                )
                self.add_object(point)
            if self.force_active and pid == 85:
                value = Any(Enumerated(1) if int(obj[0]) == 4 else Real(50))
            else:
                return await Application.do_ReadPropertyRequest(self, request)
        elif pid == 519 and int(obj[0]) == 1:
            value = Any(Unsigned(1 if self.wrong_slot_alias else app.reader.scalar(r, 990)))
        else:
            raw = raw_property(app, r, 2390 if pid == 77 else pid)
            if raw is None:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
            value = Any(TagList.decode(PDUData(raw[:-1])))
        return await self.response(
            ReadPropertyACK(
                context=request,
                objectIdentifier=obj,
                propertyIdentifier=request.propertyIdentifier,
                propertyValue=value,
            )
        )

    peer.do_ReadPropertyRequest = MethodType(read, peer)
    peer.do_WritePropertyRequest = MethodType(write, peer)
    return peer, native, target, service


@pytest.mark.parametrize(
    ("mode", "slot", "values"),
    [("binary", 3, [1, 0]), ("binary", 4, [1, 0]), ("proportional", 4, [0, 25, 50, 75, 100])],
)
async def test_allocate_verify_command_release_on_owned_peer(output_link, mode, slot, values):
    peer, native, target, service = output_link
    _, plan = await review(output_link, proposal(mode) | {"slot": slot})
    with pytest.raises(ValueError, match="connected load"):
        await service.apply(confirm(plan))
    assert not any("start-restore" in str(e) for e in peer.events)
    receipt = await service.apply(confirm(plan, output_wiring_confirmed=True))
    assert receipt["result"]["status"] == "verified", receipt["result"]
    assert receipt["result"]["published_io"]["neutral_present_value"] == 0
    with pytest.raises(ValueError, match="already consumed"):
        await service.apply(confirm(plan, output_wiring_confirmed=True))
    obj = plan["compilation"]["object_id"]
    peer.command_test_object = ObjectIdentifier(obj)
    broker = native.bacnet
    for value in values:
        cmd = await broker.plan_write(target["address"], obj, value, 8)
        applied = await broker.apply_write(cmd["token"])
        try:
            observed = float(peer.get_object_id(ObjectIdentifier(obj)).presentValue)
            assert observed == value
        finally:
            released = await broker.release(applied["command"])
            assert released["released"]
        assert float(peer.get_object_id(ObjectIdentifier(obj)).presentValue) == 0
    assert not broker.commands


async def test_non_neutral_publication_is_uncertain_and_readback_does_not_replay(output_link):
    peer, _, target, service = output_link
    _, plan = await review(output_link, proposal("binary"))
    peer.force_active = True
    r = await service.apply(confirm(plan, output_wiring_confirmed=True))
    assert (
        r["pending"] and r["result"]["may_have_applied"] and "neutral" in str(r["result"]["errors"])
    )
    writes = peer.events.count(("state", "start-restore"))
    assert writes == 1
    peer.force_active = False
    rb = await service.readback(
        IOReadback(**target, operation_id="output-readback", receipt_id=r["intent"]["id"])
    )
    assert rb["latest_readback"]["status"] == "verified" and not rb["pending"]
    assert peer.events.count(("state", "start-restore")) == writes


async def test_proportional_slot_disagreement_rejects_review(output_link):
    peer, _, _, _ = output_link
    peer.wrong_slot_alias = True
    with pytest.raises(ValueError, match="slot and slot A disagree"):
        await review(output_link, proposal("proportional"))
    assert ("state", "start-restore") not in peer.events


@pytest.mark.parametrize(
    "mode,instance,source_slot,value",
    [
        ("proportional", 72, 5, 42.0),
        ("binary", 71, 1, 1),
    ],
)
async def test_move_output_preserves_identity_and_refuses_existing_command(
    output_link,
    tmp_path,
    mode,
    instance,
    source_slot,
    value,
):
    peer, _, target, service = output_link
    edit = dict(
        action=f"{mode}-output-terminal",
        object_instance=instance,
        expected_slot=source_slot,
        slot=4,
    )
    obj = ObjectIdentifier((1 if mode == "proportional" else 4, instance))
    peer.command_test_object = obj
    operator = Bacnet(Store(tmp_path / "second-operator"))
    await operator.connect(f"127.0.0.1:{port()}", instance=18001)
    try:
        command = await operator.plan_write(target["address"], str(obj), value, 8)
        issued = await operator.apply_write(command["token"])
        try:
            with pytest.raises(ValueError, match="existing output command"):
                await review(output_link, edit)
        finally:
            assert (await operator.release(issued["command"]))["released"]
    finally:
        await operator.disconnect()
    _, plan = await review(output_link, edit)
    result = await service.apply(confirm(plan, output_wiring_confirmed=True))
    assert result["result"]["status"] == "verified", result["result"]
    point = result["result"]["published_io"]
    assert (point["75"], point["77"], point["31"], point["990"]) == (
        str(obj),
        "Example modulator" if mode == "proportional" else "Example relay",
        "CO OUT1",
        4,
    )
    if mode == "proportional":
        assert point["519"] == 4
    else:
        assert point["518"] == 0


async def test_command_arriving_during_backup_prevents_binary_move(
    output_link, tmp_path, monkeypatch
):
    peer, native, target, service = output_link
    edit = dict(action="binary-output-terminal", object_instance=71, expected_slot=1, slot=4)
    _, plan = await review(output_link, edit)
    peer.command_test_object = ObjectIdentifier("binary-output,71")
    operator = Bacnet(Store(tmp_path / "operator"))
    await operator.connect(f"127.0.0.1:{port()}", instance=18002)
    original = native.capture_session

    async def capture(*args, **kwargs):
        result = await original(*args, **kwargs)
        command = await operator.plan_write(target["address"], "binary-output,71", 1, 8)
        await operator.apply_write(command["token"])
        return result

    monkeypatch.setattr(native, "capture_session", capture)
    try:
        with pytest.raises(ValueError, match="connected load"):
            await service.apply(confirm(plan))
        r = await service.apply(confirm(plan, output_wiring_confirmed=True))
        assert r["result"]["status"] == "not_sent" and "existing output command" in str(
            r["result"]["errors"]
        )
        assert ("state", "start-restore") not in peer.events
    finally:
        for command in list(operator.commands):
            assert (await operator.release(command))["released"]
        await operator.disconnect()


async def test_restore_original_after_two_independent_allocations(output_link):
    _, native, target, service = output_link
    original = await native.capture(**target, operation_id="retain-initial-outputs")
    for mode, instance in (("binary", 3300123), ("proportional", 3300124)):
        _, plan = await review(
            output_link, proposal(mode) | {"object_instance": instance, "name": f"Trial {mode}"}
        )
        result = await service.apply(confirm(plan, output_wiring_confirmed=True))
        assert result["result"]["status"] == "verified", result["result"]
    history = await native.preview_snapshot_restore(
        **target,
        restore_capture_id=original["id"],
        restore_snapshot_sha256=original["snapshot_evidence_sha256"],
        operation_id="review-original-outputs",
    )
    restored = await native.apply_snapshot_restore(
        operation_id="restore-original-outputs",
        token=history["token"],
        review_sha256=history["review_sha256"],
        historical_application_confirmed=True,
        application_transfer_confirmed=True,
    )
    assert restored["result"]["status"] == "verified", restored["result"]
    _, files = native.storage.load(original["id"])
    peer = output_link[0]
    before, _ = effective_source(files, identity())
    after, _ = effective_source(peer.files, identity())
    assert after.data == before.data
    assert output_options(after) == output_options(before)


def test_first_discrete_output_from_capture_without_a_binary_template():
    files = source()
    raw = MoiIdentity(files[3])
    files[3] = archive(
        raw, [raw.data[r["offset"] : r["end_offset"]] for r in raw.records if r["class_id"] != 239]
    )
    edit = dict(
        action="allocate-discrete-output", object_instance=3200102, slot=1, name="Fan command"
    )
    original, _ = effective_source(files, identity())
    assert not any(row["class_id"] == 239 for row in original.records)
    image, proof = compile_io(files, identity(), edit)
    rebuilt = MoiIdentity(image)
    row = next(
        row for row in rebuilt.records if rebuilt.reader.scalar(row, 75) == proof["object_id"]
    )
    for pid, value in {31: "BO OUT1", 990: 1, 518: 0, 4: "On", 46: "Off", 931: 83}.items():
        assert rebuilt.reader.scalar(row, pid) == value
    assert proof["all_other_effective_records_preserved"] and not proof["graph_wires_changed"]
    for patch in ({"slot": 4}, {"expected_slot": 2}, {"template_instance": 5}):
        with pytest.raises(ValueError):
            compile_io(files, identity(), edit | patch)
    with pytest.raises(ValueError, match="free internally powered"):
        compile_io(configured(), identity(), edit | {"slot": 1})


async def test_new_discrete_output_publishes_neutral_and_releases_owned_pulse(output_link):
    peer, native, target, service = output_link
    edit = dict(
        action="allocate-discrete-output", object_instance=3200102, slot=3, name="Fan command"
    )
    _, plan = await review(output_link, edit)
    receipt = await service.apply(confirm(plan, output_wiring_confirmed=True))
    assert receipt["result"]["status"] == "verified", receipt["result"]
    assert receipt["result"]["published_io"]["neutral_present_value"] == 0
    obj = plan["compilation"]["object_id"]
    peer.command_test_object = ObjectIdentifier(obj)
    broker = native.bacnet
    pulse = await broker.plan_write(target["address"], obj, 1, 8)
    applied = await broker.apply_write(pulse["token"])
    try:
        assert int(peer.get_object_id(ObjectIdentifier(obj)).presentValue) == 1
    finally:
        assert (await broker.release(applied["command"]))["released"]
    assert int(peer.get_object_id(ObjectIdentifier(obj)).presentValue) == 0
