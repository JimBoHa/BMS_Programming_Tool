"""Authored graph and saved parameters for the legacy inline observation program."""

from types import SimpleNamespace

import pytest
from bacpypes3.pdu import PDUData
from bacpypes3.primitivedata import (
    CharacterString,
    Enumerated,
    ObjectIdentifier,
    Real,
    TagList,
    Unsigned,
)
from bms_tool.moi_identity import MoiIdentity, seal, sha
from bms_tool.moi_parameters import ParameterApplication
from bms_tool.native_inline_monitor import compile_monitor
from bms_tool.native_inline_monitor_transfer import (
    MonitorReview,
    reconstruct,
    validate_review,
    verify,
)
from bms_tool.native_inputs import archive, raw_property
from pydantic import ValidationError

from .test_controller_application import encoded, native_record
from .test_moi_parameters import parameters_source

ROOT = "controller/sequence"


def fixture(
    *,
    model="FX-PCV1630-0",
    duplicate=False,
    owner=ROOT,
    declared=18,
    header=18,
    wrong_source=False,
    wrong_pickup=False,
    fan=False,
    fan_port=4,
    direct=False,
):
    source, directory, parameters = parameters_source(model=model, cid=194, modules=0)
    editor = MoiIdentity(source)
    rows = [editor.data[r["offset"] : r["end_offset"]] for r in editor.records]

    def add(cid, instance, alias, ref, name, props, *, public_instance=None):
        ids = [
            (
                75,
                encoded(
                    ObjectIdentifier(
                        (alias, instance if public_instance is None else public_instance)
                    )
                ),
            ),
            (32527, encoded(CharacterString(ref))),
            (2390, encoded(CharacterString(name))),
        ]
        rows.append(
            native_record(
                cid,
                instance,
                ids
                + [
                    (pid, value if isinstance(value, bytes) else encoded(value))
                    for pid, value in props.items()
                ],
            )
        )

    def seq(cls, values):
        return b"".join(encoded(cls(v)) for v in values)

    old_ref = ROOT + ".536_" + ("18" if direct else "87")
    add(
        575,
        1,
        575,
        ROOT,
        "Root sequence",
        {
            3375: seq(ObjectIdentifier, [(556, 10), (570, 12), (536, 18)]),
            3117: seq(Unsigned, [2, 0, 1]),
            3118: b"\x3e"
            + seq(Unsigned, [0, 8000, 1, 3504 if not wrong_source else 3505])
            + b"\x3f",
            65030: Real(37.25),
        },
    )
    add(
        536,
        header,
        536,
        owner + old_ref[len(ROOT) :],
        "Nested activity",
        {},
        public_instance=declared,
    )
    if duplicate:
        add(536, 19, 536, ROOT + ".536_44", "Second declaration", {}, public_instance=18)
    sensor_ref = "controller/duct" if wrong_pickup else "controller/integral"
    add(
        556,
        10,
        556,
        ROOT + ".556_10",
        "DA-VP",
        {
            3399: b"\x3e"
            + encoded(CharacterString(sensor_ref))
            + b"\x4e\x4f"
            + encoded(Enumerated(85))
            + b"\x3f"
        },
    )
    add(570, 12, 570, ROOT + ".570_12", "Flow calculation", {3670: Enumerated(681)})
    add(527, 13, 2, ROOT + ".570_12.2_13", "SA-F", {117: Enumerated(84), 3365: Enumerated(3505)})
    add(
        240,
        14,
        0,
        "controller/integral",
        "DA-VP",
        {31: CharacterString("AI1-Int"), 117: Enumerated(58)},
    )
    add(240, 15, 0, "controller/duct", "DA-T", {31: CharacterString("UI IN1"), 117: Enumerated(64)})
    add(
        241,
        16,
        1,
        "controller/valve",
        "HTG-O",
        {31: CharacterString("CO OUT4"), 990: Unsigned(fan_port), 117: Enumerated(98)},
    )
    add(
        251,
        17,
        1,
        "controller/damper",
        "DPR-O",
        {31: CharacterString("BO1-Int,BO2-Int"), 990: Unsigned(6), 991: Unsigned(7)},
    )
    if fan:
        add(239, 20, 4, "controller/fan", "SF-C", {})
    return {3: archive(editor, rows), 11: directory, 12: parameters}


@pytest.mark.parametrize("model", ["MS-VMA1630-0", "FX-PCV1630-0"])
def test_preserves_control_graph_and_settings_and_has_independent_clock_witness(model):
    files = fixture(model=model)
    output, report = compile_monitor(files, 12)
    assert (output, report) == compile_monitor(files, 12)
    before = MoiIdentity(ParameterApplication(files[3], files[11], files[12]).compile()[0])
    after = MoiIdentity(output)
    original = before.reader.diagram(ROOT, retained_activity_refs=True)
    modified = after.reader.diagram(ROOT, retained_activity_refs=True)
    assert original["blocks"][2]["ref"] == ROOT + ".536_87"
    assert {b["ref"] for b in modified["blocks"][:3]} == {b["ref"] for b in original["blocks"]}
    assert after.reader.scalar(after.root, 904) == "saved"
    for original_row, now in zip(before.records, after.records[: len(before.records)], strict=True):
        if original_row["class_id"] != 575:
            assert original_row["sha256"] == now["sha256"]
        else:
            assert raw_property(after, now, 65030) == raw_property(before, original_row, 65030)
    assert modified["execution_order"] == [2, 0, 1, *range(3, 10)]
    assert (
        len(modified["connections"]) == 2 and modified["connections"][:1] == original["connections"]
    )
    obs = report["observations"]
    assert report["new_records"] == len(set(report["added_objects"])) == 26
    assert report["new_blocks"] == 7 and len(obs) == 5
    assert all(int(ObjectIdentifier(x)[1]) not in range(12, 19) for x in report["added_objects"])
    for data in obs.values():
        child = next(r for r in after.records if after.reader.scalar(r, 75) == data["object"])
        parent = after.reader.records[after.reader.scalar(child, 32527).rpartition(".")[0]]
        sem = TagList.decode(PDUData(raw_property(after, parent, 3399)[:-1]))
        target = str(CharacterString.decode(TagList([sem[1]])))
        assert int(Enumerated.decode(TagList([sem[-2]]))) == data["property"]
        assert after.reader.scalar(after.reader.records[target], 75) == data["source"]
        assert child["properties"][3113]["scalar"]["datatype"] == (
            "Boolean" if data["boolean"] else "Real"
        )
        if not data["boolean"]:
            assert child["properties"][661]["scalar"]["datatype"] == "Enumerated"
    wire = modified["connections"][-1]
    assert after.reader.scalar(after.reader.records[wire["source_ref"]], 3670) == 62
    assert after.reader.scalar(after.reader.records[wire["target_ref"]], 3670) == 79
    assert (wire["source_port"], wire["target_port"]) == (1081, 513)
    assert len(after.records) - len(before.records) == 26
    assert not any(after.reader.scalar(r, 3807) for r in after.records[len(before.records) :])


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(duplicate=True),
        dict(owner="controller/another"),
        dict(declared=23),
        dict(header=23),
        dict(duplicate=True, direct=True),
    ],
)
def test_rejects_unproven_or_ambiguous_activity_identity(kwargs):
    with pytest.raises(ValueError):
        MoiIdentity(fixture(**kwargs)[3]).reader.display_diagram(ROOT)


def test_strict_writer_graph_still_requires_the_exact_engineering_path():
    reader = MoiIdentity(fixture()[3]).reader
    with pytest.raises(ValueError, match="reference"):
        reader.diagram(ROOT)
    assert reader.display_diagram(ROOT)["blocks"][2]["ref"] == ROOT + ".536_87"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        (dict(fan=True), "valve"),
        (dict(fan_port=2), "valve"),
        (dict(wrong_source=True), "pickup"),
        (dict(wrong_pickup=True), "pickup"),
        (dict(model="another-model"), "62/62"),
    ],
)
def test_rejects_other_hardware_and_unverified_flow_path(kwargs, reason):
    with pytest.raises(ValueError, match=reason):
        compile_monitor(fixture(**kwargs), 100)


def test_refuses_duplicate_install_allocation_exhaustion_and_wrong_review():
    files = fixture()
    output, _ = compile_monitor(files, 100)
    with pytest.raises(ValueError, match="already includes"):
        compile_monitor({**files, 3: output}, 200)
    with pytest.raises(ValueError, match="Insufficient"):
        compile_monitor(files, 4194302)
    with pytest.raises(ValueError, match="valid"):
        compile_monitor(files, True)
    opts = dict(
        address="127.0.0.1",
        device="device,5136",
        operation_id="review-abc",
        first_instance=100,
        capture_id="a" * 32,
        snapshot_sha256="a" * 64,
    )
    with pytest.raises(ValidationError):
        MonitorReview(**{**opts, "first_instance": "100"})
    with pytest.raises(ValueError, match="exact"):
        validate_review(
            {
                "body": {"first_instance": 101},
                "digest": seal({"first_instance": 101}),
                "options": MonitorReview(**opts),
            }
        )


def test_readback_requires_original_lineage_and_verifies_effective_settings():
    from bms_tool.native_inline_monitor import PROFILE

    files = fixture()
    out, r = compile_monitor(files, 100)
    native = SimpleNamespace(storage=SimpleNamespace(load=lambda ident: ({}, files)))
    intent = dict(
        backup_id="b" * 32,
        operation_profile=PROFILE,
        monitor_confirmed=True,
        first_instance=100,
        compilation=r,
        payload_sha256=sha(out),
        native_payload_sha256=sha(MoiIdentity(out).data),
    )
    assert reconstruct(native, intent) == out
    assert verify(native, intent, {**files, 3: out})["native_graph_verified"]
    with pytest.raises(ValueError, match="complete"):
        verify(native, intent, files)
    with pytest.raises(ValueError, match="receipt"):
        reconstruct(native, {**intent, "first_instance": 700})


def observation_peer(peer, fault):
    import time
    from types import MethodType

    from bacpypes3.apdu import ReadPropertyACK
    from bacpypes3.basetypes import PriorityArray, PriorityValue
    from bacpypes3.constructeddata import Any
    from bacpypes3.errors import ExecutionError
    from bacpypes3.primitivedata import Boolean

    peer.files = fixture()
    peer.metadata.update({"model-name": "FX-PCV1630-0", "firmware-revision": "6.2.0.1054"})
    direct = peer.do_ReadPropertyRequest
    peer.clearance_reads = []
    peer.clock_started = None
    physical = {
        (0, 14): ("DA-VP", 58),
        (0, 15): ("DA-T", 64),
        (2, 13): ("SA-F", 84),
        (1, 16): ("HTG-O", 98),
        (1, 17): ("DPR-O", 98),
    }

    async def read(self, req):
        obj = req.objectIdentifier
        key = (int(obj[0]), int(obj[1]))
        pid = int(req.propertyIdentifier)
        if key == (8, self.instance) and pid == 787:
            value = Unsigned(90)
        elif key in physical:
            name, unit = physical[key]
            if pid == 77:
                value = CharacterString(name)
            elif pid == 117:
                value = Enumerated(unit)
            elif pid == 81:
                value = Boolean(fault == "out-of-service")
            elif pid == 3368:
                value = Boolean(False)
            elif pid == 103:
                value = Enumerated(0)
            elif pid == 85:
                value = Real(65)
            elif pid == 31:
                value = CharacterString("CO OUT4" if key[1] == 16 else "BO1-Int,BO2-Int")
            elif pid == 87:
                slots = [PriorityValue(null=()) for _ in range(16)]
                if fault == "override":
                    slots[7] = PriorityValue(real=0)
                value = PriorityArray(slots)
            else:
                raise ExecutionError(errorClass="property", errorCode="unknown-property")
        elif 100 <= key[1] < 126 and pid in (85, 103):
            installed = MoiIdentity(self.files[3])
            rd = installed.reader
            clock_output = {
                rd.scalar(child, 75)
                for ref, child in rd.records.items()
                if rd.scalar(child, 3365) == 85
                and (owner := rd.records.get(ref.rpartition(".")[0]))
                and rd.scalar(owner, 2390) == "Sampling interval witness"
            }
            if str(obj) not in clock_output:
                raise ExecutionError(errorClass="object", errorCode="unknown-object")
            if peer.clock_started is None:
                peer.clock_started = time.monotonic()
            elapsed = int(time.monotonic() - peer.clock_started)
            value = (
                Enumerated(0)
                if pid == 103
                else Real(37 if fault == "clock-stalled" else (2 - elapsed) % 60)
            )
        elif 100 <= key[1] < 126 and pid == 75:
            peer.clearance_reads.append(key)
            if key[1] == 100 and (
                fault == "silent"
                or fault in ("lost-first", "collision-after-loss")
                and peer.clearance_reads.count(key) == 1
            ):
                return
            if fault == "collision" or (fault == "collision-after-loss" and key[1] == 100):
                value = obj
            else:
                raise ExecutionError(errorClass="object", errorCode="unknown-object")
        else:
            return await direct(req)
        await self.response(
            ReadPropertyACK(
                context=req,
                objectIdentifier=obj,
                propertyIdentifier=req.propertyIdentifier,
                propertyValue=Any(value),
            )
        )

    peer.do_ReadPropertyRequest = MethodType(read, peer)


from .test_native_applications import native_link as native_link  # noqa: E402, F401


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("override", "command"),
        ("out-of-service", "quality"),
        ("collision", "unused"),
        ("collision-after-loss", "unused"),
        ("silent", "before deadline"),
    ],
)
async def test_real_datagrams_refuse_unproven_operating_conditions(native_link, fault, reason):
    from bms_tool.native_inline_monitor_transfer import review

    peer, _, _, service, target = native_link
    observation_peer(peer, fault)
    cap = await service.capture(**target, operation_id="capture-guard")
    options = MonitorReview(
        **target,
        operation_id="review-guard",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        first_instance=100,
    )
    with pytest.raises(ValueError, match=reason):
        await review(service, options)
    assert ("state", "start-restore") not in peer.events


async def test_lost_allocation_read_requires_a_new_attributed_absence(native_link):
    from bms_tool.native_inline_monitor_transfer import review

    peer, _, _, service, target = native_link
    observation_peer(peer, "lost-first")
    cap = await service.capture(**target, operation_id="capture-clearance")
    plan = await review(
        service,
        MonitorReview(
            **target,
            operation_id="retry-clearance",
            capture_id=cap["id"],
            snapshot_sha256=cap["snapshot_evidence_sha256"],
            first_instance=100,
        ),
    )
    assert plan["live_review"]["confirmed_absent"] == 26
    assert len(set(peer.clearance_reads)) == 26 and len(peer.clearance_reads) == 27
    assert ("state", "start-restore") not in peer.events


@pytest.mark.parametrize("clock", ["advancing", "stationary"])
async def test_real_datagrams_apply_reconcile_and_recover_reviewed_original(native_link, clock):
    from bms_tool.native_inline_monitor_transfer import MonitorApply, review

    peer, _, _, service, target = native_link
    observation_peer(peer, "clock-stalled" if clock == "stationary" else "")
    cap = await service.capture(**target, operation_id="capture-original")
    options = MonitorReview(
        **target,
        operation_id="review-observations",
        capture_id=cap["id"],
        snapshot_sha256=cap["snapshot_evidence_sha256"],
        first_instance=100,
    )
    plan = await review(service, options)
    req = MonitorApply(
        operation_id="apply-observations",
        token=plan["token"],
        review_sha256=plan["review_sha256"],
        monitor_confirmed=True,
        application_transfer_confirmed=True,
    )
    receipt = await service.apply_reviewed(req, default_edit=False, inline_kind="inline-monitor")
    assert receipt["result"]["status"] == "verified", receipt["result"]
    assert receipt["result"]["preservation"]["native_graph_verified"]
    evidence = receipt["result"]["diagnostic_execution"]
    assert evidence["read_only"] and len(evidence["samples"]) == 6
    assert evidence["status"] == clock
    assert not receipt["result"]["preservation"]["runtime_sampling_verified"]
    with pytest.raises(ValueError, match="consumed"):
        await service.apply_reviewed(req, default_edit=False, inline_kind="inline-monitor")
    restored = await service.preview_snapshot_restore(
        **target,
        operation_id="review-original",
        restore_capture_id=cap["id"],
        restore_snapshot_sha256=cap["snapshot_evidence_sha256"],
    )
    r = await service.apply_snapshot_restore(
        operation_id="restore-original",
        token=restored["token"],
        review_sha256=restored["review_sha256"],
        historical_application_confirmed=True,
        application_transfer_confirmed=True,
    )
    assert r["result"]["status"] == "verified", r["result"]
    assert len(MoiIdentity(peer.files[3]).records) == len(MoiIdentity(fixture()[3]).records)
    assert peer.events.count(("state", "start-restore")) == 2
